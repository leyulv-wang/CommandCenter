from __future__ import annotations

from typing import Any

from app.command_center.model import StructuredModel
from app.command_center.schemas import (
    APIAttributionAnalysis,
    DemonstrationAnalysis,
    FieldMappingAnalysis,
    SkillDefinition,
    TaskMatchDecision,
    TestPlan,
    TraceSegmentation,
    VerificationResult,
)


BINDING_PROTOCOL_PROMPT = (
    "绑定表达式只能引用数据路径：业务上下文使用 task.content.quantity，"
    "前序步骤输出使用 steps.create.output.data.id，运行时输入使用 "
    "literal.item_name。不能写成 literal(...)、函数调用、代码或直接业务值。"
)

DEMONSTRATION_LITERAL_PROMPT = (
    "员工在 UI 或 API 请求中直接输入、复用时会变化的值，应抽象为 "
    "literal.<语义输入名>。这类运行时输入不要求预先存在于 task 上下文，"
    "不能因此判定字段来源不确定。只有无法判断字段业务含义或关键请求未匹配时，"
    "才设置 compilable=false。"
)


class AgentSuite:
    def __init__(self, model: StructuredModel):
        self.model = model

    def analyze_demonstration(
        self,
        trace: Any,
        catalog: Any,
    ) -> DemonstrationAnalysis:
        return self.model.generate(
            DemonstrationAnalysis,
            (
                "你是演示理解智能体。识别员工真正完成的业务动作，把页面证据与"
                "允许的 API Tool 对齐。"
                f"{BINDING_PROTOCOL_PROMPT}"
                f"{DEMONSTRATION_LITERAL_PROMPT}"
            ),
            {"trace": trace, "catalog": catalog},
        )

    def segment_trace(self, trace: Any) -> TraceSegmentation:
        result = self.model.generate(
            TraceSegmentation,
            (
                "你是演示时序分段智能体。只依据已脱敏的 UI、页面变化和网络证据，"
                "把连续操作划分为业务动作、辅助查询、验证查询、导航、静态或遥测流量"
                "以及不确定片段。不要猜测不存在的证据；不确定时明确列入 uncertainties。"
            ),
            {"trace": trace},
        )
        _validate_segmentation_references(result, trace)
        return result

    def attribute_apis(
        self,
        segmentation: TraceSegmentation,
        trace: Any,
        catalog: Any,
    ) -> APIAttributionAnalysis:
        result = self.model.generate(
            APIAttributionAnalysis,
            (
                "你是 API 归因智能体。结合时序片段与 Tool 目录，区分主业务 API、"
                "辅助查询、验证查询、静态或遥测流量以及不确定候选。只能引用输入中"
                "真实存在的片段、网络交换和 Tool；HTTP GET 本身不代表安全或业务主接口。"
            ),
            {"segmentation": segmentation, "trace": trace, "catalog": catalog},
        )
        _validate_attribution_references(result, segmentation, trace, catalog)
        return result

    def map_fields(
        self,
        attribution: APIAttributionAnalysis,
        trace: Any,
        catalog: Any,
    ) -> FieldMappingAnalysis:
        result = self.model.generate(
            FieldMappingAnalysis,
            (
                "你是字段映射智能体。根据已脱敏页面证据、请求参数名、值指纹及 API 归因，"
                "把会随运行变化的业务输入映射到 query、path 或 body 目标。语义理解由你判断；"
                "证据不足必须标记 uncertainty，不能用名称关键词硬猜。"
                f"{DEMONSTRATION_LITERAL_PROMPT}"
            ),
            {"attribution": attribution, "trace": trace, "catalog": catalog},
        )
        _validate_mapping_references(result, attribution, trace, catalog)
        return result

    def compile_skill(self, mapping: Any, attribution: Any, trace: Any = None, catalog: Any = None) -> SkillDefinition:
        legacy = catalog is None
        if legacy:
            analysis, legacy_trace, legacy_catalog = mapping, attribution, trace
            payload = {"analysis": analysis, "trace": legacy_trace, "catalog": legacy_catalog}
            prompt = (
                "你是 Skill 编译智能体。根据演示分析编译可复用 Skill。只使用目录内 Tool；"
                "写步骤必须提供幂等模板；引用只能来自 task、steps、literal。"
                "每个 input_bindings 目标必须以 body.、path. 或 query. 开头。"
                "成功条件必须描述可复用的业务不变量。不得把演示返回的业务对象 ID"
                "或其他单次运行值写成固定期望值；新执行产生的对象标识允许变化。"
                f"{BINDING_PROTOCOL_PROMPT}"
            )
        else:
            payload = {
                "mapping": mapping,
                "attribution": attribution,
                "trace": trace,
                "catalog": catalog,
            }
            prompt = (
                "你是通用 Skill 编译智能体。依据字段映射和 API 归因编译最小可复用 Skill。"
                "只使用归因为主业务、辅助或验证用途且存在于目录中的 Tool；不要复制单次演示值。"
                "输入绑定只使用 task、steps、literal 数据路径，目标以 body.、path. 或 query. 开头；"
                "写操作必须提供幂等模板，成功条件必须是可复用业务不变量。"
                f"{BINDING_PROTOCOL_PROMPT}"
            )
        skill = self.model.generate(
            SkillDefinition,
            prompt,
            payload,
        )
        if not legacy:
            _validate_skill_tool_references(skill, catalog)
        return skill

    def design_tests(self, skill: SkillDefinition) -> TestPlan:
        return self.model.generate(
            TestPlan,
            (
                "你是测试设计智能体。为候选 Skill 生成 normal、parameter_variation、"
                "idempotency 三类测试，每类恰好一个，数据仅用于本地采购测试系统。"
                "每个 case 的 invocation 必须为 Skill 的全部 literal 输入提供可执行值。"
            ),
            {"skill": skill},
        )

    def verify_result(
        self,
        skill: SkillDefinition,
        step_results: list[Any],
        observed_state: dict[str, Any],
    ) -> VerificationResult:
        return self.model.generate(
            VerificationResult,
            (
                "你是验证智能体。V1 只验证采购系统：根据 Skill 成功条件、步骤输出和"
                "采购系统最终记录，确认本次采购申请是否存在且没有重复。"
                "HTTP 2xx 不能单独证明业务成功；未知副作用必须返回 inconclusive。"
                "StepResult.side_effect 中 occurred=true 表示已知写操作，"
                "不能仅因发生写操作而判定为未知副作用。应结合操作描述、幂等信息、"
                "步骤输出以及 _execution_evidence 中的执行前后状态，判断状态变化"
                "是否能由 Skill 解释；只有出现无法解释的变化或证据不足时才返回 "
                "inconclusive。"
            ),
            {
                "skill": skill,
                "step_results": step_results,
                "observed_state": observed_state,
            },
        )

    def match_request(
        self,
        user_request: str,
        tasks: list[dict[str, Any]],
        skills: list[SkillDefinition],
    ) -> TaskMatchDecision:
        return self.model.generate(
            TaskMatchDecision,
            (
                "你是任务匹配智能体。V1 只处理员工直接发起的采购申请。"
                "根据员工自然语言选择唯一已发布 Skill，返回唯一候选输入对象编号，"
                "并把申请人、物品名称、数量、采购原因等 Skill 所需输入提取到 literals。"
                "不要查询或假设办公用品任务。"
            ),
            {
                "user_request": user_request,
                "tasks": tasks,
                "skills": skills,
            },
        )


