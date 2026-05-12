# -*- coding: utf-8 -*-
"""StepExecutor 测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.skills.context import SkillContext
from src.skills.step_executor import StepExecutor


# ======================================================================
# Mock action 函数（注册到 ACTION_REGISTRY 中）
# ======================================================================

async def _mock_key_combo(step, context, platform=None, perception=None,
                          humanhand=None, executor=None, skill_executor=None):
    return {"success": True, "keys": step.get("keys", "")}

async def _mock_wait(step, context, platform=None, perception=None,
                     humanhand=None, executor=None, skill_executor=None):
    return {"success": True, "duration": step.get("duration", 1.0)}

async def _mock_fail(step, context, platform=None, perception=None,
                     humanhand=None, executor=None, skill_executor=None):
    return {"success": False, "error": "模拟失败"}


@pytest.fixture(autouse=True)
def patch_registry(monkeypatch):
    """替换 ACTION_REGISTRY 为 mock 版本。"""
    from src.skills import actions
    mock_registry = {
        "key_combo": _mock_key_combo,
        "wait": _mock_wait,
        "fail_action": _mock_fail,
    }
    monkeypatch.setattr(actions, "ACTION_REGISTRY", mock_registry)
    # 也覆盖 get_action_registry
    monkeypatch.setattr(actions, "get_action_registry", lambda: mock_registry)


@pytest.fixture
def executor():
    return StepExecutor()


class TestExecuteStep:
    @pytest.mark.asyncio
    async def test_execute_step_routes_to_action(self, executor):
        ctx = SkillContext()
        step = {"action": "key_combo", "keys": "ctrl+s"}
        result = await executor.execute_step(step, ctx)
        assert result["success"] is True
        assert result["keys"] == "ctrl+s"

    @pytest.mark.asyncio
    async def test_execute_step_unknown_action(self, executor):
        ctx = SkillContext()
        step = {"action": "nonexistent_action"}
        result = await executor.execute_step(step, ctx)
        assert result["success"] is False
        assert "未知 action" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_step_no_action(self, executor):
        ctx = SkillContext()
        step = {"keys": "ctrl+s"}
        result = await executor.execute_step(step, ctx)
        assert result["success"] is False
        assert "action" in result["error"]


class TestExecuteSteps:
    @pytest.mark.asyncio
    async def test_execute_steps_sequential(self, executor):
        ctx = SkillContext()
        steps = [
            {"action": "key_combo", "keys": "ctrl+s"},
            {"action": "wait", "duration": 0.01},
        ]
        result = await executor.execute_steps(steps, ctx)
        assert result["success"] is True
        assert result["completed_steps"] == 2
        assert result["total_steps"] == 2

    @pytest.mark.asyncio
    async def test_execute_steps_stops_on_failure(self, executor):
        ctx = SkillContext()
        steps = [
            {"action": "key_combo", "keys": "ctrl+s"},
            {"action": "fail_action"},
            {"action": "wait", "duration": 1.0},
        ]
        result = await executor.execute_steps(steps, ctx)
        assert result["success"] is False
        assert result["failed_step"] == 1
        assert result["completed_steps"] == 1

    @pytest.mark.asyncio
    async def test_execute_steps_empty_list(self, executor):
        ctx = SkillContext()
        result = await executor.execute_steps([], ctx)
        assert result["success"] is True
        assert result["completed_steps"] == 0


class TestResolveParams:
    @pytest.mark.asyncio
    async def test_resolve_params_template(self, executor):
        ctx = SkillContext(parameters={"shortcut": "ctrl+s"})
        step = {"action": "key_combo", "keys": "{{parameters.shortcut}}"}
        result = await executor.execute_step(step, ctx)
        assert result["success"] is True
        assert result["keys"] == "ctrl+s"

    @pytest.mark.asyncio
    async def test_context_current_step_increments(self, executor):
        ctx = SkillContext()
        steps = [
            {"action": "wait"},
            {"action": "wait"},
            {"action": "wait"},
        ]
        await executor.execute_steps(steps, ctx)
        assert ctx.current_step == 2  # 最后一步的索引
        assert ctx.total_steps == 3
