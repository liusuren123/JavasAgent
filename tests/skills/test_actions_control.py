# -*- coding: utf-8 -*-
"""控制流原语测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.skills.actions.control import (
    exec_wait, exec_wait_text, exec_condition, exec_loop,
    exec_run_skill, exec_set_var,
)
from src.skills.context import SkillContext


class TestWait:
    @pytest.mark.asyncio
    async def test_wait_default(self):
        ctx = SkillContext()
        step = {"action": "wait"}
        result = await exec_wait(step, ctx)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_wait_capped_at_30(self):
        ctx = SkillContext()
        step = {"action": "wait", "duration": 60}
        result = await exec_wait(step, ctx)
        assert result["duration"] == 30.0


class TestWaitText:
    @pytest.mark.asyncio
    async def test_wait_text_found(self):
        perception = MagicMock()
        # 第一次没找到，第二次找到
        perception.get_screen_text = AsyncMock(side_effect=["加载中", "保存成功"])
        ctx = SkillContext()
        step = {"action": "wait_text", "text": "保存成功", "timeout": 2.0, "interval": 0.01}
        result = await exec_wait_text(step, ctx, perception)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_wait_text_timeout(self):
        perception = MagicMock()
        perception.get_screen_text = AsyncMock(return_value="加载中...")
        ctx = SkillContext()
        step = {"action": "wait_text", "text": "完成", "timeout": 0.1, "interval": 0.05}
        result = await exec_wait_text(step, ctx, perception)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_wait_text_no_perception(self):
        ctx = SkillContext()
        step = {"action": "wait_text", "text": "test", "timeout": 0.05}
        result = await exec_wait_text(step, ctx, None)
        assert result["success"] is False


class TestCondition:
    @pytest.mark.asyncio
    async def test_condition_true_runs_then(self):
        ctx = SkillContext(parameters={"x": 1})
        executor = MagicMock()
        executor.execute_steps = AsyncMock(return_value={"success": True, "completed_steps": 1})
        step = {"action": "condition", "when": "parameters.x == 1", "then": [{"action": "wait"}]}
        result = await exec_condition(step, ctx, executor)
        assert result["branch"] == "then"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_condition_false_runs_else(self):
        ctx = SkillContext(parameters={"x": 0})
        executor = MagicMock()
        executor.execute_steps = AsyncMock(return_value={"success": True, "completed_steps": 1})
        step = {
            "action": "condition", "when": "parameters.x == 1",
            "then": [{"action": "wait"}], "else": [{"action": "wait"}],
        }
        result = await exec_condition(step, ctx, executor)
        assert result["branch"] == "else"

    @pytest.mark.asyncio
    async def test_condition_no_steps(self):
        ctx = SkillContext(parameters={"x": 1})
        step = {"action": "condition", "when": "parameters.x == 1"}
        result = await exec_condition(step, ctx, None)
        assert result["success"] is True
        assert result["executed"] == 0


class TestLoop:
    @pytest.mark.asyncio
    async def test_loop_iterations(self):
        ctx = SkillContext()
        executor = MagicMock()
        executor.execute_steps = AsyncMock(return_value={"success": True})
        step = {"action": "loop", "steps": [{"action": "wait"}], "max_iterations": 3}
        result = await exec_loop(step, ctx, executor)
        assert result["success"] is True
        assert result["iterations"] == 3

    @pytest.mark.asyncio
    async def test_loop_break_when(self):
        ctx = SkillContext(variables={"done": False})
        call_count = 0

        async def mock_execute(steps, ctx):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                ctx.set("done", True)
            return {"success": True}

        executor = MagicMock()
        executor.execute_steps = mock_execute
        step = {
            "action": "loop", "steps": [{"action": "wait"}],
            "max_iterations": 10, "break_when": "variables.done == true",
        }
        result = await exec_loop(step, ctx, executor)
        assert result["success"] is True
        assert result["iterations"] == 3  # 第3次检查 break_when 时 done=True

    @pytest.mark.asyncio
    async def test_loop_max_iterations_capped(self):
        ctx = SkillContext()
        executor = MagicMock()
        executor.execute_steps = AsyncMock(return_value={"success": True})
        step = {"action": "loop", "steps": [{"action": "wait"}], "max_iterations": 200}
        result = await exec_loop(step, ctx, executor)
        assert result["iterations"] <= 100

    @pytest.mark.asyncio
    async def test_loop_empty_steps(self):
        ctx = SkillContext()
        step = {"action": "loop", "steps": [], "max_iterations": 5}
        result = await exec_loop(step, ctx, None)
        assert result["success"] is True
        assert result["iterations"] == 0


class TestRunSkill:
    @pytest.mark.asyncio
    async def test_run_skill_calls_executor(self):
        ctx = SkillContext()
        skill_executor = MagicMock()
        skill_executor.execute_skill = AsyncMock(return_value={"success": True, "data": {}})
        step = {"action": "run_skill", "skill_name": "other_skill", "params": {"a": 1}}
        result = await exec_run_skill(step, ctx, skill_executor)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_run_skill_depth_limit(self):
        ctx = SkillContext(variables={"_skill_depth": 5})
        step = {"action": "run_skill", "skill_name": "deep"}
        result = await exec_run_skill(step, ctx, None)
        assert result["success"] is False
        assert "超限" in result["error"]


class TestSetVar:
    @pytest.mark.asyncio
    async def test_set_var(self):
        ctx = SkillContext()
        step = {"action": "set_var", "name": "count", "value": 42}
        result = await exec_set_var(step, ctx)
        assert result["success"] is True
        assert ctx.get("count") == 42

    @pytest.mark.asyncio
    async def test_set_var_template(self):
        ctx = SkillContext(parameters={"base": 10})
        step = {"action": "set_var", "name": "total", "value": "{{parameters.base}}"}
        result = await exec_set_var(step, ctx)
        assert result["success"] is True
        assert ctx.get("total") == "10"
