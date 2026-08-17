from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from app.command_center.analysis_projection import project_trace_for_analysis
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
    DirectToolPlan,
    DirectToolVerification,
    FieldMappingAnalysis,
    SkillDefinition,
    StepResult,
    TaskMatchDecision,
    TestPlan,
    TraceSegmentation,
    VerificationResult,
)
from app.command_center.tool_catalog import ToolDefinition, validate_tool_arguments


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
        analysis_trace = project_trace_for_analysis(trace)
        system_codes = _ordered_trace_system_codes(analysis_trace)
        if len(system_codes) > 1:
            system_analyses = []
            for system_code in system_codes:
                system_trace = _trace_for_system(analysis_trace, system_code)
                analysis = self.model.generate(
                    TraceSegmentation,
                    (
                        "你是单一业务系统的演示时序分析智能体。只分析指定 system_code "
                        "内的已脱敏证据；说明该系统中实际发生的业务动作、辅助查询、验证查询、"
                        "导航和不确定性。不要因为跨系统目标尚未在本系统内完成就丢弃已有证据。"
                    ),
                    {"system_code": system_code, "trace": system_trace},
                )
                _validate_segmentation_references(analysis, trace)
                system_analyses.append(
                    {
                        "system_code": system_code,
                        "analysis": analysis.model_dump(mode="json"),
                    }
                )
            result = self.model.generate(
                TraceSegmentation,
                (
                    "你是跨系统演示协调智能体。根据各系统分析智能体的结论和全局证据顺序，"
                    "合并为一份跨系统时序分段。保留真实证据 ID，重新生成全局唯一、连续排序的"
                    " segment_id 和 sequence。各系统局部不完整不等于整体不可学习；由你结合"
                    "跨系统目标判断 conclusive。不要补造原始证据中不存在的动作或 API。"
                ),
                {
                    "objective": analysis_trace.get("objective"),
                    "system_analyses": system_analyses,
                    "global_evidence_order": _global_evidence_order(analysis_trace),
                },
            )
        else:
            result = self.model.generate(
                TraceSegmentation,
                (
                    "你是演示时序分段智能体。只依据已脱敏的 UI、页面变化和网络证据，"
                    "system_code 与 tab_id 用于识别跨系统页面切换；一个业务动作可以跨越多个系统，"
                    "把连续操作划分为业务动作、辅助查询、验证查询、导航、静态或遥测流量"
                    "以及不确定片段。不要猜测不存在的证据；不确定时明确列入 uncertainties。"
                    "conclusive 表示整体是否足以继续学习核心业务能力，不表示必须不存在任何"
                    "局部不确定性。核心业务动作已有可归因的网络交换时，可以保留局部不确定性"
                    "并继续后续归因；不能仅因非核心导航、页面切换或辅助动作缺少 URL 或页面"
                    "变化证据，就否决证据充分的核心业务动作。"
                ),
                {"trace": analysis_trace},
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
                "按每条交换自身的 system_code 在 Tool 目录中归因，保留跨系统先后关系。"
                "真实存在的片段、网络交换和 Tool；HTTP GET 本身不代表安全或业务主接口。"
            ),
            {
                "segmentation": segmentation,
                "trace": project_trace_for_analysis(trace),
                "catalog": catalog,
            },
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
                "跨系统时允许后续写操作引用前序读取步骤的可信输出；"
                "证据不足必须标记 uncertainty，不能用名称关键词硬猜。"
                "页面 value_fingerprint 与 query_parameter_fingerprints 中的 HMAC 指纹相同只能证明值相等，"
                "页面 value_fingerprint 也可以与 body_field_fingerprints 中按 JSON 路径记录的指纹比较；"
                "仍须结合控件语义、操作时序、API 归因和 Tool schema 判断业务含义；"
                "不能只根据字段名称建立映射，指纹缺失或不相等时也不能猜测对应关系。"
                f"{DEMONSTRATION_LITERAL_PROMPT}"
            ),
            {
                "attribution": attribution,
                "trace": project_trace_for_analysis(trace),
                "catalog": catalog,
            },
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
                "当 OpenAPI Body 字段是对象数组时，必须绑定整个数组（例如 body.items -> "
                "task.content.items），不得把演示中的元素数量编译成 body.items.0、"
                "body.items.1 等固定下标；数组输入类型声明为 array。"
                "成功条件必须描述可复用的业务不变量。不得把演示返回的业务对象 ID"
                "或其他单次运行值写成固定期望值；新执行产生的对象标识允许变化。"
                "如果该 Skill 适合作为业务记录上的用户动作，填写 action 元数据："
                "label 是用户可见动作名，required_record_fields 只声明稳定的适用字段，"
                "context_request 描述执行前需要通过只读 Tool 获取的上下文；不要包含页面位置。"
                f"{BINDING_PROTOCOL_PROMPT}"
            )
        else:
            payload = {
                "mapping": mapping,
                "attribution": attribution,
                "trace": project_trace_for_analysis(trace),
                "catalog": catalog,
            }
            prompt = (
                "你是通用 Skill 编译智能体。依据字段映射和 API 归因编译最小可复用 Skill。"
                "只使用归因为主业务、辅助或验证用途且存在于目录中的 Tool；不要复制单次演示值。"
                "输入绑定只使用 task、steps、literal 数据路径，目标以 body.、path. 或 query. 开头；"
                "写操作必须提供幂等模板，成功条件必须是可复用业务不变量。"
                "跨系统 Skill 应保留最小必要步骤，并使用 steps.<step_id>.output 路径传递前序输出。"
                "适合作为业务记录动作时必须填写 action 元数据，使客户端可根据 Skill 自动呈现动作；"
                "适用性仅声明稳定的对象字段要求，复杂业务判断仍由执行智能体结合证据完成。"
                f"{BINDING_PROTOCOL_PROMPT}"
            )
        skill = self.model.generate(
            SkillDefinition,
            prompt,
            payload,
        )
        if not legacy:
            _validate_skill_tool_references(skill, catalog)
            _validate_primary_system_coverage(skill, attribution, catalog)
            contract_errors = _skill_tool_contract_errors(skill, catalog)
            if contract_errors:
                repair_prompt = (
                    f"{prompt}"
                    "\n上一次候选 Skill 未满足 OpenAPI Tool 的确定性请求契约。"
                    "请重新生成完整 Skill，并为下列每个必填目标提供可解析的 input_bindings；"
                    "不得填入演示期固定业务值：\n- "
                    + "\n- ".join(contract_errors)
                )
                skill = self.model.generate(
                    SkillDefinition,
                    repair_prompt,
                    {**payload, "invalid_candidate_skill": skill},
                )
                _validate_skill_tool_references(skill, catalog)
                _validate_primary_system_coverage(skill, attribution, catalog)
                remaining_errors = _skill_tool_contract_errors(skill, catalog)
                if remaining_errors:
                    raise ValueError(
                        "compiled Skill violates Tool request contract: "
                        + "; ".join(remaining_errors)
                    )
        return skill

    def design_tests(self, skill: SkillDefinition) -> TestPlan:
        prompt = (
                "你是测试设计智能体。为候选 Skill 生成 normal、parameter_variation、"
                "idempotency 三类测试，每类恰好一个，数据仅用于本地采购测试系统。"
                "逐项检查 Skill 全部 input_bindings：每个 task.* 绑定都必须在该 case 的 "
                "fixture.source_task.content 中提供可解析值，每个 literal.* 绑定必须直接在 "
                "invocation 中提供（例如 literal.mode 对应 invocation.mode，不能再套 literal）；"
                "中提供可执行值；每个 steps.* 绑定必须引用该 Skill 中真实存在且位于当前步骤"
                "之前的前序步骤输出。不得省略必需绑定，也不得为不存在的前序步骤编造数据。"
            )
        plan = self.model.generate(
            TestPlan,
            prompt,
            {"skill": skill},
        )
        errors = _test_plan_binding_errors(skill, plan)
        if not errors:
            return plan
        repaired = self.model.generate(
            TestPlan,
            (
                f"{prompt}\n上一次测试计划违反执行协议，请重新生成完整计划：\n- "
                + "\n- ".join(errors)
            ),
            {"skill": skill, "invalid_test_plan": plan},
        )
        remaining = _test_plan_binding_errors(skill, repaired)
        if remaining:
            raise ValueError(
                "test plan violates Skill binding protocol: "
                + "; ".join(remaining)
            )
        return repaired

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

    def plan_tool_request(
        self,
        user_request: str,
        task_context: dict[str, Any],
        tools: list[ToolDefinition],
    ) -> DirectToolPlan:
        tool_payload = [_compact_tool_definition(tool) for tool in tools]
        runtime_request = RuntimeRequest(
            role="direct_tool_planner",
            instructions=(
                "你是企业业务系统的只读 Tool 规划智能体。根据员工请求、可信业务上下文"
                "和候选 Tool 的语义与参数，判断是否可直接完成任务。语义选择和参数提取"
                "由你完成；只能逐字使用候选 tool_id 和候选声明的参数。若信息不足返回 "
                "needs_input，若这些原子 Tool 不适用返回 not_applicable，以便系统继续尝试"
                "已有 Skill。不要编造业务值，不要请求或输出凭据。每次最多规划三个步骤。"
            ),
            payload={
                "user_request": user_request,
                "task_context": task_context,
                "tools": tool_payload,
            },
            output_schema=DirectToolPlan,
            session_id=str(uuid4()),
            limits=self.match_runtime.default_limits,
        )
        result = self.match_runtime.run_structured(runtime_request)
        _validate_direct_tool_plan(result.output, tools)
        logger.info(
            "agent_runtime_completed trace_id=%s role=%s status=%s tool_steps=%s",
            result.telemetry.trace_id,
            result.telemetry.role,
            result.output.status,
            len(result.output.steps),
        )
        return result.output

    def verify_tool_result(
        self,
        user_request: str,
        plan: DirectToolPlan,
        step_results: list[StepResult],
    ) -> DirectToolVerification:
        runtime_request = RuntimeRequest(
            role="direct_tool_verifier",
            instructions=(
                "你是只读 Tool 执行结果验证智能体。结合员工原始请求、已批准的 Tool "
                "计划和步骤结果，判断查询是否完成。HTTP 2xx 不能单独证明结果符合业务"
                "请求；信息不足时返回 inconclusive。不要请求或输出凭据。"
            ),
            payload={
                "user_request": user_request,
                "plan": plan.model_dump(mode="json"),
                "step_results": [
                    step_result.model_dump(mode="json")
                    for step_result in step_results
                ],
            },
            output_schema=DirectToolVerification,
            session_id=str(uuid4()),
            limits=self.match_runtime.default_limits,
        )
        result = self.match_runtime.run_structured(runtime_request)
        return result.output

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

        instructions = (
            "你是任务匹配智能体。根据员工自然语言、候选业务对象和 Skill 的名称、"
            "描述、示例及输入定义，选择唯一最合适的可执行 Skill。返回候选对象编号，"
            "并把该 Skill 声明的所有必填输入提取到 literals；不要补造用户没有表达且"
            "无法从上下文确定的业务值。candidate_task_ids 只能逐字复制 tasks 中的 "
            "task_id，绝不能填写 Skill ID 或自行生成编号；只有一个任务对象时直接返回"
            "该对象的 task_id。literals 可以包含对象数组；当 Skill 要求 items 等数组输入时，"
            "必须遍历可信只读 Tool 返回的全部明细记录，按 Skill 输入描述映射每一项。即使"
            "上下文已经提供 record_purpose 等部分输入，也必须继续提取其余全部必填输入。"
        )
        runtime_request = RuntimeRequest(
            role="task_matcher",
            instructions=instructions,
            payload=payload,
            output_schema=TaskMatchDecision,
            tools=tools,
            requires_tool_evidence=bool(tools),
            session_id=str(uuid4()),
            limits=self.match_runtime.default_limits,
        )
        for attempt in range(2):
            try:
                result = self.match_runtime.run_structured(runtime_request)
            except Exception as exc:
                failure = get_runtime_failure(exc)
                if failure is not None:
                    _log_runtime_failure(failure)
                raise
            try:
                _validate_match_references(result.output, tasks, skills)
            except ValueError as exc:
                if attempt == 0:
                    runtime_request = RuntimeRequest(
                        role=runtime_request.role,
                        instructions=(
                            instructions
                            + "\n上一轮输出违反了候选集合协议。根据 validation_feedback "
                            "重新检查证据并修正输出，不要重复无效标识符。"
                        ),
                        payload={
                            **payload,
                            "previous_invalid_output": result.output.model_dump(
                                mode="json"
                            ),
                            "validation_feedback": {
                                "error": str(exc),
                                "allowed_task_ids": sorted(
                                    str(task["task_id"])
                                    for task in tasks
                                    if task.get("task_id")
                                ),
                                "allowed_skill_ids": sorted(skill_by_id),
                            },
                        },
                        output_schema=runtime_request.output_schema,
                        tools=tools,
                        requires_tool_evidence=bool(tools),
                        session_id=str(uuid4()),
                        limits=runtime_request.limits,
                    )
                    continue
                summary = RuntimeFailureSummary(
                    failure_category=RuntimeFailureCategory.CANDIDATE_BOUNDARY_REJECTED,
                    telemetry=result.telemetry,
                )
                attach_runtime_failure(exc, summary)
                _log_runtime_failure(summary)
                raise
            _log_runtime_telemetry(result)
            return result.output
        raise AssertionError("task match repair loop ended unexpectedly")


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


