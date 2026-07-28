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
                "你是 Skill 编译智能体。把已确认业务动作编译成 API-only Skill。"
                "只使用目录内 Tool；写步骤必须提供幂等模板；引用只能来自 task、steps、literal。"
            ),
            {"analysis": analysis, "trace": trace, "catalog": catalog},
        )

    def design_tests(self, skill: SkillDefinition) -> TestPlan:
        return self.model.generate(
            TestPlan,
            (
                "你是测试设计智能体。为候选 Skill 生成 normal、parameter_variation、"
                "idempotency 三类测试，每类恰好一个，数据仅用于本地测试系统。"
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
                "你是验证智能体。根据 Skill 成功条件、步骤结果和最终业务状态判断结果。"
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
                "你是任务匹配智能体。根据员工自然语言、候选业务对象和已发布 Skill，"
                "返回所有仍可能匹配的任务编号及唯一 Skill。不能在多个对象间私自选择。"
            ),
            {
                "user_request": user_request,
                "tasks": tasks,
                "skills": skills,
            },
        )
