"""LearningIntegration 测试。

测试 LearningIntegration 的三个核心方法及 BaseAgent 集成点。
使用 mock 避免真实文件系统依赖。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.learning_integration import LearningIntegration
from src.core.models import ExecutionResult, PlanStatus, Priority, Step, TaskPlan
from src.memory.skill_models import LearnedPattern, SkillDefinition, SkillSuggestion
from src.utils.config import AppConfig, AgentConfig, LLMConfig, MemoryConfig


# ------------------------------------------------------------------
# 辅助工厂
# ------------------------------------------------------------------


def _make_plan(intent: str = "测试计划", n_steps: int = 1) -> TaskPlan:
    """创建测试用 TaskPlan。"""
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


def _make_result(success: bool = True) -> ExecutionResult:
    """创建测试用 ExecutionResult。"""
    return ExecutionResult(
        plan_id="plan_test",
        success=success,
        completed_steps=1 if success else 0,
        total_steps=1,
        errors=[] if success else ["执行失败"],
        output={},
    )


def _make_config() -> AppConfig:
    """创建测试用 AppConfig。"""
    return AppConfig(
        agent=AgentConfig(name="TestAgent"),
        llm=LLMConfig(default_provider="zhipuai"),
        memory=MemoryConfig(short_term_max_messages=10),
    )


# ------------------------------------------------------------------
# LearningIntegration 核心方法测试
# ------------------------------------------------------------------


class TestOnExecutionComplete:
    """测试 on_execution_complete 方法。"""

    @pytest.mark.asyncio
    async def test_records_successful_execution(self) -> None:
        """成功执行后应记录模式。"""
        integration = LearningIntegration()
        plan = _make_plan()
        result = _make_result(success=True)

        await integration.on_execution_complete(plan, result)

        assert integration.pattern_count == 1

    @pytest.mark.asyncio
    async def test_records_failed_execution(self) -> None:
        """失败执行后也应记录模式。"""
        integration = LearningIntegration()
        plan = _make_plan()
        result = _make_result(success=False)

        await integration.on_execution_complete(plan, result)

        assert integration.pattern_count == 1

    @pytest.mark.asyncio
    async def test_multiple_executions_accumulate(self) -> None:
        """多次执行应累计模式计数。"""
        integration = LearningIntegration()
        plan = _make_plan()

        for _ in range(5):
            result = _make_result(success=True)
            await integration.on_execution_complete(plan, result)

        # 同一模式应合并，不是新增
        assert integration.pattern_count == 1

    @pytest.mark.asyncio
    async def test_different_plans_create_different_patterns(self) -> None:
        """不同步骤的计划应创建不同模式。"""
        integration = LearningIntegration()
        plan_a = _make_plan("任务A")
        plan_b = TaskPlan(
            id="plan_b",
            intent="任务B",
            steps=[Step(id="s1", action="写入", tool="shell", params={})],
            priority=Priority.NORMAL,
        )

        await integration.on_execution_complete(plan_a, _make_result())
        await integration.on_execution_complete(plan_b, _make_result())

        assert integration.pattern_count == 2

    @pytest.mark.asyncio
    async def test_skips_plan_with_no_steps(self) -> None:
        """无步骤的计划不应记录。"""
        integration = LearningIntegration()
        plan = TaskPlan(
            id="empty_plan",
            intent="空计划",
            steps=[],
            priority=Priority.NORMAL,
        )
        result = _make_result()

        await integration.on_execution_complete(plan, result)

        assert integration.pattern_count == 0

    @pytest.mark.asyncio
    async def test_triggers_suggestion_after_threshold(self) -> None:
        """成功次数超过阈值后应生成建议。"""
        integration = LearningIntegration(min_success_count=2)
        plan = _make_plan()

        # 第一次执行
        await integration.on_execution_complete(plan, _make_result(success=True))
        assert integration.suggestion_count == 0

        # 第二次执行达到阈值
        await integration.on_execution_complete(plan, _make_result(success=True))
        assert integration.suggestion_count == 1

    @pytest.mark.asyncio
    async def test_calls_learner_save(self) -> None:
        """应调用 learner.save() 持久化数据。"""
        integration = LearningIntegration()
        integration._learner = MagicMock(spec=integration._learner)
        integration._learner.record_execution = AsyncMock()
        integration._learner.suggest_skills = AsyncMock(return_value=[])
        integration._learner.save = AsyncMock()

        plan = _make_plan()
        result = _make_result()

        await integration.on_execution_complete(plan, result)

        integration._learner.record_execution.assert_called_once_with(plan, result)
        integration._learner.save.assert_called_once()


class TestOnPlanningStart:
    """测试 on_planning_start 方法。"""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_suggestions(self) -> None:
        """无建议时应返回空列表。"""
        integration = LearningIntegration()
        suggestions = await integration.on_planning_start("测试上下文")
        assert suggestions == []

    @pytest.mark.asyncio
    async def test_returns_pending_suggestions(self) -> None:
        """应返回 pending 状态的建议。"""
        integration = LearningIntegration(min_success_count=2)
        plan = _make_plan()

        # 触发建议生成
        await integration.on_execution_complete(plan, _make_result(True))
        await integration.on_execution_complete(plan, _make_result(True))

        suggestions = await integration.on_planning_start()
        assert len(suggestions) == 1
        assert suggestions[0].status == "pending"

    @pytest.mark.asyncio
    async def test_does_not_return_approved_suggestions(self) -> None:
        """已确认的建议不应出现在列表中。"""
        integration = LearningIntegration(min_success_count=2)
        plan = _make_plan()

        await integration.on_execution_complete(plan, _make_result(True))
        await integration.on_execution_complete(plan, _make_result(True))

        suggestions = await integration.on_planning_start()
        suggestion_id = suggestions[0].id

        # 确认注册
        await integration.approve_and_register(suggestion_id)

        # 再次查询应为空
        suggestions = await integration.on_planning_start()
        assert suggestions == []

    @pytest.mark.asyncio
    async def test_accepts_context_parameter(self) -> None:
        """应接受 context 参数（预留扩展）。"""
        integration = LearningIntegration()
        suggestions = await integration.on_planning_start(context="一些上下文")
        assert isinstance(suggestions, list)


class TestApproveAndRegister:
    """测试 approve_and_register 方法。"""

    @pytest.mark.asyncio
    async def test_approve_and_register_skill(self) -> None:
        """确认注册应返回 SkillDefinition。"""
        integration = LearningIntegration(min_success_count=2)
        plan = _make_plan()

        await integration.on_execution_complete(plan, _make_result(True))
        await integration.on_execution_complete(plan, _make_result(True))

        suggestions = await integration.on_planning_start()
        suggestion_id = suggestions[0].id

        skill = await integration.approve_and_register(suggestion_id)

        assert skill is not None
        assert isinstance(skill, SkillDefinition)
        assert skill.category == "learned"
        assert skill.source == "auto_learned"

    @pytest.mark.asyncio
    async def test_approve_registers_to_registry(self) -> None:
        """确认注册后技能应出现在注册表中。"""
        integration = LearningIntegration(min_success_count=2)
        plan = _make_plan()

        await integration.on_execution_complete(plan, _make_result(True))
        await integration.on_execution_complete(plan, _make_result(True))

        suggestions = await integration.on_planning_start()
        suggestion_id = suggestions[0].id

        await integration.approve_and_register(suggestion_id)

        assert integration.registered_count == 1

    @pytest.mark.asyncio
    async def test_approve_nonexistent_returns_none(self) -> None:
        """确认不存在的 ID 应返回 None。"""
        integration = LearningIntegration()
        result = await integration.approve_and_register("nonexistent_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_approve_twice_returns_none(self) -> None:
        """重复确认同一建议应返回 None（状态已变）。"""
        integration = LearningIntegration(min_success_count=2)
        plan = _make_plan()

        await integration.on_execution_complete(plan, _make_result(True))
        await integration.on_execution_complete(plan, _make_result(True))

        suggestions = await integration.on_planning_start()
        suggestion_id = suggestions[0].id

        # 第一次确认成功
        skill = await integration.approve_and_register(suggestion_id)
        assert skill is not None

        # 第二次确认应失败（已 approved）
        result = await integration.approve_and_register(suggestion_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_rejected_suggestion_cannot_be_approved(self) -> None:
        """已拒绝的建议不能确认注册。"""
        integration = LearningIntegration(min_success_count=2)
        plan = _make_plan()

        await integration.on_execution_complete(plan, _make_result(True))
        await integration.on_execution_complete(plan, _make_result(True))

        suggestions = await integration.on_planning_start()
        suggestion_id = suggestions[0].id

        # 先拒绝
        await integration.reject_suggestion(suggestion_id)

        # 再确认应失败
        result = await integration.approve_and_register(suggestion_id)
        assert result is None


class TestRejectSuggestion:
    """测试 reject_suggestion 方法。"""

    @pytest.mark.asyncio
    async def test_reject_pending_suggestion(self) -> None:
        """应成功拒绝 pending 状态的建议。"""
        integration = LearningIntegration(min_success_count=2)
        plan = _make_plan()

        await integration.on_execution_complete(plan, _make_result(True))
        await integration.on_execution_complete(plan, _make_result(True))

        suggestions = await integration.on_planning_start()
        suggestion_id = suggestions[0].id

        result = await integration.reject_suggestion(suggestion_id)
        assert result is True

        # 拒绝后不应再出现在 pending 列表
        suggestions = await integration.on_planning_start()
        assert suggestions == []

    @pytest.mark.asyncio
    async def test_reject_nonexistent_returns_false(self) -> None:
        """拒绝不存在的 ID 应返回 False。"""
        integration = LearningIntegration()
        result = await integration.reject_suggestion("nonexistent")
        assert result is False


class TestQueryInterfaces:
    """测试查询接口。"""

    @pytest.mark.asyncio
    async def test_search_skills_empty(self) -> None:
        """空注册表搜索应返回空列表。"""
        integration = LearningIntegration()
        results = await integration.search_skills("测试")
        assert results == []

    @pytest.mark.asyncio
    async def test_list_registered_skills_empty(self) -> None:
        """空注册表应返回空列表。"""
        integration = LearningIntegration()
        skills = await integration.list_registered_skills()
        assert skills == []

    @pytest.mark.asyncio
    async def test_search_after_register(self) -> None:
        """注册后应能搜索到。"""
        integration = LearningIntegration(min_success_count=2)
        plan = _make_plan()

        await integration.on_execution_complete(plan, _make_result(True))
        await integration.on_execution_complete(plan, _make_result(True))

        suggestions = await integration.on_planning_start()
        await integration.approve_and_register(suggestions[0].id)

        skills = await integration.list_registered_skills()
        assert len(skills) == 1

    def test_pattern_count_initial(self) -> None:
        """初始 pattern_count 应为 0。"""
        integration = LearningIntegration()
        assert integration.pattern_count == 0

    def test_suggestion_count_initial(self) -> None:
        """初始 suggestion_count 应为 0。"""
        integration = LearningIntegration()
        assert integration.suggestion_count == 0

    def test_registered_count_initial(self) -> None:
        """初始 registered_count 应为 0。"""
        integration = LearningIntegration()
        assert integration.registered_count == 0


class TestLifecycle:
    """测试初始化和保存生命周期。"""

    @pytest.mark.asyncio
    async def test_initialize_with_no_storage(self) -> None:
        """无 storage_dir 时初始化不应报错。"""
        integration = LearningIntegration()
        await integration.initialize()
        assert integration.pattern_count == 0

    @pytest.mark.asyncio
    async def test_save_with_no_storage(self) -> None:
        """无 storage_dir 时保存不应报错。"""
        integration = LearningIntegration()
        await integration.save()


# ------------------------------------------------------------------
# BaseAgent 集成点测试
# ------------------------------------------------------------------


class TestBaseAgentLearningIntegration:
    """测试 BaseAgent 中新增的学习集成点。"""

    def test_learning_integration_initialized(self) -> None:
        """BaseAgent 应初始化 LearningIntegration 实例。"""
        from src.agents.base_agent import BaseAgent

        config = _make_config()
        agent = BaseAgent(config)

        assert hasattr(agent, "_learning")
        assert isinstance(agent._learning, LearningIntegration)

    def test_status_includes_learning_stats(self) -> None:
        """status 属性应包含学习统计信息。"""
        from src.agents.base_agent import BaseAgent

        config = _make_config()
        agent = BaseAgent(config)
        s = agent.status

        assert "learning_patterns" in s
        assert "learning_suggestions" in s
        assert "registered_skills" in s
        assert s["learning_patterns"] == 0
        assert s["learning_suggestions"] == 0
        assert s["registered_skills"] == 0

    @pytest.mark.asyncio
    async def test_execute_plan_calls_learning(self) -> None:
        """_execute_plan 应调用 _learning.on_execution_complete。"""
        from src.agents.base_agent import BaseAgent
        from src.core.models import DecisionPoint

        config = _make_config()
        agent = BaseAgent(config)

        # Mock planner
        plan = _make_plan()
        agent._planner = AsyncMock()
        agent._planner.plan.return_value = plan

        # Mock decider
        agent._decider = MagicMock()
        agent._decider.evaluate.return_value = DecisionPoint(
            context="test", question="test",
            confidence=0.9, auto_decided=True,
        )

        # Mock executor
        result = _make_result(success=True)
        agent._executor = AsyncMock()
        agent._executor.execute.return_value = result

        # Mock learning
        agent._learning = AsyncMock(spec=LearningIntegration)
        agent._learning.on_execution_complete = AsyncMock()

        await agent.process("测试任务")

        agent._learning.on_execution_complete.assert_called_once()
        call_args = agent._learning.on_execution_complete.call_args
        assert call_args[0][0] is plan
        assert call_args[0][1] is result

    @pytest.mark.asyncio
    async def test_planning_queries_learning(self) -> None:
        """规划前应调用 _learning.on_planning_start。"""
        from src.agents.base_agent import BaseAgent
        from src.core.models import DecisionPoint

        config = _make_config()
        agent = BaseAgent(config)

        # Mock planner
        plan = _make_plan()
        agent._planner = AsyncMock()
        agent._planner.plan.return_value = plan

        # Mock decider
        agent._decider = MagicMock()
        agent._decider.evaluate.return_value = DecisionPoint(
            context="test", question="test",
            confidence=0.9, auto_decided=True,
        )

        # Mock executor
        result = _make_result(success=True)
        agent._executor = AsyncMock()
        agent._executor.execute.return_value = result

        # Mock learning
        agent._learning = AsyncMock(spec=LearningIntegration)
        agent._learning.on_planning_start = AsyncMock(return_value=[])

        await agent.process("测试任务")

        agent._learning.on_planning_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_saves_learning(self) -> None:
        """close() 应调用 _learning.save()。"""
        from src.agents.base_agent import BaseAgent

        config = _make_config()
        agent = BaseAgent(config)

        agent._learning = AsyncMock(spec=LearningIntegration)
        agent._learning.save = AsyncMock()

        # Mock LLM to avoid errors
        agent._llm = AsyncMock()
        agent._llm.close = AsyncMock()

        await agent.close()

        agent._learning.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_learning_failure_does_not_break_execution(self) -> None:
        """学习模块异常不应中断正常执行流程。"""
        from src.agents.base_agent import BaseAgent
        from src.core.models import DecisionPoint

        config = _make_config()
        agent = BaseAgent(config)

        # Mock planner
        plan = _make_plan()
        agent._planner = AsyncMock()
        agent._planner.plan.return_value = plan

        # Mock decider
        agent._decider = MagicMock()
        agent._decider.evaluate.return_value = DecisionPoint(
            context="test", question="test",
            confidence=0.9, auto_decided=True,
        )

        # Mock executor
        result = _make_result(success=True)
        agent._executor = AsyncMock()
        agent._executor.execute.return_value = result

        # Mock learning — 模拟异常
        agent._learning = AsyncMock(spec=LearningIntegration)
        agent._learning.on_execution_complete = AsyncMock(
            side_effect=RuntimeError("学习模块故障")
        )
        agent._learning.on_planning_start = AsyncMock(return_value=[])

        # 不应抛异常
        response = await agent.process("测试任务")
        assert "✅" in response

    @pytest.mark.asyncio
    async def test_initialize_memory_includes_learning(self) -> None:
        """initialize_memory 应初始化学习模块。"""
        from src.agents.base_agent import BaseAgent

        config = _make_config()
        agent = BaseAgent(config)

        # Mock 长期记忆
        agent._long_term_memory = AsyncMock()
        agent._long_term_memory.count = 0

        # Mock 学习模块
        agent._learning = AsyncMock(spec=LearningIntegration)
        agent._learning.initialize = AsyncMock()
        agent._learning.pattern_count = 0

        await agent.initialize_memory()

        agent._long_term_memory.initialize.assert_called_once()
        agent._learning.initialize.assert_called_once()
