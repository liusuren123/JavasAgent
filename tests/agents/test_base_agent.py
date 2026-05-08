"""BaseAgent 测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base_agent import BaseAgent
from src.core.executor import ExecutionResult
from src.core.models import (
    DecisionPoint,
    PlanStatus,
    Priority,
    Step,
    TaskPlan,
)
from src.utils.config import AppConfig, AgentConfig, LLMConfig, MemoryConfig


def _make_config() -> AppConfig:
    return AppConfig(
        agent=AgentConfig(name="TestAgent", ask_human_threshold=0.6),
        llm=LLMConfig(default_provider="zhipuai"),
        memory=MemoryConfig(short_term_max_messages=10),
    )


def _make_plan(intent: str = "测试计划", n_steps: int = 1) -> TaskPlan:
    steps = [
        Step(id=f"step_{i}", action=f"步骤{i}", tool="mock_tool", params={})
        for i in range(n_steps)
    ]
    return TaskPlan(
        id="plan_test",
        intent=intent,
        steps=steps,
        priority=Priority.NORMAL,
    )


class TestRegisterTool:
    """测试工具注册。"""

    def test_register_tool(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        mock_tool = MagicMock()
        agent.register_tool("my_tool", mock_tool)
        assert "my_tool" in agent._executor._tool_registry


class TestBuildContext:
    """测试上下文构建。"""

    def test_empty_context(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        ctx = agent._build_context()
        assert ctx == ""

    def test_context_includes_recent_messages(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        agent._memory.add("user", "你好")
        agent._memory.add("assistant", "你好呀")
        ctx = agent._build_context()
        assert "你好" in ctx
        assert "用户" in ctx
        assert "助手" in ctx

    def test_context_shows_running_task(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        plan = _make_plan()
        agent._scheduler.mark_running(plan)
        ctx = agent._build_context()
        assert "运行中" in ctx


class TestStatus:
    """测试 status 属性。"""

    def test_initial_status(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        s = agent.status
        assert s["running"] is False
        assert s["memory_size"] == 0
        assert s["scheduler"]["running"] == 0

    def test_status_with_memory(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        agent._memory.add("user", "hello")
        assert agent.status["memory_size"] == 1

    def test_is_running_default(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        assert agent.is_running is False


class TestProcess:
    """测试 process() 核心流程。"""

    @pytest.mark.asyncio
    async def test_process_auto_execute(self) -> None:
        """confidence 高且无风险关键词 → 自动执行。"""
        config = _make_config()
        agent = BaseAgent(config)

        mock_plan = _make_plan("读取文件", 1)

        agent._planner = AsyncMock()
        agent._planner.plan.return_value = mock_plan

        mock_result = ExecutionResult(
            plan_id="plan_test", success=True,
            completed_steps=1, total_steps=1, errors=[], output={},
        )
        agent._executor = AsyncMock()
        agent._executor.execute.return_value = mock_result

        # Mock decider to auto-decide
        agent._decider = MagicMock()
        agent._decider.evaluate.return_value = DecisionPoint(
            context="读取文件", question="读取文件",
            confidence=0.9, auto_decided=True,
        )

        response = await agent.process("帮我读取文件")
        assert "✅" in response
        assert "任务完成" in response
        assert agent._memory.size == 2  # user + assistant

    @pytest.mark.asyncio
    async def test_process_needs_human(self) -> None:
        """低 confidence → 询问人类。"""
        config = _make_config()
        agent = BaseAgent(config)

        mock_plan = _make_plan("删除文件", 1)
        agent._planner = AsyncMock()
        agent._planner.plan.return_value = mock_plan

        agent._decider = MagicMock()
        agent._decider.evaluate.return_value = DecisionPoint(
            context="删除文件", question="删除文件",
            confidence=0.3, auto_decided=False,
        )

        response = await agent.process("帮我删除文件")
        assert "确认" in response
        # executor should NOT have been called
        assert agent._executor.is_busy is False

    @pytest.mark.asyncio
    async def test_process_execution_failure(self) -> None:
        """执行失败时的回复。"""
        config = _make_config()
        agent = BaseAgent(config)

        mock_plan = _make_plan("测试任务", 1)
        agent._planner = AsyncMock()
        agent._planner.plan.return_value = mock_plan

        mock_result = ExecutionResult(
            plan_id="plan_test", success=False,
            completed_steps=0, total_steps=1,
            errors=["步骤0 执行失败"], output={},
        )
        agent._executor = AsyncMock()
        agent._executor.execute.return_value = mock_result

        agent._decider = MagicMock()
        agent._decider.evaluate.return_value = DecisionPoint(
            context="安全", question="安全",
            confidence=0.9, auto_decided=True,
        )

        response = await agent.process("执行测试任务")
        assert "❌" in response
        assert "执行失败" in response

    @pytest.mark.asyncio
    async def test_process_adds_to_memory(self) -> None:
        """每次 process 应该在记忆中存储用户输入和回复。"""
        config = _make_config()
        agent = BaseAgent(config)

        mock_plan = _make_plan()
        agent._planner = AsyncMock()
        agent._planner.plan.return_value = mock_plan

        agent._decider = MagicMock()
        agent._decider.evaluate.return_value = DecisionPoint(
            context="x", question="x", confidence=0.9, auto_decided=True,
        )

        mock_result = ExecutionResult(
            plan_id="plan_test", success=True,
            completed_steps=1, total_steps=1, errors=[], output={},
        )
        agent._executor = AsyncMock()
        agent._executor.execute.return_value = mock_result

        await agent.process("hello")
        msgs = agent._memory.get_messages()
        assert msgs[0].role == "user"
        assert msgs[0].content == "hello"
        assert msgs[1].role == "assistant"
