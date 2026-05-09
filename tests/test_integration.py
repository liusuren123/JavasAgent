"""端到端集成测试。

验证 感知→规划→决策→执行→反馈 的完整工作流，
确保各组件之间的交互正确。

与单元测试不同，这里尽可能使用真实组件组合，
仅在 LLM/外部服务处使用 mock。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.base_agent import BaseAgent, PendingDecision
from src.core.decider import Decider
from src.core.executor import Executor
from src.core.models import DecisionPoint, ExecutionResult, PlanStatus, Priority, Step, StepStatus, TaskPlan
from src.core.planner import Planner
from src.core.scheduler import Scheduler
from src.memory.short_term import ShortTermMemory
from src.utils.config import AgentConfig, AppConfig, LLMConfig, MemoryConfig


# ── Helpers ──────────────────────────────────────────────


def _config() -> AppConfig:
    """测试用的标准配置。"""
    return AppConfig(
        agent=AgentConfig(
            name="IntegrationTestAgent",
            ask_human_threshold=0.6,
            max_step_retries=2,
        ),
        llm=LLMConfig(default_provider="zhipuai"),
        memory=MemoryConfig(short_term_max_messages=20),
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
    config = _config()
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


class _FakeTool:
    """用于集成测试的模拟工具。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, action: str, params: dict) -> str:
        self.calls.append((action, params))
        return f"执行了 {action}"


# ── 完整工作流测试 ──────────────────────────────────────


class TestFullWorkflow:
    """端到端工作流：用户输入 → 规划 → 决策 → 执行 → 反馈。"""

    @pytest.mark.asyncio
    async def test_simple_auto_execute_workflow(self) -> None:
        """简单任务（高 confidence）应自动执行完成。"""
        agent, _, _, _ = _setup_agent_with_mocks(auto_decided=True, exec_success=True)

        result = await agent.process("帮我创建一个文件")
        assert "✅" in result
        assert "任务完成" in result
        agent._executor.execute.assert_called_once()
        assert agent._memory.size == 2  # user + assistant

    @pytest.mark.asyncio
    async def test_high_risk_needs_confirm_workflow(self) -> None:
        """包含「删除」关键词的任务应暂停，等待用户确认。"""
        agent, _, executor, _ = _setup_agent_with_mocks(auto_decided=False, exec_success=True)

        # 第一次调用：应暂停
        result = await agent.process("帮我删除一个文件")
        assert "⚠️" in result or "确认" in result
        assert agent._pending is not None
        executor.execute.assert_not_called()  # 未执行

        # 用户确认后执行
        result2 = await agent.process("确认")
        assert "✅" in result2
        assert agent._pending is None
        executor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_confirm_cancel_then_new_task(self) -> None:
        """取消后再提交新任务应正常工作。"""
        agent, _, executor, planner = _setup_agent_with_mocks(auto_decided=False)

        # 触发暂停
        await agent.process("帮我发送邮件")
        assert agent._pending is not None

        # 取消
        result = await agent.process("取消")
        assert "取消" in result
        assert agent._pending is None
        executor.execute.assert_not_called()

        # 新任务（重新 mock planner 返回自动决策）
        agent._decider.evaluate.return_value = DecisionPoint(
            context="新任务", question="新任务",
            confidence=0.9, auto_decided=True,
        )

        result = await agent.process("帮我创建一个文件")
        assert "✅" in result

    @pytest.mark.asyncio
    async def test_execution_failure_and_retry_feedback(self) -> None:
        """执行失败后应保存 failed plan。"""
        agent, _, _, _ = _setup_agent_with_mocks(auto_decided=True, exec_success=False)

        result = await agent.process("帮我执行任务")
        assert "❌" in result
        assert agent._last_failed_plan is not None

    @pytest.mark.asyncio
    async def test_multi_step_plan_execution(self) -> None:
        """多步骤计划应依次执行（使用真实 Executor）。"""
        config = _config()
        agent = BaseAgent(config)

        # 构建多步计划
        plan = TaskPlan(
            id="plan_multi",
            intent="多步骤测试",
            steps=[
                Step(id="s0", action="步骤一", tool="tool_a", params={"key": "val1"}),
                Step(id="s1", action="步骤二", tool="tool_b", params={"key": "val2"}),
                Step(id="s2", action="步骤三", tool="tool_a", params={"key": "val3"}),
            ],
            priority=Priority.NORMAL,
        )

        agent._planner = AsyncMock()
        agent._planner.plan.return_value = plan

        agent._decider = MagicMock()
        agent._decider.evaluate.return_value = DecisionPoint(
            context="多步骤测试", question="多步骤测试",
            confidence=0.9, auto_decided=True,
        )

        # 使用真实 Executor
        tool_a = _FakeTool()
        tool_b = _FakeTool()
        agent.register_tool("tool_a", tool_a)
        agent.register_tool("tool_b", tool_b)

        result = await agent.process("执行多步骤任务")
        assert "✅" in result
        assert len(tool_a.calls) == 2
        assert len(tool_b.calls) == 1

    @pytest.mark.asyncio
    async def test_dependency_chain_execution(self) -> None:
        """有依赖关系的步骤应按正确顺序执行（使用真实 Executor）。"""
        config = _config()
        agent = BaseAgent(config)

        plan = TaskPlan(
            id="plan_deps",
            intent="依赖链测试",
            steps=[
                Step(id="s0", action="准备数据", tool="tool_a", params={}),
                Step(id="s1", action="处理数据", tool="tool_a", params={}, depends_on=["s0"]),
                Step(id="s2", action="输出结果", tool="tool_a", params={}, depends_on=["s1"]),
            ],
            priority=Priority.HIGH,
        )

        agent._planner = AsyncMock()
        agent._planner.plan.return_value = plan

        agent._decider = MagicMock()
        agent._decider.evaluate.return_value = DecisionPoint(
            context="依赖链", question="依赖链",
            confidence=0.95, auto_decided=True,
        )

        tool = _FakeTool()
        agent.register_tool("tool_a", tool)

        result = await agent.process("执行依赖链")
        assert "✅" in result
        assert len(tool.calls) == 3
        # 验证执行顺序
        assert tool.calls[0][0] == "准备数据"
        assert tool.calls[1][0] == "处理数据"
        assert tool.calls[2][0] == "输出结果"


