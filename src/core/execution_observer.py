"""执行观察者模块。

定义 ExecutionObserver 协议和 SkillLearningObserver 实现，
用于在执行流程中桥接 SkillLearner 实现持续学习。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from loguru import logger

from src.core.models import ExecutionResult, Step, TaskPlan


@runtime_checkable
class ExecutionObserver(Protocol):
    """执行观察者协议。

    实现 on_step_done 和 on_plan_done 即可作为 Executor 的观察者。
    """

    async def on_step_done(
        self, step: Step, result: Any, tool_name: str
    ) -> None:
        """单个步骤执行完成后回调。

        Args:
            step: 已完成的步骤
            result: 步骤执行返回值
            tool_name: 使用的工具名称
        """
        ...

    async def on_plan_done(
        self, plan: TaskPlan, execution_result: ExecutionResult
    ) -> None:
        """整个计划执行完成后回调。

        Args:
            plan: 已执行完毕的任务计划
            execution_result: 执行结果
        """
        ...


class SkillLearningObserver:
    """将执行结果桥接到 SkillLearner 的观察者。

    在每次步骤完成后记录单步信息，在整个计划完成后
    调用 SkillLearner.record_execution() 和 analyze_patterns()。
    """

    def __init__(self, skill_learner: Any) -> None:
        """初始化。

        Args:
            skill_learner: SkillLearner 实例
        """
        self._skill_learner = skill_learner
        self._step_records: list[dict[str, Any]] = []

    async def on_step_done(
        self, step: Step, result: Any, tool_name: str
    ) -> None:
        """记录单步执行结果。"""
        self._step_records.append(
            {
                "step_id": step.id,
                "action": step.action,
                "tool": tool_name,
                "result": str(result) if result is not None else None,
                "status": step.status.value if hasattr(step.status, "value") else str(step.status),
            }
        )
        logger.debug(
            "SkillLearningObserver: 记录步骤 {}/{}",
            step.id,
            tool_name,
        )

    async def on_plan_done(
        self, plan: TaskPlan, execution_result: ExecutionResult
    ) -> None:
        """计划完成后调用 SkillLearner 记录并分析。"""
        try:
            await self._skill_learner.record_execution(plan, execution_result)
            await self._skill_learner.analyze_patterns()
            logger.info(
                "SkillLearningObserver: 计划 {} 执行记录完成 (success={})",
                plan.id,
                execution_result.success,
            )
        except Exception:
            logger.exception(
                "SkillLearningObserver: 记录计划 {} 时出错",
                plan.id,
            )
        finally:
            self._step_records.clear()
