from __future__ import annotations

from typing import Any

from app.command_center.model import StructuredModel
from app.command_center.schemas import (
    DemonstrationAnalysis,
    SkillDefinition,
    TaskMatchDecision,
    TestPlan,
    VerificationResult,
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
                "允许的 API Tool 对齐。关键请求未匹配或字段来源不确定时 compilable=false。"
            ),
            {"trace": trace, "catalog": catalog},
        )

    def compile_skill(
        self,
        analysis: DemonstrationAnalysis,
        trace: Any,
        catalog: Any,
    ) -> SkillDefinition:
        return self.model.generate(
            SkillDefinition,
            (
                "你是 Skill 编译智能体。V1 只把采购系统中“创建采购申请”业务动作"
                "编译成单步骤 API-only Skill。把演示中的申请人、物品、数量和原因"
                "抽象为 Skill 输入，步骤通过 literal.<输入名> 引用这些运行时输入。"
                "只使用目录内 Tool；写步骤必须提供幂等模板；引用只能来自 task、steps、literal。"
                "每个 input_bindings 的目标键必须写成 body.<字段> 或 path.<路径参数>；"
                "跨步骤结果使用 steps.<步骤>.output.<响应路径>。"
            ),
            {"analysis": analysis, "trace": trace, "catalog": catalog},
        )

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