class TestSchedulerIntegration:
    """调度器与执行引擎的集成。"""

    @pytest.mark.asyncio
    async def test_submit_and_execute_via_scheduler(self) -> None:
        """通过 scheduler 提交的计划应被正确执行。"""
        scheduler = Scheduler()
        executor = Executor()

        tool = _FakeTool()
        executor.register_tool("my_tool", tool)

        plan = TaskPlan(
            id="plan_sched",
            intent="调度器测试",
            steps=[Step(id="s0", action="执行", tool="my_tool", params={})],
        )

        # 提交到调度器
        task_id = await scheduler.submit(plan)
        assert task_id == "plan_sched"

        # 获取下一个任务
        fetched = await scheduler.get_next()
        assert fetched is not None
        scheduler.mark_running(fetched)
        assert scheduler.has_running_task

        # 执行
        result = await executor.execute(fetched)
        assert result.success
        assert result.completed_steps == 1

        # 标记完成
        scheduler.mark_done(fetched, result.success)
        assert not scheduler.has_running_task
        assert fetched.status == PlanStatus.DONE

    @pytest.mark.asyncio
    async def test_priority_ordering(self) -> None:
        """高优先级任务应优先出队。"""
        scheduler = Scheduler()

        low_plan = TaskPlan(
            id="low", intent="低优先级",
            steps=[Step(id="s0", action="低", tool="t", params={})],
            priority=Priority.LOW,
        )
        high_plan = TaskPlan(
            id="high", intent="高优先级",
            steps=[Step(id="s0", action="高", tool="t", params={})],
            priority=Priority.HIGH,
        )
        normal_plan = TaskPlan(
            id="normal", intent="普通优先级",
            steps=[Step(id="s0", action="普通", tool="t", params={})],
            priority=Priority.NORMAL,
        )

        # 按低→高→普通顺序提交
        await scheduler.submit(low_plan)
        await scheduler.submit(high_plan)
        await scheduler.submit(normal_plan)

        # 取出并标记完成（释放并发槽位）
        first = await scheduler.get_next()
        assert first is not None
        assert first.id == "high"
        scheduler.mark_done(first, True)

        second = await scheduler.get_next()
        assert second is not None
        assert second.id == "normal"
        scheduler.mark_done(second, True)

        third = await scheduler.get_next()
        assert third is not None
        assert third.id == "low"


