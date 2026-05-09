"""ExecutionObserver 和 SkillLearningObserver 测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.execution_observer import ExecutionObserver, SkillLearningObserver
from src.core.executor import Executor
from src.core.models import ExecutionResult, PlanStatus, Step, StepStatus, TaskPlan


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _make_step(
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


def _make_plan(steps: list[Step] | None = None) -> TaskPlan:
    if steps is None:
        steps = [_make_step()]
    return TaskPlan(id="plan_test", intent="测试计划", steps=steps)


def _make_tool(return_value: str = "ok") -> MagicMock:
    tool = MagicMock()
    tool.execute = AsyncMock(return_value=return_value)
    return tool


# ---------------------------------------------------------------------------
# ExecutionObserver 协议测试
# ---------------------------------------------------------------------------


class TestExecutionObserverProtocol:
    """ExecutionObserver Protocol 测试。"""

    def test_protocol_compliance_with_class(self) -> None:
        """实现了两个方法的类应满足协议。"""

        class MyObserver:
            async def on_step_done(self, step, result, tool_name):
                pass

            async def on_plan_done(self, plan, execution_result):
                pass

        assert isinstance(MyObserver(), ExecutionObserver)

    def test_protocol_non_compliance(self) -> None:
        """缺少方法的类不满足协议。"""

        class BadObserver:
            async def on_step_done(self, step, result, tool_name):
                pass

        assert not isinstance(BadObserver(), ExecutionObserver)

    def test_skill_learning_observer_satisfies_protocol(self) -> None:
        """SkillLearningObserver 应满足 ExecutionObserver 协议。"""
        mock_learner = MagicMock()
        observer = SkillLearningObserver(mock_learner)
        assert isinstance(observer, ExecutionObserver)


# ---------------------------------------------------------------------------
# SkillLearningObserver 测试
# ---------------------------------------------------------------------------


class TestSkillLearningObserver:
    """SkillLearningObserver 测试。"""

    def test_on_step_done_records_step(self) -> None:
        """on_step_done 应记录步骤信息。"""
        mock_learner = MagicMock()
        observer = SkillLearningObserver(mock_learner)

        step = _make_step()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(observer.on_step_done(step, "result_val", "mock_tool"))

        assert len(observer._step_records) == 1
        assert observer._step_records[0]["step_id"] == "s0"
        assert observer._step_records[0]["tool"] == "mock_tool"
        assert observer._step_records[0]["result"] == "result_val"

    def test_on_step_done_multiple(self) -> None:
        """多次调用 on_step_done 应累积记录。"""
        mock_learner = MagicMock()
        observer = SkillLearningObserver(mock_learner)

        loop = asyncio.get_event_loop()
        s1 = _make_step("s1")
        s2 = _make_step("s2")
        loop.run_until_complete(observer.on_step_done(s1, "r1", "tool_a"))
        loop.run_until_complete(observer.on_step_done(s2, "r2", "tool_b"))

        assert len(observer._step_records) == 2

    def test_on_plan_done_calls_record_execution(self) -> None:
        """on_plan_done 应调用 skill_learner.record_execution。"""
        mock_learner = MagicMock()
        mock_learner.record_execution = AsyncMock()
        mock_learner.analyze_patterns = AsyncMock(return_value=[])

        observer = SkillLearningObserver(mock_learner)

        plan = _make_plan()
        exec_result = ExecutionResult(
            plan_id="plan_test", success=True, completed_steps=1, total_steps=1
        )

        loop = asyncio.get_event_loop()
        loop.run_until_complete(observer.on_plan_done(plan, exec_result))

        mock_learner.record_execution.assert_awaited_once_with(plan, exec_result)

    def test_on_plan_done_calls_analyze_patterns(self) -> None:
        """on_plan_done 应调用 skill_learner.analyze_patterns。"""
        mock_learner = MagicMock()
        mock_learner.record_execution = AsyncMock()
        mock_learner.analyze_patterns = AsyncMock(return_value=[])

        observer = SkillLearningObserver(mock_learner)

        plan = _make_plan()
        exec_result = ExecutionResult(
            plan_id="plan_test", success=True, completed_steps=1, total_steps=1
        )

        loop = asyncio.get_event_loop()
        loop.run_until_complete(observer.on_plan_done(plan, exec_result))

        mock_learner.analyze_patterns.assert_awaited_once()

    def test_on_plan_done_clears_step_records(self) -> None:
        """on_plan_done 完成后应清除步骤记录。"""
        mock_learner = MagicMock()
        mock_learner.record_execution = AsyncMock()
        mock_learner.analyze_patterns = AsyncMock(return_value=[])

        observer = SkillLearningObserver(mock_learner)

        step = _make_step()
        plan = _make_plan()
        exec_result = ExecutionResult(
            plan_id="plan_test", success=True, completed_steps=1, total_steps=1
        )

        loop = asyncio.get_event_loop()
        loop.run_until_complete(observer.on_step_done(step, "r", "tool"))
        assert len(observer._step_records) == 1

        loop.run_until_complete(observer.on_plan_done(plan, exec_result))
        assert len(observer._step_records) == 0

    def test_on_plan_done_handles_learner_exception(self) -> None:
        """skill_learner 抛异常时 on_plan_done 不应传播。"""
        mock_learner = MagicMock()
        mock_learner.record_execution = AsyncMock(side_effect=RuntimeError("boom"))
        mock_learner.analyze_patterns = AsyncMock(return_value=[])

        observer = SkillLearningObserver(mock_learner)
        plan = _make_plan()
        exec_result = ExecutionResult(
            plan_id="plan_test", success=True, completed_steps=1, total_steps=1
        )

        loop = asyncio.get_event_loop()
        # 不应抛出异常
        loop.run_until_complete(observer.on_plan_done(plan, exec_result))


# ---------------------------------------------------------------------------
# Executor + Observer 集成测试
# ---------------------------------------------------------------------------


class TestExecutorObserverIntegration:
    """Executor 通知 Observer 的集成测试。"""

    def test_observer_on_step_done_called(self) -> None:
        """步骤成功完成后应通知 observer.on_step_done。"""
        executor = Executor()
        executor.register_tool("mock_tool", _make_tool())

        mock_observer = MagicMock()
        mock_observer.on_step_done = AsyncMock()
        mock_observer.on_plan_done = AsyncMock()
        executor.add_observer(mock_observer)

        plan = _make_plan()
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(executor.execute(plan))

        assert result.success is True
        mock_observer.on_step_done.assert_awaited_once()
        call_args = mock_observer.on_step_done.call_args
        assert call_args[0][2] == "mock_tool"  # tool_name

    def test_observer_on_step_done_not_called_on_failure(self) -> None:
        """步骤失败不应通知 observer.on_step_done。"""
        executor = Executor()
        fail_tool = MagicMock()
        fail_tool.execute = AsyncMock(return_value=None)
        executor.register_tool("mock_tool", fail_tool)

        mock_observer = MagicMock()
        mock_observer.on_step_done = AsyncMock()
        mock_observer.on_plan_done = AsyncMock()
        executor.add_observer(mock_observer)

        step = _make_step(max_retries=0)
        plan = _make_plan(steps=[step])
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(executor.execute(plan))

        assert result.success is False
        mock_observer.on_step_done.assert_not_awaited()

    def test_observer_on_plan_done_called(self) -> None:
        """计划完成后应通知 observer.on_plan_done。"""
        executor = Executor()
        executor.register_tool("mock_tool", _make_tool())

        mock_observer = MagicMock()
        mock_observer.on_step_done = AsyncMock()
        mock_observer.on_plan_done = AsyncMock()
        executor.add_observer(mock_observer)

        plan = _make_plan()
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(executor.execute(plan))

        assert result.success is True
        mock_observer.on_plan_done.assert_awaited_once()
        call_args = mock_observer.on_plan_done.call_args
        # 第一参数是 plan，第二参数是 ExecutionResult
        assert call_args[0][0] is plan
        assert call_args[0][1] is result

    def test_observer_on_plan_done_called_on_failure(self) -> None:
        """即使计划失败也应通知 observer.on_plan_done。"""
        executor = Executor()
        fail_tool = MagicMock()
        fail_tool.execute = AsyncMock(return_value=None)
        executor.register_tool("mock_tool", fail_tool)

        mock_observer = MagicMock()
        mock_observer.on_step_done = AsyncMock()
        mock_observer.on_plan_done = AsyncMock()
        executor.add_observer(mock_observer)

        step = _make_step(max_retries=0)
        plan = _make_plan(steps=[step])
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(executor.execute(plan))

        assert result.success is False
        mock_observer.on_plan_done.assert_awaited_once()

    def test_multiple_observers(self) -> None:
        """多个 observer 都应被通知。"""
        executor = Executor()
        executor.register_tool("mock_tool", _make_tool())

        observers = []
        for _ in range(3):
            obs = MagicMock()
            obs.on_step_done = AsyncMock()
            obs.on_plan_done = AsyncMock()
            observers.append(obs)
            executor.add_observer(obs)

        plan = _make_plan()
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(executor.execute(plan))

        for obs in observers:
            obs.on_step_done.assert_awaited_once()
            obs.on_plan_done.assert_awaited_once()

    def test_observer_exception_does_not_break_execution(self) -> None:
        """observer 异常不应中断执行。"""
        executor = Executor()
        executor.register_tool("mock_tool", _make_tool())

        bad_observer = MagicMock()
        bad_observer.on_step_done = AsyncMock(side_effect=RuntimeError("observer crash"))
        bad_observer.on_plan_done = AsyncMock(side_effect=RuntimeError("observer crash"))
        executor.add_observer(bad_observer)

        plan = _make_plan()
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(executor.execute(plan))

        # 执行应正常完成
        assert result.success is True
        assert result.completed_steps == 1

    def test_no_observer_does_not_break(self) -> None:
        """没有 observer 时执行应正常。"""
        executor = Executor()
        executor.register_tool("mock_tool", _make_tool())

        plan = _make_plan()
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(executor.execute(plan))

        assert result.success is True

    def test_observer_with_retry_success(self) -> None:
        """重试成功后应通知 on_step_done。"""
        executor = Executor()
        tool = MagicMock()
        tool.execute = AsyncMock(side_effect=[None, "retry_ok"])
        executor.register_tool("mock_tool", tool)

        mock_observer = MagicMock()
        mock_observer.on_step_done = AsyncMock()
        mock_observer.on_plan_done = AsyncMock()
        executor.add_observer(mock_observer)

        step = _make_step(max_retries=1)
        plan = _make_plan(steps=[step])
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(executor.execute(plan))

        assert result.success is True
        # 重试成功后应通知一次 on_step_done
        mock_observer.on_step_done.assert_awaited_once()
