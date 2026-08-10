from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from app.command_center.agent_runtime import (
    AgentRuntime,
    LegacyStructuredModelRuntime,
    RuntimeFailureCategory,
    RuntimeFailureSummary,
    RuntimeLimitError,
    RuntimeRequest,
    RuntimeResult,
    attach_runtime_failure,
    get_runtime_failure,
)
from app.command_center.model import StructuredModel
from app.command_center.schemas import (
    APIAttributionAnalysis,
    BrowserSkillDefinition,
    DemonstrationAnalysis,
    FieldMappingAnalysis,
    SkillDefinition,
    TaskMatchDecision,
    TestPlan,
    TraceSegmentation,
    VerificationResult,
)


logger = logging.getLogger(__name__)

_SKILL_NAME_CHARS = 160
_SKILL_SUMMARY_CHARS = 320
_SKILL_DETAIL_CHARS = 1200
_SKILL_INPUT_NAME_CHARS = 160
_SKILL_INPUT_DESCRIPTION_CHARS = 600
_SKILL_EXAMPLE_CHARS = 400
_SKILL_SUMMARY_INPUTS = 8
_SKILL_DETAIL_INPUTS = 32
_SKILL_CANDIDATE_LIMIT = 100


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
    def __init__(
        self,
        model: StructuredModel,
        match_runtime: AgentRuntime | None = None,
    ):
        self.model = model
        self.match_runtime = match_runtime or LegacyStructuredModelRuntime(model)

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
                "conclusive 表示整体是否足以继续学习核心业务能力，不表示必须不存在任何"
                "局部不确定性。核心业务动作已有可归因的网络交换时，可以保留局部不确定性"
                "并继续后续归因；不能仅因非核心导航、页面切换或辅助动作缺少 URL 或页面"
                "变化证据，就否决证据充分的核心业务动作。"
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
                "页面 value_fingerprint 与 query_parameter_fingerprints 中的 HMAC 指纹相同只能证明值相等，"
                "仍须结合控件语义、操作时序、API 归因和 Tool schema 判断业务含义；"
                "不能只根据字段名称建立映射，指纹缺失或不相等时也不能猜测对应关系。"
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
                "逐项检查 Skill 全部 input_bindings：每个 task.* 绑定都必须在该 case 的 "
                "fixture.source_task 中提供可解析值，每个 literal.* 绑定都必须在 invocation "
                "中提供可执行值；每个 steps.* 绑定必须引用该 Skill 中真实存在且位于当前步骤"
                "之前的前序步骤输出。不得省略必需绑定，也不得为不存在的前序步骤编造数据。"
            ),
            {"skill": skill},
        )

    def compile_browser_skill(
        self,
        trace: Any,
        allowed_origins: list[str],
    ) -> BrowserSkillDefinition:
        """Distill a UI-only demonstration without inventing page evidence."""
        skill = self.model.generate(
            BrowserSkillDefinition,
            (
                "你是企业浏览器操作 Skill 编译智能体。仅根据已脱敏的 UI 事件生成候选步骤，"
                "每一步必须引用真实存在的 source_ui_event_id，并复用该事件已有的语义定位信息。"
                "不得猜测 CSS/XPath、凭据、隐藏页面状态或未录制操作。"
                "输入、选择和点击的业务含义由上下文判断；无法判断副作用时标记 unknown。"
                "该候选只用于后续隔离浏览器验证，不得宣称已经验证或发布。"
            ),
            {"trace": trace, "allowed_origins": allowed_origins},
        )
        trace_payload = _as_payload(trace)
        known_events = {
            str(item["event_id"]): item
            for item in trace_payload.get("ui_events", [])
            if isinstance(item, dict) and item.get("event_id")
        }
        if str(skill.source_recording_id) != str(trace_payload.get("recording_id")):
            raise ValueError("browser skill references a different recording")
        if set(skill.allowed_origins) - set(allowed_origins):
            raise ValueError("browser skill references an origin outside the recording profile")
        for step in skill.steps:
            event = known_events.get(str(step.source_ui_event_id))
            if event is None:
                raise ValueError("browser skill references an unknown UI event")
            if step.action != event.get("action_type"):
                raise ValueError("browser skill action conflicts with recorded evidence")
        return skill.model_copy(update={"status": "candidate", "execution_mode": "browser"})

    def verify_result(
        self,
        skill: SkillDefinition,
        step_results: list[Any],
        observed_state: dict[str, Any],
    ) -> VerificationResult:
        return self.model.generate(
            VerificationResult,
            (
                "你是执行结果验证智能体。根据 Skill 成功条件、允许的 Tool 步骤输出和"
                "可用的执行后观察，判断员工请求是否完成。"
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
        if len(skills) > _SKILL_CANDIDATE_LIMIT:
            raise RuntimeLimitError(
                f"task matching supports at most {_SKILL_CANDIDATE_LIMIT} Skill candidates"
            )
        skill_by_id = {str(skill.skill_id): skill for skill in skills}

        def list_available_skills() -> list[dict[str, Any]]:
            """List compact summaries of Skills available for this request."""
            return [
                {
                    "skill_id": str(skill.skill_id),
                    "version": skill.version,
                    "name": _truncate(skill.name, _SKILL_NAME_CHARS),
                    "description": _truncate(
                        skill.description, _SKILL_SUMMARY_CHARS
                    ),
                    "status": skill.status,
                    "inputs": [
                        _compact_skill_input(item)
                        for item in skill.inputs[:_SKILL_SUMMARY_INPUTS]
                    ],
                    "input_count": len(skill.inputs),
                    "trigger_examples": [
                        _truncate(example, _SKILL_EXAMPLE_CHARS)
                        for example in skill.trigger_examples[:3]
                    ],
                }
                for skill in skills
            ]

        def get_available_skill(skill_id: str) -> dict[str, Any]:
            """Get one available Skill definition by exact Skill ID."""
            skill = skill_by_id.get(skill_id)
            if skill is None:
                raise ValueError("Skill is not available in this request")
            detail = skill.model_dump(mode="json")
            detail["name"] = _truncate(skill.name, _SKILL_NAME_CHARS)
            detail["description"] = _truncate(
                skill.description, _SKILL_DETAIL_CHARS
            )
            detail["inputs"] = [
                _compact_skill_input(item)
                for item in skill.inputs[:_SKILL_DETAIL_INPUTS]
            ]
            detail["input_count"] = len(skill.inputs)
            detail["trigger_examples"] = [
                _truncate(example, _SKILL_EXAMPLE_CHARS)
                for example in skill.trigger_examples[:5]
            ]
            return detail

        tools = ()
        payload: dict[str, Any] = {"user_request": user_request, "tasks": tasks}
        if self.match_runtime.capabilities.tool_loop:
            tools = (list_available_skills, get_available_skill)
        else:
            payload["skills"] = skills

        try:
            result = self.match_runtime.run_structured(
                RuntimeRequest(
                    role="task_matcher",
                    instructions=(
                        "你是任务匹配智能体。根据员工自然语言、候选业务对象和 Skill 的名称、"
                        "描述、示例及输入定义，选择唯一最合适的可执行 Skill。返回候选对象编号，"
                        "并把该 Skill 声明的所有必填输入提取到 literals；不要补造用户没有表达且"
                        "无法从上下文确定的业务值。"
                    ),
                    payload=payload,
                    output_schema=TaskMatchDecision,
                    tools=tools,
                    session_id=str(uuid4()),
                    limits=self.match_runtime.default_limits,
                )
            )
        except Exception as exc:
            failure = get_runtime_failure(exc)
            if failure is not None:
                _log_runtime_failure(failure)
            raise
        try:
            _validate_match_references(result.output, tasks, skills)
        except ValueError as exc:
            summary = RuntimeFailureSummary(
                failure_category=RuntimeFailureCategory.CANDIDATE_BOUNDARY_REJECTED,
                telemetry=result.telemetry,
            )
            attach_runtime_failure(exc, summary)
            _log_runtime_failure(summary)
            raise
        _log_runtime_telemetry(result)
        return result.output


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit]


def _compact_skill_input(item: Any) -> dict[str, Any]:
    payload = item.model_dump(mode="json")
    return {
        "name": _truncate(str(payload.get("name", "")), _SKILL_INPUT_NAME_CHARS),
        "type": payload.get("type"),
        "description": _truncate(
            str(payload.get("description") or ""), _SKILL_INPUT_DESCRIPTION_CHARS
        ),
        "required": bool(payload.get("required")),
    }


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


def _validate_match_references(
    decision: TaskMatchDecision,
    tasks: list[dict[str, Any]],
    skills: list[SkillDefinition],
) -> None:
    known_skill_ids = {skill.skill_id for skill in skills}
    known_task_ids = {str(task["task_id"]) for task in tasks if task.get("task_id")}
    if decision.selected_skill_id not in known_skill_ids:
        raise ValueError("agent match references unknown Skill")
    if set(decision.candidate_task_ids) - known_task_ids:
        raise ValueError("agent match references unknown task")


def _log_runtime_telemetry(result: RuntimeResult[TaskMatchDecision]) -> None:
    telemetry = result.telemetry
    tool_events = [
        {
            "name": event.name,
            "status": event.status,
            "duration_ms": event.duration_ms,
        }
        for event in telemetry.tool_events
    ]
    logger.info(
        "agent_runtime_completed trace_id=%s session_id=%s runtime=%s provider=%s "
        "model=%s role=%s model_calls=%s tool_events=%s input_tokens=%s "
        "output_tokens=%s total_tokens=%s duration_ms=%s selected_skill_id=%s",
        telemetry.trace_id,
        telemetry.session_id,
        telemetry.runtime,
        telemetry.provider,
        telemetry.model,
        telemetry.role,
        telemetry.model_calls,
        tool_events,
        telemetry.usage.input_tokens,
        telemetry.usage.output_tokens,
        telemetry.usage.total_tokens,
        telemetry.duration_ms,
        result.output.selected_skill_id,
    )


def _log_runtime_failure(summary: RuntimeFailureSummary) -> None:
    telemetry = summary.telemetry
    tool_events = [
        {
            "name": event.name,
            "status": event.status,
            "duration_ms": event.duration_ms,
        }
        for event in telemetry.tool_events
    ]
    logger.info(
        "agent_runtime_failed trace_id=%s session_id=%s runtime=%s provider=%s "
        "model=%s role=%s model_calls=%s tool_events=%s duration_ms=%s "
        "failure_category=%s",
        telemetry.trace_id,
        telemetry.session_id,
        telemetry.runtime,
        telemetry.provider,
        telemetry.model,
        telemetry.role,
        telemetry.model_calls,
        tool_events,
        telemetry.duration_ms,
        summary.failure_category.value,
    )


def _validate_uncertainties(
    uncertainties: list[Any],
    ui_ids: set[str],
    exchange_ids: set[str],
) -> None:
    for uncertainty in uncertainties:
        _validate_known(uncertainty.source_ui_event_ids, ui_ids, "UI event")
        _validate_known(uncertainty.source_exchange_ids, exchange_ids, "API exchange")