class TestDeciderIntegration:
    """决策器与 confidence 估算的集成。"""

    def test_shell_command_reduces_confidence(self) -> None:
        """包含 shell 工具的计划 confidence 应较低。"""
        plan = TaskPlan(
            id="p1", intent="执行命令",
            steps=[Step(id="s0", action="运行", tool="shell", params={})],
        )

        confidence = BaseAgent._estimate_confidence(plan, "运行命令")
        assert confidence < 0.85  # shell 降低 confidence

    def test_delete_keyword_always_asks(self) -> None:
        """「删除」关键词应强制询问人类。"""
        config = _config()
        decider = Decider(config.agent)

        decision = decider.evaluate(
            context="删除重要文件",
            question="删除文件",
            confidence=0.99,  # 即使 confidence 很高
        )
        assert decision.auto_decided is False


class TestMemoryIntegration:
    """记忆系统与 Agent 的集成。"""

    @pytest.mark.asyncio
    async def test_conversation_history_accumulates(self) -> None:
        """多轮对话应在短期记忆中累积。"""
        agent, _, _, _ = _setup_agent_with_mocks()

        await agent.process("第一个任务")
        await agent.process("第二个任务")
        await agent.process("第三个任务")

        # 应有 6 条消息（3 user + 3 assistant）
        assert agent._memory.size == 6

    @pytest.mark.asyncio
    async def test_memory_respects_max_limit(self) -> None:
        """短期记忆应遵守最大消息限制。"""
        config = AppConfig(
            agent=AgentConfig(ask_human_threshold=0.6),
            llm=LLMConfig(default_provider="zhipuai"),
            memory=MemoryConfig(short_term_max_messages=4),
        )
        agent = BaseAgent(config)

        # 使用 mock
        agent._planner = AsyncMock()
        agent._planner.plan.return_value = _make_plan()
        agent._decider = MagicMock()
        agent._decider.evaluate.return_value = DecisionPoint(
            context="t", question="t", confidence=0.9, auto_decided=True,
        )
        agent._executor = AsyncMock()
        agent._executor.execute.return_value = ExecutionResult(
            plan_id="p", success=True, completed_steps=1, total_steps=1, errors=[], output={},
        )

        for i in range(5):
            await agent.process(f"任务{i}")

        assert agent._memory.size == 4  # 应被截断到 max

    @pytest.mark.asyncio
    async def test_context_for_llm_reflects_conversation(self) -> None:
        """_build_context 应反映最近的对话。"""
        agent, _, _, _ = _setup_agent_with_mocks()

        await agent.process("用户说了A")
        ctx = agent._build_context()
        assert "用户说了A" in ctx


class TestPlannerIntegration:
    """规划器 JSON 解析与真实数据结构的集成。"""

    @pytest.mark.asyncio
    async def test_planner_produces_valid_plan(self) -> None:
        """Planner 应产出结构有效的 TaskPlan。"""
        mock_llm = AsyncMock()
        mock_llm.chat_with_system.return_value = json.dumps({
            "intent_summary": "创建 hello.py",
            "steps": [
                {"action": "创建文件", "tool": "system_control", "params": {"path": "hello.py", "content": "print('hello')"}},
                {"action": "验证文件", "tool": "shell", "params": {"command": "python hello.py"}, "depends_on": [0]},
            ],
            "priority": 5,
        })

        planner = Planner(mock_llm)
        plan = await planner.plan("创建一个 hello.py 文件")

        assert plan.intent == "创建 hello.py"
        assert len(plan.steps) == 2
        assert plan.steps[0].tool == "system_control"
        assert plan.steps[1].depends_on == ["step_0"]
        assert plan.priority == Priority.NORMAL

    @pytest.mark.asyncio
    async def test_planner_replan_preserves_intent(self) -> None:
        """重新规划应保留原始意图。"""
        mock_llm = AsyncMock()
        mock_llm.chat_with_system.return_value = json.dumps({
            "intent_summary": "修改后的计划",
            "steps": [{"action": "新步骤", "tool": "shell", "params": {}}],
            "priority": 10,
        })

        planner = Planner(mock_llm)

        original = TaskPlan(
            id="orig", intent="原始意图",
            steps=[Step(id="s0", action="旧步骤", tool="shell", params={})],
        )

        new_plan = await planner.replan(original, "旧步骤失败了")
        assert new_plan.parent_id == "orig"
        assert len(new_plan.steps) == 1

    @pytest.mark.asyncio
    async def test_planner_handles_malformed_json(self) -> None:
        """Planner 在 JSON 格式错误时应降级为单步计划。"""
        mock_llm = AsyncMock()
        mock_llm.chat_with_system.return_value = "这不是 JSON 格式"
        planner = Planner(mock_llm)

        plan = await planner.plan("随便做点什么")
        assert len(plan.steps) >= 1
        assert plan.steps[0].tool == "shell"


