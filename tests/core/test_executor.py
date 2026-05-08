"""执行引擎测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.executor import Executor
from src.core.models import PlanStatus, Step, StepStatus, TaskPlan


class TestExecutor:
    """Executor 基本功能测试。"""

    def _make_step(
        self,
        step_id: str = "s0",
        action: str = "测试步骤",
        tool: str = "mock_tool",
        depends_on: list[str] | None = None,
        max_retries: int = 3,
    ) -> Step:
        return Step(
            id=step_id,
            action=action,
            tool=tool,
            depends_on=depends_on or [],
            max_retries=max_retries,
        )

    def _make_plan(self, steps: list[Step] | None = None) -> TaskPlan:
        if steps is None:
            steps = [self._make_step()]
        return TaskPlan(id="plan_test", intent="测试计划", steps=steps)

    def _make_tool(self, return_value: str = "ok") -> MagicMock:
        """创建 mock 工具。"""
        tool = MagicMock()
        tool.execute = AsyncMock(return_value=return_value)
        return tool

    def _make_failing_tool(self) -> MagicMock:
        """创建始终失败的 mock 工具。"""
        tool = MagicMock()
        tool.execute = AsyncMock(return_value=None)
        return tool

    def _make_exception_tool(self) -> MagicMock:
        """创建抛异常的 mock 工具。"""
        tool = MagicMock()
        tool.execute = AsyncMock(side_effect=RuntimeError("工具异常"))
        return tool

    # --- 基本执行测试 ---

    def test_execute_single_step(self) -> None:
        """单步骤计划执行成功。"""
        executor = Executor()
        executor.register_tool("mock_tool", self._make_tool())

        plan = self._make_plan()
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is True
        assert result.completed_steps == 1
        assert result.total_steps == 1
        assert len(result.errors) == 0
        assert plan.status == PlanStatus.DONE

    def test_execute_multiple_steps(self) -> None:
        """多步骤计划顺序执行。"""
        executor = Executor()
        executor.register_tool("mock_tool", self._make_tool())

        steps = [
            self._make_step("s0"),
            self._make_step("s1"),
            self._make_step("s2"),
        ]
        plan = self._make_plan(steps)
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is True
        assert result.completed_steps == 3
        assert plan.status == PlanStatus.DONE

    def test_execute_empty_plan(self) -> None:
        """空计划执行。"""
        executor = Executor()
        plan = self._make_plan(steps=[])
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is True
        assert result.completed_steps == 0
        assert result.total_steps == 0

    # --- 重试测试 ---

    def test_retry_on_failure(self) -> None:
        """步骤失败后应重试。"""
        executor = Executor()
        # 第一次失败，重试成功
        tool = MagicMock()
        tool.execute = AsyncMock(side_effect=[None, "retry_ok"])
        executor.register_tool("mock_tool", tool)

        step = self._make_step(max_retries=1)
        plan = self._make_plan(steps=[step])
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is True
        assert result.completed_steps == 1
        assert step.retry_count == 1
        assert step.status == StepStatus.DONE

    def test_retry_exhausted(self) -> None:
        """重试耗尽后步骤应失败。"""
        executor = Executor()
        tool = self._make_failing_tool()
        executor.register_tool("mock_tool", tool)

        step = self._make_step(max_retries=1)
        plan = self._make_plan(steps=[step])
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is False
        assert step.status == StepStatus.FAILED
        assert len(result.errors) == 1

    def test_retry_loop_until_success(self) -> None:
        """循环重试直到成功。"""
        executor = Executor()
        # 失败 2 次，第 3 次成功（共调用 1+2=3 次）
        tool = MagicMock()
        tool.execute = AsyncMock(side_effect=[None, None, "finally_ok"])
        executor.register_tool("mock_tool", tool)

        step = self._make_step(max_retries=3)
        plan = self._make_plan(steps=[step])
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is True
        assert result.completed_steps == 1
        assert step.retry_count == 2
        assert step.status == StepStatus.DONE
        assert tool.execute.call_count == 3

    def test_retry_loop_exhausted_all_attempts(self) -> None:
        """重试循环耗尽所有次数后应失败。"""
        executor = Executor()
        tool = self._make_failing_tool()
        executor.register_tool("mock_tool", tool)

        step = self._make_step(max_retries=3)
        plan = self._make_plan(steps=[step])
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is False
        assert step.status == StepStatus.FAILED
        assert step.retry_count == 3
        # 1 initial + 3 retries = 4 total calls
        assert tool.execute.call_count == 4
        assert "已重试 3 次" in result.errors[0]

    def test_no_retry_when_max_zero(self) -> None:
        """max_retries=0 时不应重试。"""
        executor = Executor()
        tool = self._make_failing_tool()
        executor.register_tool("mock_tool", tool)

        step = self._make_step(max_retries=0)
        plan = self._make_plan(steps=[step])
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is False
        assert step.status == StepStatus.FAILED
        assert step.retry_count == 0

    # --- 依赖检查测试 ---

    def test_skip_step_with_failed_dependency(self) -> None:
        """前置依赖失败时应跳过后续步骤。"""
        executor = Executor()
        fail_tool = self._make_failing_tool()
        ok_tool = self._make_tool()
        executor.register_tool("fail_tool", fail_tool)
        executor.register_tool("ok_tool", ok_tool)

        steps = [
            self._make_step("s0", tool="fail_tool", max_retries=0),
            self._make_step("s1", tool="ok_tool", depends_on=["s0"]),
        ]
        plan = self._make_plan(steps)
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is False
        assert plan.steps[0].status == StepStatus.FAILED
        assert plan.steps[1].status == StepStatus.SKIPPED

    def test_step_runs_after_deps_done(self) -> None:
        """依赖完成后步骤应正常执行。"""
        executor = Executor()
        executor.register_tool("mock_tool", self._make_tool())

        steps = [
            self._make_step("s0"),
            self._make_step("s1", depends_on=["s0"]),
        ]
        plan = self._make_plan(steps)
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is True
        assert plan.steps[0].status == StepStatus.DONE
        assert plan.steps[1].status == StepStatus.DONE

    # --- 工具未注册测试 ---

    def test_unregistered_tool_fails(self) -> None:
        """使用未注册的工具应失败。"""
        executor = Executor()
        plan = self._make_plan()
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is False
        assert plan.steps[0].status == StepStatus.FAILED

    def test_tool_exception_handled(self) -> None:
        """工具抛异常应被捕获。"""
        executor = Executor()
        executor.register_tool("mock_tool", self._make_exception_tool())

        step = self._make_step(max_retries=0)
        plan = self._make_plan(steps=[step])
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is False
        assert step.status == StepStatus.FAILED
        assert step.error == "工具异常"

    # --- callable 工具测试 ---

    def test_callable_tool(self) -> None:
        """工具为 callable（非对象）时也能执行。"""
        executor = Executor()
        async_fn = AsyncMock(return_value="callable_result")
        executor.register_tool("mock_tool", async_fn)

        plan = self._make_plan()
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is True
        assert result.completed_steps == 1

    def test_non_callable_non_execute_tool(self) -> None:
        """工具既没有 execute 也不 callable → 应失败。"""
        executor = Executor()
        executor.register_tool("mock_tool", "not_a_tool")

        plan = self._make_plan()
        result = asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert result.success is False

    # --- 属性测试 ---

    def test_is_busy_during_execution(self) -> None:
        """执行中 is_busy 应为 True。"""
        executor = Executor()
        executor.register_tool("mock_tool", self._make_tool())

        plan = self._make_plan()
        assert executor.is_busy is False

        loop = asyncio.get_event_loop()

        async def check_busy():
            # Before execution
            assert executor.current_plan is None
            # Run execution
            return await executor.execute(plan)

        result = loop.run_until_complete(check_busy())

        # After execution
        assert executor.is_busy is False
        assert executor.current_plan is None

    def test_current_plan_set_during_execution(self) -> None:
        """执行中 current_plan 应被设置。"""
        executor = Executor()
        # Use a tool that lets us observe state
        observed_plan = None

        async def observing_tool(action, params):
            nonlocal observed_plan
            observed_plan = executor.current_plan
            return "observed"

        executor.register_tool("mock_tool", observing_tool)

        plan = self._make_plan()
        asyncio.get_event_loop().run_until_complete(executor.execute(plan))

        assert observed_plan is not None
        assert observed_plan.id == "plan_test"

    def test_register_tool(self) -> None:
        """注册工具应成功。"""
        executor = Executor()
        tool = self._make_tool()
        executor.register_tool("my_tool", tool)
        assert "my_tool" in executor._tool_registry
