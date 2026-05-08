"""执行引擎。

按步骤执行任务计划，管理执行状态和重试逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from src.core.models import PlanStatus, Step, StepStatus, TaskPlan


@dataclass
class ExecutionResult:
    """执行结果。"""

    plan_id: str
    success: bool
    completed_steps: int
    total_steps: int
    errors: list[str]
    output: dict[str, Any]


class Executor:
    """任务执行引擎。"""

    def __init__(self) -> None:
        self._current_plan: TaskPlan | None = None
        self._tool_registry: dict[str, Any] = {}

    def register_tool(self, name: str, tool: Any) -> None:
        """注册工具实例。"""
        self._tool_registry[name] = tool
        logger.info(f"注册工具: {name}")

    @property
    def is_busy(self) -> bool:
        """当前是否有任务在执行。"""
        return (
            self._current_plan is not None
            and self._current_plan.status == PlanStatus.RUNNING
        )

    @property
    def current_plan(self) -> TaskPlan | None:
        """当前执行中的计划。"""
        return self._current_plan

    async def execute(self, plan: TaskPlan) -> ExecutionResult:
        """执行任务计划。

        按步骤顺序执行，支持依赖关系和重试。
        """
        self._current_plan = plan
        plan.status = PlanStatus.RUNNING
        errors: list[str] = []
        completed = 0

        logger.info(f"开始执行计划 {plan.id}: {plan.intent} ({len(plan.steps)} 步)")

        for step in plan.steps:
            if self._has_failed_dependency(step, plan):
                step.status = StepStatus.SKIPPED
                logger.warning(f"跳过步骤 {step.id}: 前置依赖失败")
                continue

            result = await self._execute_step(step)

            if result:
                step.status = StepStatus.DONE
                step.result = str(result)
                completed += 1
                logger.info(f"步骤 {step.id} 完成: {step.action[:50]}")
            else:
                # 循环重试直到成功或耗尽 max_retries
                retried = False
                while step.can_retry:
                    step.retry_count += 1
                    logger.warning(
                        f"步骤 {step.id} 失败，重试 {step.retry_count}/{step.max_retries}"
                    )
                    retry_result = await self._execute_step(step)
                    if retry_result:
                        step.status = StepStatus.DONE
                        step.result = str(retry_result)
                        completed += 1
                        retried = True
                        break

                if not retried:
                    step.status = StepStatus.FAILED
                    errors.append(f"步骤 {step.id} 执行失败（已重试 {step.retry_count} 次）: {step.action}")

        success = len(errors) == 0
        plan.status = PlanStatus.DONE if success else PlanStatus.FAILED
        self._current_plan = None

        return ExecutionResult(
            plan_id=plan.id,
            success=success,
            completed_steps=completed,
            total_steps=len(plan.steps),
            errors=errors,
            output={},
        )

    async def _execute_step(self, step: Step) -> Any:
        """执行单个步骤。"""
        step.status = StepStatus.RUNNING
        tool = self._tool_registry.get(step.tool)

        if tool is None:
            logger.error(f"未注册的工具: {step.tool}")
            return None

        try:
            if hasattr(tool, "execute"):
                return await tool.execute(step.action, step.params)
            elif callable(tool):
                return await tool(step.action, step.params)
            else:
                logger.error(f"工具 {step.tool} 没有可调用的接口")
                return None
        except Exception as e:
            logger.error(f"步骤 {step.id} 异常: {e}")
            step.error = str(e)
            return None

    def _has_failed_dependency(self, step: Step, plan: TaskPlan) -> bool:
        """检查步骤的前置依赖是否有失败的。"""
        for dep_id in step.depends_on:
            for s in plan.steps:
                if s.id == dep_id and s.status == StepStatus.FAILED:
                    return True
        return False
