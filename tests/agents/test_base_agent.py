"""BaseAgent 测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base_agent import BaseAgent, PendingAction, PendingDecision
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


def _setup_agent_with_mocks(
    plan: TaskPlan | None = None,
    auto_decided: bool = True,
    exec_success: bool = True,
) -> tuple[BaseAgent, MagicMock, AsyncMock, MagicMock]:
    """创建一个 mock 好子组件的 Agent，返回 (agent, decider, executor, planner)。"""
    config = _make_config()
    agent = BaseAgent(config)

    mock_plan = plan or _make_plan()

    agent._planner = AsyncMock()
    agent._planner.plan.return_value = mock_plan

    mock_result = ExecutionResult(
        plan_id="plan_test",
        success=exec_success,
        completed_steps=1 if exec_success else 0,
        total_steps=1,
        errors=[] if exec_success else ["步骤0 执行失败"],
        output={},
    )
    agent._executor = AsyncMock()
    agent._executor.execute.return_value = mock_result

    agent._decider = MagicMock()
    agent._decider.evaluate.return_value = DecisionPoint(
        context="测试", question="测试",
        confidence=0.9, auto_decided=auto_decided,
    )

    return agent, agent._decider, agent._executor, agent._planner


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
        assert s["pending_decision"] is False

    def test_status_with_memory(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        agent._memory.add("user", "hello")
        assert agent.status["memory_size"] == 1

    def test_is_running_default(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        assert agent.is_running is False

    def test_pending_decision_in_status(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        agent._pending = PendingDecision(
            plan=_make_plan(), question="确认?", confidence=0.3,
        )
        assert agent.status["pending_decision"] is True


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
        agent, _, _, _ = _setup_agent_with_mocks(auto_decided=True, exec_success=True)

        response = await agent.process("帮我读取文件")
        assert "✅" in response
        assert "任务完成" in response
        assert agent._memory.size == 2  # user + assistant

    @pytest.mark.asyncio
    async def test_process_needs_human(self) -> None:
        """低 confidence → 询问人类，保存 pending。"""
        agent, _, _, _ = _setup_agent_with_mocks(auto_decided=False)

        response = await agent.process("帮我删除文件")
        assert "确认" in response
        assert agent._pending is not None
        # executor should NOT have been called
        agent._executor.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_execution_failure(self) -> None:
        """执行失败时的回复。"""
        agent, _, _, _ = _setup_agent_with_mocks(auto_decided=True, exec_success=False)

        response = await agent.process("执行测试任务")
        assert "❌" in response
        assert "执行失败" in response

    @pytest.mark.asyncio
    async def test_process_adds_to_memory(self) -> None:
        """每次 process 应该在记忆中存储用户输入和回复。"""
        agent, _, _, _ = _setup_agent_with_mocks()

        await agent.process("hello")
        msgs = agent._memory.get_messages()
        assert msgs[0].role == "user"
        assert msgs[0].content == "hello"
        assert msgs[1].role == "assistant"


class TestFeedbackLoop:
    """测试反馈循环：确认/取消/重新规划。"""

    @pytest.mark.asyncio
    async def test_confirm_executes_plan(self) -> None:
        """用户确认后应执行之前暂停的计划。"""
        agent, _, _, _ = _setup_agent_with_mocks(auto_decided=False, exec_success=True)

        # 第一次调用触发询问
        await agent.process("帮我删除文件")
        assert agent._pending is not None

        # 用户确认
        response = await agent.process("确认")
        assert "✅" in response
        assert agent._pending is None
        agent._executor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_aborts_plan(self) -> None:
        """用户取消应放弃计划。"""
        agent, _, _, _ = _setup_agent_with_mocks(auto_decided=False)

        await agent.process("帮我删除文件")
        assert agent._pending is not None

        response = await agent.process("取消")
        assert "取消" in response
        assert agent._pending is None
        agent._executor.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_replan_creates_new_plan(self) -> None:
        """用户要求重新规划。"""
        agent, _, _, planner = _setup_agent_with_mocks(auto_decided=False)

        new_plan = _make_plan("重新规划的任务", 2)
        planner.replan.return_value = new_plan

        await agent.process("帮我删除文件")

        response = await agent.process("重新规划一下")
        assert "重新规划" in response
        assert agent._pending is not None  # 新计划也需要确认
        planner.replan.assert_called_once()

    @pytest.mark.asyncio
    async def test_feedback_method_is_alias(self) -> None:
        """feedback() 方法应等同于 process()。"""
        agent, _, _, _ = _setup_agent_with_mocks(auto_decided=False)

        await agent.process("帮我删除文件")
        response = await agent.feedback("确认")
        assert "✅" in response

    @pytest.mark.asyncio
    async def test_non_feedback_input_clears_pending(self) -> None:
        """如果用户输入不是反馈关键词，应走正常流程。"""
        agent, _, _, _ = _setup_agent_with_mocks(auto_decided=False)

        await agent.process("帮我删除文件")
        assert agent._pending is not None

        # 用户说了一句完全不相关的话
        response = await agent.process("今天天气怎么样")
        # 应该走正常流程（而不是反馈处理），planner.plan 应被再次调用
        assert agent._planner.plan.call_count == 2

    @pytest.mark.asyncio
    async def test_cancel_keywords_variants(self) -> None:
        """多种取消关键词都应生效。"""
        for keyword in ["算了", "不要了", "放弃"]:
            agent, _, _, _ = _setup_agent_with_mocks(auto_decided=False)
            await agent.process("删除文件")
            response = await agent.process(keyword)
            assert "取消" in response

    @pytest.mark.asyncio
    async def test_confirm_keywords_variants(self) -> None:
        """多种确认关键词都应生效。"""
        for keyword in ["确定", "好的", "执行吧"]:
            agent, _, _, _ = _setup_agent_with_mocks(auto_decided=False, exec_success=True)
            await agent.process("删除文件")
            response = await agent.process(keyword)
            assert "✅" in response


class TestClassifyFeedback:
    """测试 _classify_feedback 方法。"""

    def test_confirm_keywords(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        for kw in ["确认", "确定", "yes", "ok", "Y"]:
            assert agent._classify_feedback(kw) == PendingAction.CONFIRM

    def test_cancel_keywords(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        for kw in ["取消", "算了", "cancel", "NO"]:
            assert agent._classify_feedback(kw) == PendingAction.CANCEL

    def test_replan_keywords(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        for kw in ["重试", "重新", "调整", "retry"]:
            assert agent._classify_feedback(kw) == PendingAction.REPLAN

    def test_normal_text(self) -> None:
        config = _make_config()
        agent = BaseAgent(config)
        assert agent._classify_feedback("帮我写个函数") == PendingAction.NONE
        assert agent._classify_feedback("今天天气怎么样") == PendingAction.NONE


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


class TestLifecycleManagement:
    """测试资源生命周期管理。"""

    @pytest.mark.asyncio
    async def test_close_releases_resources(self) -> None:
        """close() 应释放 LLM 连接池。"""
        config = _make_config()
        agent = BaseAgent(config)

        mock_llm = AsyncMock()
        agent._llm = mock_llm

        await agent.close()
        mock_llm.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_calls_close(self) -> None:
        """async with 应在退出时调用 close()。"""
        config = _make_config()
        agent = BaseAgent(config)

        mock_llm = AsyncMock()
        agent._llm = mock_llm

        async with agent:
            pass  # 使用 agent

        mock_llm.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_returns_agent(self) -> None:
        """async with 应返回 agent 实例。"""
        config = _make_config()
        agent = BaseAgent(config)

        async with agent as a:
            assert a is agent

    @pytest.mark.asyncio
    async def test_status_after_close(self) -> None:
        """close() 后 status 不应崩溃。"""
        config = _make_config()
        agent = BaseAgent(config)
        await agent.close()

        s = agent.status
        assert s["long_term_memory_count"] == 0

    @pytest.mark.asyncio
    async def test_close_idempotent(self) -> None:
        """多次调用 close() 不应报错。"""
        config = _make_config()
        agent = BaseAgent(config)
        await agent.close()
        await agent.close()  # 不应抛异常


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