def _compact_tool_definition(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "tool_id": tool.tool_id,
        "system_code": tool.system_code,
        "description": tool.description,
        "side_effect": tool.side_effect,
        "parameters": [
            {
                "name": parameter.name,
                "location": parameter.location,
                "type": parameter.type,
                "required": parameter.required,
                "description": parameter.description,
            }
            for parameter in tool.parameters
            if parameter.location in {"query", "path", "body"}
        ],
    }


def _validate_direct_tool_plan(
    plan: DirectToolPlan,
    tools: list[ToolDefinition],
) -> None:
    candidates = {tool.tool_id: tool for tool in tools}
    for step in plan.steps:
        tool = candidates.get(step.tool_id)
        if tool is None:
            raise ValueError("agent plan references unknown Tool")
        validate_tool_arguments(tool, step.arguments)


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


def _ordered_trace_system_codes(trace: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for item in trace.get("ui_events", []):
        code = (item.get("target") or {}).get("system_code")
        if code and code not in codes:
            codes.append(str(code))
    for collection in ("api_exchanges", "page_mutations"):
        for item in trace.get(collection, []):
            code = item.get("system_code")
            if code and code not in codes:
                codes.append(str(code))
    return codes


def _trace_for_system(trace: dict[str, Any], system_code: str) -> dict[str, Any]:
    return {
        "objective": trace.get("objective"),
        "ui_events": [
            item
            for item in trace.get("ui_events", [])
            if (item.get("target") or {}).get("system_code") == system_code
        ],
        "api_exchanges": [
            item
            for item in trace.get("api_exchanges", [])
            if item.get("system_code") == system_code
        ],
        "page_mutations": [
            item
            for item in trace.get("page_mutations", [])
            if item.get("system_code") == system_code
        ],
    }


def _global_evidence_order(trace: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for item in trace.get("ui_events", []):
        evidence.append(
            {
                "sequence": item.get("sequence"),
                "system_code": (item.get("target") or {}).get("system_code"),
                "evidence_type": "ui_event",
                "evidence_id": item.get("event_id"),
            }
        )
    for item in trace.get("api_exchanges", []):
        evidence.append(
            {
                "sequence": item.get("sequence"),
                "system_code": item.get("system_code"),
                "evidence_type": "api_exchange",
                "evidence_id": item.get("exchange_id"),
            }
        )
    return sorted(evidence, key=lambda item: int(item.get("sequence") or 0))


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


def _catalog_tool_systems(catalog: Any) -> dict[str, str]:
    payload = (
        catalog.to_agent_payload()
        if hasattr(catalog, "to_agent_payload")
        else catalog if isinstance(catalog, dict) else {}
    )
    return {
        str(item["tool_id"]): str(item["system_code"])
        for item in payload.get("tools", [])
        if isinstance(item, dict) and item.get("tool_id") and item.get("system_code")
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


def _skill_tool_contract_errors(
    skill: SkillDefinition,
    catalog: Any,
) -> list[str]:
    if not hasattr(catalog, "get"):
        return []
    errors: list[str] = []
    declared_inputs = {item.name for item in skill.inputs}
    prior_steps: dict[str, Any] = {}
    for step in skill.steps:
        tool = catalog.get(step.tool_id)
        targets = set(step.input_bindings)
        required_body = tool.body_schema.get("required", [])
        if isinstance(required_body, list):
            for name in required_body:
                target = f"body.{name}"
                if not any(
                    bound == target or bound.startswith(f"{target}.")
                    for bound in targets
                ):
                    errors.append(f"step {step.step_id}: missing {target}")
        for parameter in tool.parameters:
            if not parameter.required or parameter.location not in {
                "query",
                "path",
                "body",
            }:
                continue
            target = f"{parameter.location}.{parameter.name}"
            if target not in targets:
                errors.append(f"step {step.step_id}: missing {target}")
        for expression in step.input_bindings.values():
            if expression.startswith(("literal.", "task.content.")):
                input_name = expression.split(".", 2)[-1].split(".", 1)[0]
                if input_name not in declared_inputs:
                    errors.append(
                        f"step {step.step_id}: binding references undeclared Skill "
                        f"input: {expression}"
                    )
            if not expression.startswith("steps."):
                continue
            parts = expression.split(".")
            if len(parts) < 4 or parts[2] != "output":
                errors.append(
                    f"step {step.step_id}: invalid previous-step binding {expression}"
                )
                continue
            source_tool = prior_steps.get(parts[1])
            if source_tool is None:
                errors.append(
                    f"step {step.step_id}: unknown previous step in {expression}"
                )
                continue
            response_path = parts[3:]
            if source_tool.response_schema and not _schema_has_path(
                source_tool.response_schema,
                response_path,
            ):
                errors.append(
                    f"step {step.step_id}: response path not in OpenAPI schema: "
                    f"{expression}"
                )
        prior_steps[step.step_id] = tool
    return errors


def _schema_has_path(schema: dict[str, Any], path: list[str]) -> bool:
    current: Any = schema
    for part in path:
        if not isinstance(current, dict):
            return False
        if current.get("type") == "array":
            if not part.isdigit():
                return False
            current = current.get("items", {})
            continue
        properties = current.get("properties")
        if not isinstance(properties, dict) or part not in properties:
            return False
        current = properties[part]
    return True


def _test_plan_binding_errors(
    skill: SkillDefinition,
    plan: TestPlan,
) -> list[str]:
    task_paths = {
        expression.removeprefix("task.content.")
        for step in skill.steps
        for expression in step.input_bindings.values()
        if expression.startswith("task.content.")
    }
    literal_paths = {
        expression.removeprefix("literal.")
        for step in skill.steps
        for expression in step.input_bindings.values()
        if expression.startswith("literal.")
    }
    errors: list[str] = []
    for case in plan.cases:
        source_task = case.fixture.get("source_task", {})
        content = (
            source_task.get("content", {})
            if isinstance(source_task, dict)
            else {}
        )
        for path in task_paths:
            if not _mapping_has_path(content, path.split(".")):
                errors.append(
                    f"case {case.case_id}: missing fixture.source_task.content.{path}"
                )
        for path in literal_paths:
            if not _mapping_has_path(case.invocation, path.split(".")):
                errors.append(f"case {case.case_id}: missing invocation.{path}")
    return errors


def _mapping_has_path(value: Any, path: list[str]) -> bool:
    current = value
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _validate_primary_system_coverage(
    skill: SkillDefinition,
    attribution: APIAttributionAnalysis,
    catalog: Any,
) -> None:
    """Keep compiled steps faithful to systems the agent marked as core evidence."""

    tool_systems = _catalog_tool_systems(catalog)
    primary_systems = {
        tool_systems[tool_id]
        for segment in attribution.segments
        for tool_id in segment.primary_tool_ids
        if tool_id in tool_systems
    }
    compiled_systems = {
        tool_systems[step.tool_id]
        for step in skill.steps
        if step.tool_id in tool_systems
    }
    if not primary_systems.issubset(compiled_systems):
        raise ValueError("compiled Skill omits a primary system from attributed evidence")


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
