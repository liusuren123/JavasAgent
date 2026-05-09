"""TeamIntegrationMixin 集成测试。

使用 mock 替代真实 AgentTeam，测试 Mixin 各方法的正确性。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.team_integration import TeamIntegrationMixin
from src.core.models import PlanStatus, Priority, Step, StepStatus, TaskPlan
from src.utils.config import AppConfig, TeamConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(step_count: int) -> TaskPlan:
    """创建指定步骤数的 TaskPlan（用于测试）。"""
    steps = [
        Step(id=f"s{i}", action=f"action-{i}", tool="shell", params={})
        for i in range(step_count)
    ]
    return TaskPlan(
        id="test-plan",
        intent="test intent",
        steps=steps,
        priority=Priority.NORMAL,
        status=PlanStatus.PENDING,
    )


def _make_config(enabled: bool = False, threshold: int = 5) -> AppConfig:
    """创建带指定团队配置的 AppConfig。"""
    return AppConfig(team=TeamConfig(enabled=enabled, delegation_threshold=threshold))


class _DummyAgent(TeamIntegrationMixin):
    """用于测试的 Mixin 宿主类。"""

    def __init__(self, config: AppConfig) -> None:
        self._init_team_integration(config)


# ---------------------------------------------------------------------------
# Tests: 初始化
# ---------------------------------------------------------------------------


class TestInit:
    """测试 __init_team_integration 初始化逻辑。"""

    def test_disabled_by_default(self) -> None:
        """默认配置下，团队未启用。"""
        agent = _DummyAgent(AppConfig())
        assert agent._team_enabled is False
        assert agent._team is None
        assert agent._task_distributor is None

    def test_enabled_creates_team(self) -> None:
        """启用后应创建 AgentTeam 和 TaskDistributor。"""
        cfg = _make_config(enabled=True)
        agent = _DummyAgent(cfg)
        assert agent._team_enabled is True
        assert agent._team is not None
        assert agent._task_distributor is not None

    def test_custom_threshold(self) -> None:
        """自定义委派阈值应正确保存。"""
        cfg = _make_config(enabled=True, threshold=10)
        agent = _DummyAgent(cfg)
        assert agent._delegation_threshold == 10

    def test_delegated_ids_empty_on_init(self) -> None:
        """初始化时已委派列表应为空。"""
        agent = _DummyAgent(_make_config(enabled=True))
        assert agent._delegated_task_ids == []


# ---------------------------------------------------------------------------
# Tests: should_delegate
# ---------------------------------------------------------------------------


class TestShouldDelegate:
    """测试 should_delegate 判断逻辑。"""

    @pytest.mark.asyncio
    async def test_disabled_team_returns_false(self) -> None:
        """团队未启用时永远返回 False。"""
        agent = _DummyAgent(_make_config(enabled=False))
        plan = _make_plan(10)
        assert await agent.should_delegate(plan) is False

    @pytest.mark.asyncio
    async def test_no_members_returns_false(self) -> None:
        """团队启用但无成员时返回 False。"""
        agent = _DummyAgent(_make_config(enabled=True))
        # 不添加任何成员
        plan = _make_plan(10)
        assert await agent.should_delegate(plan) is False

    @pytest.mark.asyncio
    async def test_below_threshold_returns_false(self) -> None:
        """步骤数低于阈值时返回 False。"""
        agent = _DummyAgent(_make_config(enabled=True, threshold=5))
        await agent._team.add_agent("w1", "worker", ["code"])
        plan = _make_plan(3)  # 3 < 5
        assert await agent.should_delegate(plan) is False

    @pytest.mark.asyncio
    async def test_above_threshold_with_members_returns_true(self) -> None:
        """步骤数超过阈值且有成员时返回 True。"""
        agent = _DummyAgent(_make_config(enabled=True, threshold=5))
        await agent._team.add_agent("w1", "worker", ["code"])
        plan = _make_plan(8)  # 8 > 5
        assert await agent.should_delegate(plan) is True

    @pytest.mark.asyncio
    async def test_exactly_at_threshold_returns_false(self) -> None:
        """步骤数恰好等于阈值时返回 False。"""
        agent = _DummyAgent(_make_config(enabled=True, threshold=5))
        await agent._team.add_agent("w1", "worker", ["code"])
        plan = _make_plan(5)  # 5 == 5, not > 5
        assert await agent.should_delegate(plan) is False


# ---------------------------------------------------------------------------
# Tests: delegate_subtask
# ---------------------------------------------------------------------------


class TestDelegateSubtask:
    """测试 delegate_subtask 委派逻辑。"""

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self) -> None:
        """团队未启用时返回空字符串。"""
        agent = _DummyAgent(_make_config(enabled=False))
        result = await agent.delegate_subtask("do something")
        assert result == ""

    @pytest.mark.asyncio
    async def test_successful_delegation(self) -> None:
        """成功委派应返回 assignment_id 并记录。"""
        agent = _DummyAgent(_make_config(enabled=True))
        await agent._team.add_agent("w1", "worker", ["code"])

        result = await agent.delegate_subtask("编写测试代码")
        assert result != ""
        assert result in agent._delegated_task_ids

    @pytest.mark.asyncio
    async def test_no_members_returns_empty(self) -> None:
        """无成员时委派应失败。"""
        agent = _DummyAgent(_make_config(enabled=True))
        # 不添加成员
        result = await agent.delegate_subtask("do something")
        assert result == ""


# ---------------------------------------------------------------------------
# Tests: delegate_task (公开接口)
# ---------------------------------------------------------------------------


class TestDelegateTask:
    """测试 delegate_task 公开接口。"""

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self) -> None:
        """团队未启用时返回空字符串。"""
        agent = _DummyAgent(_make_config(enabled=False))
        result = await agent.delegate_task("写代码", agent_role="coder")
        assert result == ""

    @pytest.mark.asyncio
    async def test_delegates_to_matching_role(self) -> None:
        """应优先分配给匹配角色的空闲 Agent。"""
        agent = _DummyAgent(_make_config(enabled=True))
        await agent._team.add_agent("coder_1", "coder", ["code"])
        await agent._team.add_agent("worker_1", "worker", ["general"])

        result = await agent.delegate_task("写代码", agent_role="coder")
        assert result != ""

        # 验证分配给了 coder 角色的 Agent
        assignment = None
        for a in agent._team._assignments:
            if a.id == result:
                assignment = a
                break
        assert assignment is not None
        assert assignment.agent_id == "coder_1"

    @pytest.mark.asyncio
    async def test_fallback_to_any_idle(self) -> None:
        """没有匹配角色时应回退到任意空闲 Agent。"""
        agent = _DummyAgent(_make_config(enabled=True))
        await agent._team.add_agent("worker_1", "worker", ["general"])

        result = await agent.delegate_task("写代码", agent_role="coder")
        assert result != ""
        # 应该分配给 worker（因为没有 coder）


# ---------------------------------------------------------------------------
# Tests: monitor_progress
# ---------------------------------------------------------------------------


class TestMonitorProgress:
    """测试 monitor_progress 监控逻辑。"""

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self) -> None:
        """团队未启用时返回空字典。"""
        agent = _DummyAgent(_make_config(enabled=False))
        result = await agent.monitor_progress()
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_team_status(self) -> None:
        """启用时应返回包含团队信息的字典。"""
        agent = _DummyAgent(_make_config(enabled=True))
        await agent._team.add_agent("w1", "worker", ["code"])

        result = await agent.monitor_progress()
        assert result["total_members"] == 1
        assert result["idle_members"] == 1
        assert result["delegated_tasks"] == 0

    @pytest.mark.asyncio
    async def test_tracks_delegated_count(self) -> None:
        """应正确跟踪已委派任务数。"""
        agent = _DummyAgent(_make_config(enabled=True))
        await agent._team.add_agent("w1", "worker", ["code"])

        await agent.delegate_subtask("task 1")
        result = await agent.monitor_progress()
        assert result["delegated_tasks"] == 1


# ---------------------------------------------------------------------------
# Tests: aggregate_results
# ---------------------------------------------------------------------------


class TestAggregateResults:
    """测试 aggregate_results 聚合逻辑。"""

    @pytest.mark.asyncio
    async def test_disabled_returns_error(self) -> None:
        """团队未启用时应返回错误。"""
        agent = _DummyAgent(_make_config(enabled=False))
        result = await agent.aggregate_results(["t1"])
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_not_found_task(self) -> None:
        """不存在的任务 ID 应标记为 not_found。"""
        agent = _DummyAgent(_make_config(enabled=True))
        await agent._team.add_agent("w1", "worker", ["code"])

        result = await agent.aggregate_results(["nonexistent"])
        assert result["total"] == 1
        assert result["results"][0]["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_completed_task(self) -> None:
        """已完成的任务应包含结果。"""
        agent = _DummyAgent(_make_config(enabled=True))
        await agent._team.add_agent("w1", "worker", ["code"])

        # 委派并手动完成
        task_id = await agent.delegate_subtask("do something")
        assert task_id != ""

        # 标记完成
        agent._team.complete_assignment(task_id, {"output": "done"})

        result = await agent.aggregate_results([task_id])
        assert result["success"] is True
        assert result["successful"] == 1

    @pytest.mark.asyncio
    async def test_mixed_results(self) -> None:
        """混合结果应正确统计成功和失败数。"""
        agent = _DummyAgent(_make_config(enabled=True))
        await agent._team.add_agent("w1", "worker", ["code"])

        task_id = await agent.delegate_subtask("do something")
        # 不完成该任务（状态仍为 assigned）

        result = await agent.aggregate_results([task_id, "nonexistent"])
        assert result["total"] == 2
        assert result["successful"] == 0


# ---------------------------------------------------------------------------
# Tests: collect_all_results
# ---------------------------------------------------------------------------


class TestCollectAllResults:
    """测试 collect_all_results 全量收集逻辑。"""

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self) -> None:
        """团队未启用时返回空列表。"""
        agent = _DummyAgent(_make_config(enabled=False))
        result = await agent.collect_all_results()
        assert result == []

    @pytest.mark.asyncio
    async def test_collects_from_assignments(self) -> None:
        """应从团队分配记录中收集所有结果。"""
        agent = _DummyAgent(_make_config(enabled=True))
        await agent._team.add_agent("w1", "worker", ["code"])

        await agent.delegate_subtask("task A")

        results = await agent.collect_all_results()
        assert len(results) == 1
        assert results[0]["task"] == "task A"


# ---------------------------------------------------------------------------
# Tests: get_team_status (同步方法)
# ---------------------------------------------------------------------------


class TestGetTeamStatus:
    """测试 get_team_status 同步方法。"""

    def test_disabled_status(self) -> None:
        """未启用时应返回 enabled=False。"""
        agent = _DummyAgent(_make_config(enabled=False))
        status = agent.get_team_status()
        assert status["enabled"] is False

    def test_enabled_status(self) -> None:
        """启用后应返回包含成员信息的完整状态。"""
        agent = _DummyAgent(_make_config(enabled=True))
        asyncio.get_event_loop().run_until_complete(
            agent._team.add_agent("w1", "worker", ["code"])
        )

        status = agent.get_team_status()
        assert status["enabled"] is True
        assert status["total_members"] == 1
        assert len(status["members"]) == 1
