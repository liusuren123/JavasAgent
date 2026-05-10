"""技能执行反馈学习模块。

将技能执行结果反馈给 SkillLearner，形成学习闭环。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.tools.skill_executor_models import ExecutionRecord


# 参数摘要最大长度
PARAM_SUMMARY_MAX_LEN = 200


class SkillFeedback:
    """技能执行反馈器。

    负责将执行结果反馈给 SkillLearner 并生成参数/结果摘要。

    Usage::

        feedback = SkillFeedback(learner=my_learner)
        await feedback.send(record, params, result)
    """

    def __init__(self, learner: Any | None = None) -> None:
        """初始化反馈器。

        Args:
            learner: 技能学习器实例（可选）。
        """
        self._learner = learner

    @property
    def has_learner(self) -> bool:
        """是否有绑定学习器。"""
        return self._learner is not None

    async def send(
        self,
        record: ExecutionRecord,
        params: dict,
        result: dict,
    ) -> None:
        """将执行结果反馈给 SkillLearner。

        如果学习器存在，构造一个简单的 TaskPlan 和 ExecutionResult
        传给 ``record_execution()`` 形成学习闭环。

        Args:
            record: 执行记录。
            params: 原始参数。
            result: 原始结果。
        """
        if self._learner is None:
            return

        try:
            from src.core.models import (
                ExecutionResult,
                PlanStatus,
                Step,
                StepStatus,
                TaskPlan,
            )

            step = Step(
                id=f"step_{record.record_id}",
                action="execute_skill",
                tool=record.skill_name,
                params=params,
                status=StepStatus.DONE if record.success else StepStatus.FAILED,
                result=str(record.result_summary) if record.success else None,
                error=record.error if not record.success else None,
            )

            plan = TaskPlan(
                id=f"plan_{record.record_id}",
                intent=f"执行技能: {record.skill_name}",
                steps=[step],
                status=PlanStatus.DONE if record.success else PlanStatus.FAILED,
            )

            exec_result = ExecutionResult(
                plan_id=plan.id,
                success=record.success,
                completed_steps=1 if record.success else 0,
                total_steps=1,
                errors=[record.error] if record.error else [],
                output=result,
            )

            await self._learner.record_execution(plan, exec_result)
            logger.debug("已反馈学习器: {}", record.skill_name)

        except Exception:
            logger.exception("反馈学习器失败: {}", record.skill_name)

    @staticmethod
    def summarize_params(params: dict) -> dict:
        """生成参数摘要。

        对过长的值进行截断，避免历史记录占用过多内存。

        Args:
            params: 原始参数。

        Returns:
            参数摘要字典。
        """
        summary: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str) and len(value) > PARAM_SUMMARY_MAX_LEN:
                summary[key] = value[:PARAM_SUMMARY_MAX_LEN] + "..."
            elif isinstance(value, (list, dict)) and len(str(value)) > PARAM_SUMMARY_MAX_LEN:
                summary[key] = f"<{type(value).__name__} len={len(value)}>"
            else:
                summary[key] = value
        return summary

    @staticmethod
    def summarize_result(result: dict) -> dict:
        """生成结果摘要。

        Args:
            result: 原始结果。

        Returns:
            结果摘要字典。
        """
        summary: dict[str, Any] = {}
        for key, value in result.items():
            if isinstance(value, str) and len(value) > PARAM_SUMMARY_MAX_LEN:
                summary[key] = value[:PARAM_SUMMARY_MAX_LEN] + "..."
            elif isinstance(value, (list, dict)) and len(str(value)) > PARAM_SUMMARY_MAX_LEN:
                summary[key] = f"<{type(value).__name__} len={len(value)}>"
            else:
                summary[key] = value
        return summary