def _as_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value if isinstance(value, dict) else {}


def _trace_ids(trace: Any, collection: str, identifier: str) -> set[str]:
    payload = _as_payload(trace)
    return {
        str(item[identifier])
        for item in payload.get(collection, [])
        if isinstance(item, dict) and identifier in item
    }


def _catalog_tool_ids(catalog: Any) -> set[str]:
    if hasattr(catalog, "to_agent_payload"):
        payload = catalog.to_agent_payload()
    else:
        payload = catalog if isinstance(catalog, dict) else {}
    return {
        str(item["tool_id"])
        for item in payload.get("tools", [])
        if isinstance(item, dict) and item.get("tool_id")
    }


def _validate_known(references: list[Any], known: set[str], label: str) -> None:
    unknown = {str(reference) for reference in references} - known
    if unknown:
        raise ValueError(f"agent analysis references unknown {label}")


def _validate_segmentation_references(result: TraceSegmentation, trace: Any) -> None:
    ui_ids = _trace_ids(trace, "ui_events", "event_id")
    exchange_ids = _trace_ids(trace, "api_exchanges", "exchange_id")
    mutation_ids = _trace_ids(trace, "page_mutations", "mutation_id")
    segment_ids = [segment.segment_id for segment in result.segments]
    if len(segment_ids) != len(set(segment_ids)):
        raise ValueError("agent analysis contains duplicate segment identifiers")
    for segment in result.segments:
        _validate_known(segment.source_ui_event_ids, ui_ids, "UI event")
        _validate_known(segment.source_exchange_ids, exchange_ids, "API exchange")
        _validate_known(segment.source_mutation_ids, mutation_ids, "page mutation")
    _validate_known(result.ignored_ui_event_ids, ui_ids, "UI event")
    _validate_known(result.ignored_exchange_ids, exchange_ids, "API exchange")
    _validate_uncertainties(result.uncertainties, ui_ids, exchange_ids)


