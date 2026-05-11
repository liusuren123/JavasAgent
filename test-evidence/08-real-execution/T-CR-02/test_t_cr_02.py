"""T-CR-02: Executor 执行步骤 — 实操测试。

Mock 工具注册到 Executor，验证 execute() 返回 ExecutionResult。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.core.models import (
    ExecutionResult,
    PlanStatus,
    Priority,
    Step,
    StepStatus,
    TaskPlan,
)
from src.core.executor import Executor


def _make_step(step_id: str, action: str, tool: str, depends_on: list[str] | None = None) -> Step:
    return Step(
        id=step_id,
        action=action,
        tool=tool,
        depends_on=depends_on or [],
    )


def _make_plan(steps: list[Step], priority: Priority = Priority.NORMAL) -> TaskPlan:
    return TaskPlan(
        id="test_plan_001",
        intent="测试执行",
        steps=steps,
        priority=priority,
    )


@pytest.fixture
def executor():
    return Executor()


@pytest.fixture
def mock_tools():
    """创建 mock 工具，均包含 execute 方法。"""
    tool_a = AsyncMock()
    tool_a.execute = AsyncMock(return_value={"output": "tool_a done"})

    tool_b = AsyncMock()
    tool_b.execute = AsyncMock(return_value={"output": "tool_b done"})

    failing_tool = AsyncMock()
    failing_tool.execute = AsyncMock(return_value=None)

    return {"tool_a": tool_a, "tool_b": tool_b, "failing_tool": failing_tool}


@pytest.mark.asyncio
async def test_execute_all_success(executor, mock_tools):
    """所有步骤成功执行。"""
    for name, tool in mock_tools.items():
        executor.register_tool(name, tool)

    steps = [
        _make_step("step_0", "步骤A", "tool_a"),
        _make_step("step_1", "步骤B", "tool_b"),
    ]
    plan = _make_plan(steps)

    result = await executor.execute(plan)

    assert isinstance(result, ExecutionResult)
    assert result.success is True, f"预期成功，errors: {result.errors}"
    assert result.completed_steps == 2
    assert result.total_steps == 2
    assert result.plan_id == "test_plan_001"
    print(f"[OK] 全部成功: completed={result.completed_steps}/{result.total_steps}")


@pytest.mark.asyncio
async def test_execute_step_status_done(executor, mock_tools):
    """执行后步骤状态应为 DONE。"""
    executor.register_tool("tool_a", mock_tools["tool_a"])
    steps = [_make_step("step_0", "步骤A", "tool_a")]
    plan = _make_plan(steps)

    await executor.execute(plan)

    assert steps[0].status == StepStatus.DONE
    print(f"[OK] 步骤状态: {steps[0].status}")


@pytest.mark.asyncio
async def test_execute_failing_step(executor, mock_tools):
    """失败步骤应标记为 FAILED，ExecutionResult.success 为 False。"""
    executor.register_tool("failing_tool", mock_tools["failing_tool"])
    steps = [_make_step("step_0", "会失败的步骤", "failing_tool")]
    plan = _make_plan(steps)

    result = await executor.execute(plan)

    assert result.success is False
    assert len(result.errors) > 0
    assert steps[0].status == StepStatus.FAILED
    print(f"[OK] 失败处理: status={steps[0].status}, errors={result.errors}")


@pytest.mark.asyncio
async def test_execute_dependency_skip(executor, mock_tools):
    """前置步骤失败时，依赖步骤应被跳过。"""
    executor.register_tool("failing_tool", mock_tools["failing_tool"])
    executor.register_tool("tool_a", mock_tools["tool_a"])

    steps = [
        _make_step("step_0", "会失败", "failing_tool"),
        _make_step("step_1", "依赖步骤", "tool_a", depends_on=["step_0"]),
    ]
    plan = _make_plan(steps)

    result = await executor.execute(plan)

    assert result.success is False
    assert steps[1].status == StepStatus.SKIPPED
    print(f"[OK] 依赖跳过: step_1 status={steps[1].status}")


@pytest.mark.asyncio
async def test_execute_plan_status_transitions(executor, mock_tools):
    """执行完成后 plan status 应为 DONE 或 FAILED。"""
    executor.register_tool("tool_a", mock_tools["tool_a"])
    steps = [_make_step("step_0", "步骤", "tool_a")]
    plan = _make_plan(steps)

    await executor.execute(plan)

    assert plan.status == PlanStatus.DONE
    print(f"[OK] 计划状态: {plan.status}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
