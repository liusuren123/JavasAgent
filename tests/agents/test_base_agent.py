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


class TestEstimateConfidence:
    """测试 _estimate_confidence 静态方法。"""

    def test_single_safe_step(self) -> None:
        plan = TaskPlan(
            id="p1", intent="test",
            steps=[Step(id="s0", action="读取", tool="system_control")],
        )
        conf = BaseAgent._estimate_confidence(plan, "读取文件")
        assert conf == pytest.approx(0.80)

    def test_shell_step_reduces_confidence(self) -> None:
        plan = TaskPlan(
            id="p1", intent="test",
            steps=[Step(id="s0", action="运行命令", tool="shell")],
        )
        conf = BaseAgent._estimate_confidence(plan, "运行命令")
        assert conf == pytest.approx(0.65)

    def test_many_steps_reduces_confidence(self) -> None:
        steps = [Step(id=f"s{i}", action=f"步骤{i}", tool="code_dev") for i in range(8)]
        plan = TaskPlan(id="p1", intent="test", steps=steps)
        conf = BaseAgent._estimate_confidence(plan, "复杂任务")
        # base 0.85 - min(0.30, 0.40) = 0.55
        assert conf == pytest.approx(0.55)

    def test_confidence_clamped_low(self) -> None:
        """超多步骤 + shell → confidence 不低于 0.1。"""
        steps = [Step(id=f"s{i}", action=f"步骤{i}", tool="shell") for i in range(20)]
        plan = TaskPlan(id="p1", intent="test", steps=steps)
        conf = BaseAgent._estimate_confidence(plan, "极端任务")
        assert conf >= 0.1

    def test_no_steps_high_confidence(self) -> None:
        plan = TaskPlan(id="p1", intent="test", steps=[])
        conf = BaseAgent._estimate_confidence(plan, "空计划")
        assert conf == pytest.approx(0.85)

    def test_confidence_capped_at_one(self) -> None:
        plan = TaskPlan(id="p1", intent="test", steps=[])
        conf = BaseAgent._estimate_confidence(plan, "x")
        assert conf <= 1.0


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


class TestScreenIntegration:
    """测试 BaseAgent 与 ScreenAnalyzer 的集成。"""

    def test_screen_analyzer_initialized(self) -> None:
        """BaseAgent 应初始化 ScreenAnalyzer。"""
        config = _make_config()
        agent = BaseAgent(config)
        assert hasattr(agent, "_screen_analyzer")
        assert agent._screen_analyzer is not None

    def test_is_screen_related(self) -> None:
        """应正确判断是否涉及屏幕操作。"""
        config = _make_config()
        agent = BaseAgent(config)

        assert agent._is_screen_related("帮我点击保存按钮") is True
        assert agent._is_screen_related("截屏") is True
        assert agent._is_screen_related("看看屏幕上有什么") is True
        assert agent._is_screen_related("打开浏览器") is True
        assert agent._is_screen_related("关闭窗口") is True
        assert agent._is_screen_related("今天天气怎么样") is False
        assert agent._is_screen_related("帮我写个函数") is False

    @pytest.mark.asyncio
    async def test_analyze_screen_public_method(self) -> None:
        """公开的 analyze_screen 方法应调用 ScreenAnalyzer.describe。"""
        config = _make_config()
        agent = BaseAgent(config)

        agent._screen_analyzer = AsyncMock()
        agent._screen_analyzer.describe.return_value = "屏幕上显示了桌面"

        result = await agent.analyze_screen(b"fake_png")
        assert result == "屏幕上显示了桌面"
        agent._screen_analyzer.describe.assert_called_once_with(b"fake_png")


class TestPlatformIntegration:
    """测试 BaseAgent 与 PlatformAdapter 的集成。"""

    @pytest.mark.asyncio
    async def test_analyze_screen_if_available_no_platform(self) -> None:
        """无平台适配器时返回空字符串。"""
        config = _make_config()
        agent = BaseAgent(config)
        result = await agent._analyze_screen_if_available()
        assert result == ""

    @pytest.mark.asyncio
    async def test_analyze_screen_if_available_with_platform(self) -> None:
        """有平台适配器时应截屏并分析。"""
        config = _make_config()

        mock_platform = AsyncMock()
        mock_platform.screenshot.return_value = b"fake_png_data"

        agent = BaseAgent(config, platform=mock_platform)
        agent._screen_analyzer = AsyncMock()
        agent._screen_analyzer.describe.return_value = "屏幕显示桌面"

        result = await agent._analyze_screen_if_available()
        assert result == "屏幕显示桌面"
        mock_platform.screenshot.assert_called_once()
        agent._screen_analyzer.describe.assert_called_once_with(b"fake_png_data")

    @pytest.mark.asyncio
    async def test_analyze_screen_if_available_platform_failure(self) -> None:
        """平台截屏失败时应返回空字符串。"""
        config = _make_config()

        mock_platform = AsyncMock()
        mock_platform.screenshot.side_effect = RuntimeError("截屏失败")

        agent = BaseAgent(config, platform=mock_platform)
        result = await agent._analyze_screen_if_available()
        assert result == ""

    @pytest.mark.asyncio
    async def test_process_with_screen_context(self) -> None:
        """屏幕相关任务应注入屏幕感知上下文。"""
        config = _make_config()

        mock_platform = AsyncMock()
        mock_platform.screenshot.return_value = b"fake_png"

        agent = BaseAgent(config, platform=mock_platform)
        agent._screen_analyzer = AsyncMock()
        agent._screen_analyzer.describe.return_value = "桌面图标"

        mock_plan = _make_plan("点击按钮", 1)
        agent._planner = AsyncMock()
        agent._planner.plan.return_value = mock_plan

        agent._decider = MagicMock()
        agent._decider.evaluate.return_value = DecisionPoint(
            context="点击按钮", question="点击按钮",
            confidence=0.9, auto_decided=True,
        )

        mock_result = ExecutionResult(
            plan_id="plan_test", success=True,
            completed_steps=1, total_steps=1, errors=[], output={},
        )
        agent._executor = AsyncMock()
        agent._executor.execute.return_value = mock_result

        response = await agent.process("帮我点击按钮")
        assert "✅" in response
        # 验证 planner.plan 收到的 context 包含屏幕感知
        call_args = agent._planner.plan.call_args
        context_arg = call_args[0][1]  # 第二个位置参数是 context
        assert "屏幕感知" in context_arg
        assert "桌面图标" in context_arg