def _validate_attribution_references(
    result: APIAttributionAnalysis,
    segmentation: TraceSegmentation,
    trace: Any,
    catalog: Any,
) -> None:
    segment_ids = {segment.segment_id for segment in segmentation.segments}
    ui_ids = _trace_ids(trace, "ui_events", "event_id")
    exchange_ids = _trace_ids(trace, "api_exchanges", "exchange_id")
    tool_ids = _catalog_tool_ids(catalog)
    for segment in result.segments:
        _validate_known([segment.segment_id], segment_ids, "segment")
        _validate_known(
            [
                *segment.primary_tool_ids,
                *segment.supporting_tool_ids,
                *segment.verification_tool_ids,
            ],
            tool_ids,
            "Tool",
        )
        _validate_known(
            [
                *segment.primary_exchange_ids,
                *segment.supporting_exchange_ids,
                *segment.verification_exchange_ids,
                *segment.ignored_exchange_ids,
                *segment.uncertain_exchange_ids,
            ],
            exchange_ids,
            "API exchange",
        )
    _validate_uncertainties(result.uncertainties, ui_ids, exchange_ids)


def _validate_mapping_references(
    result: FieldMappingAnalysis,
    attribution: APIAttributionAnalysis,
    trace: Any,
    catalog: Any,
) -> None:
    ui_ids = _trace_ids(trace, "ui_events", "event_id")
    exchange_ids = _trace_ids(trace, "api_exchanges", "exchange_id")
    attributed_tools = {
        tool_id
        for segment in attribution.segments
        for tool_id in (
            *segment.primary_tool_ids,
            *segment.supporting_tool_ids,
            *segment.verification_tool_ids,
        )
    }
    _validate_known(list(attributed_tools), _catalog_tool_ids(catalog), "Tool")
    for mapping in result.mappings:
        _validate_known(mapping.source_ui_event_ids, ui_ids, "UI event")
        _validate_known(mapping.source_exchange_ids, exchange_ids, "API exchange")
    _validate_uncertainties(result.uncertainties, ui_ids, exchange_ids)


def _validate_skill_tool_references(skill: SkillDefinition, catalog: Any) -> None:
    _validate_known(
        [step.tool_id for step in skill.steps],
        _catalog_tool_ids(catalog),
        "Tool",
    )


def _validate_uncertainties(
    uncertainties: list[Any],
    ui_ids: set[str],
    exchange_ids: set[str],
) -> None:
    for uncertainty in uncertainties:
        _validate_known(uncertainty.source_ui_event_ids, ui_ids, "UI event")
        _validate_known(uncertainty.source_exchange_ids, exchange_ids, "API exchange")