class TestExecutorIntegration:
    """执行引擎与真实工具的集成。"""

    @pytest.mark.asyncio
    async def test_executor_calls_tool_execute(self) -> None:
        """Executor 应调用工具的 execute 方法。"""
        executor = Executor()
        tool = _FakeTool()
        executor.register_tool("my_tool", tool)

        plan = TaskPlan(
            id="p1", intent="测试",
            steps=[Step(id="s0", action="动作", tool="my_tool", params={"a": 1})],
        )

        result = await executor.execute(plan)
        assert result.success
        assert result.completed_steps == 1
        assert len(tool.calls) == 1
        assert tool.calls[0] == ("动作", {"a": 1})

    @pytest.mark.asyncio
    async def test_executor_skip_on_failed_dependency(self) -> None:
        """前置步骤失败时，后续依赖步骤应被跳过。"""
        executor = Executor()

        # 第一个工具总是失败
        fail_tool = _FakeTool()
        fail_tool.execute = AsyncMock(return_value=None)
        executor.register_tool("fail_tool", fail_tool)

        # 第二个工具
        ok_tool = _FakeTool()
        executor.register_tool("ok_tool", ok_tool)

        plan = TaskPlan(
            id="p1", intent="依赖测试",
            steps=[
                Step(id="s0", action="失败步骤", tool="fail_tool", params={}, max_retries=0),
                Step(id="s1", action="依赖步骤", tool="ok_tool", params={}, depends_on=["s0"]),
            ],
        )

        result = await executor.execute(plan)
        assert not result.success
        assert plan.steps[0].status == StepStatus.FAILED
        assert plan.steps[1].status == StepStatus.SKIPPED
        assert len(ok_tool.calls) == 0


class TestEndToEndRetry:
    """端到端重试场景。"""

    @pytest.mark.asyncio
    async def test_step_retry_and_recover(self) -> None:
        """步骤失败重试后成功。"""
        executor = Executor()
        call_count = 0

        class FlakyTool:
            async def execute(self, action: str, params: dict) -> str | None:
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    return None
                return "成功了"

        executor.register_tool("flaky", FlakyTool())

        plan = TaskPlan(
            id="p1", intent="重试测试",
            steps=[Step(id="s0", action="不稳定操作", tool="flaky", params={}, max_retries=3)],
        )

        result = await executor.execute(plan)
        assert result.success
        assert call_count == 3  # 第一次 + 两次重试 = 3 次调用

    @pytest.mark.asyncio
    async def test_retry_exhausted(self) -> None:
        """重试次数耗尽后应标记失败。"""
        executor = Executor()

        always_fail = _FakeTool()
        always_fail.execute = AsyncMock(return_value=None)
        executor.register_tool("fail", always_fail)

        plan = TaskPlan(
            id="p1", intent="重试耗尽",
            steps=[Step(id="s0", action="总失败", tool="fail", params={}, max_retries=2)],
        )

        result = await executor.execute(plan)
        assert not result.success
        assert plan.steps[0].status == StepStatus.FAILED
        assert plan.steps[0].retry_count == 2
