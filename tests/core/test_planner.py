"""任务规划器测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.models import Priority, Step, TaskPlan
from src.core.planner import Planner


class TestParsePlan:
    """测试 _parse_plan 的各种 LLM 返回格式。"""

    def _make_planner(self) -> Planner:
        mock_llm = AsyncMock()
        return Planner(mock_llm)

    def test_normal_json(self) -> None:
        planner = self._make_planner()
        response = json.dumps({
            "intent_summary": "打开浏览器",
            "steps": [
                {"action": "启动浏览器", "tool": "system_control", "params": {"url": "https://example.com"}, "depends_on": []},
            ],
            "priority": 5,
        })
        plan = planner._parse_plan(response, "打开浏览器访问example")
        assert plan.intent == "打开浏览器"
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "启动浏览器"
        assert plan.steps[0].tool == "system_control"
        assert plan.priority == Priority.NORMAL

    def test_json_code_block(self) -> None:
        planner = self._make_planner()
        response = '```json\n{"intent_summary": "写代码", "steps": [{"action": "生成代码", "tool": "code_dev", "params": {}, "depends_on": []}], "priority": 10}\n```'
        plan = planner._parse_plan(response, "帮我写个函数")
        assert plan.intent == "写代码"
        assert len(plan.steps) == 1
        assert plan.priority == Priority.HIGH

    def test_plain_code_block_with_json(self) -> None:
        planner = self._make_planner()
        response = '```\n{"intent_summary": "测试", "steps": [{"action": "运行测试", "tool": "shell", "params": {}, "depends_on": []}], "priority": 5}\n```'
        plan = planner._parse_plan(response, "运行测试")
        assert plan.intent == "测试"
        assert len(plan.steps) == 1

    def test_non_json_fallback(self) -> None:
        planner = self._make_planner()
        response = "抱歉，我无法解析这个请求。"
        plan = planner._parse_plan(response, "模糊的指令")
        assert plan.intent == "模糊的指令"
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "shell"
        assert plan.steps[0].action == "模糊的指令"

    def test_empty_json_object(self) -> None:
        planner = self._make_planner()
        response = "{}"
        plan = planner._parse_plan(response, "默认意图")
        assert plan.intent == "默认意图"
        assert len(plan.steps) == 0
        assert plan.priority == Priority.NORMAL

    def test_invalid_priority_fallback(self) -> None:
        planner = self._make_planner()
        response = json.dumps({
            "steps": [],
            "priority": 99,
        })
        plan = planner._parse_plan(response, "任意")
        assert plan.priority == Priority.NORMAL

    def test_depends_on_mapping(self) -> None:
        planner = self._make_planner()
        response = json.dumps({
            "steps": [
                {"action": "步骤A", "tool": "shell", "params": {}, "depends_on": []},
                {"action": "步骤B", "tool": "shell", "params": {}, "depends_on": [0]},
            ],
            "priority": 5,
        })
        plan = planner._parse_plan(response, "多步骤")
        assert plan.steps[1].depends_on == ["step_0"]

    def test_missing_fields_use_defaults(self) -> None:
        planner = self._make_planner()
        response = json.dumps({
            "steps": [{"action": "test"}],
        })
        plan = planner._parse_plan(response, "原始意图")
        assert plan.steps[0].tool == "shell"
        assert plan.steps[0].params == {}
        assert plan.steps[0].depends_on == []

    def test_plan_id_is_unique(self) -> None:
        planner = self._make_planner()
        response = '{"steps": []}'
        p1 = planner._parse_plan(response, "a")
        p2 = planner._parse_plan(response, "b")
        assert p1.id != p2.id
        assert p1.id.startswith("plan_")
        assert p2.id.startswith("plan_")


class TestPlan:
    """测试 Planner.plan() 异步方法。"""

    @pytest.mark.asyncio
    async def test_plan_returns_task_plan(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat_with_system.return_value = json.dumps({
            "intent_summary": "创建文件",
            "steps": [
                {"action": "创建文件", "tool": "system_control", "params": {"path": "/tmp/test.txt"}, "depends_on": []},
            ],
            "priority": 5,
        })
        planner = Planner(mock_llm)

        plan = await planner.plan("创建一个测试文件")
        assert isinstance(plan, TaskPlan)
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "创建文件"
        mock_llm.chat_with_system.assert_called_once()

    @pytest.mark.asyncio
    async def test_plan_with_context(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat_with_system.return_value = '{"steps": [], "priority": 5}'
        planner = Planner(mock_llm)

        await planner.plan("做点什么", context="之前做了X")
        call_args = mock_llm.chat_with_system.call_args
        assert "之前做了X" in call_args.kwargs.get("user_message", call_args[1].get("user_message", ""))

    @pytest.mark.asyncio
    async def test_plan_handles_llm_gibberish(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat_with_system.return_value = "我 不 是 JSON"
        planner = Planner(mock_llm)

        plan = await planner.plan("模糊指令")
        assert plan.steps[0].action == "模糊指令"
        assert plan.steps[0].tool == "shell"


class TestReplan:
    """测试 Planner.replan() 异步方法。"""

    @pytest.mark.asyncio
    async def test_replan_returns_new_plan(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat_with_system.return_value = json.dumps({
            "intent_summary": "重新规划",
            "steps": [
                {"action": "新步骤", "tool": "shell", "params": {}, "depends_on": []},
            ],
            "priority": 5,
        })
        planner = Planner(mock_llm)

        original = TaskPlan(
            id="plan_original",
            intent="原始意图",
            steps=[Step(id="step_0", action="步骤A", tool="shell")],
        )

        new_plan = await planner.replan(original, "执行失败需要调整")
        assert isinstance(new_plan, TaskPlan)
        assert new_plan.parent_id == "plan_original"
        assert len(new_plan.steps) == 1
        assert new_plan.steps[0].action == "新步骤"

    @pytest.mark.asyncio
    async def test_replan_preserves_intent(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat_with_system.return_value = '{"steps": [], "priority": 5}'
        planner = Planner(mock_llm)

        original = TaskPlan(id="plan_abc", intent="创建项目", steps=[])
        new_plan = await planner.replan(original, "需要调整")
        # intent comes from _parse_plan which uses original_intent when no intent_summary
        assert new_plan.intent == "创建项目"
