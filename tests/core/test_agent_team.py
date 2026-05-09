"""多 Agent 协作框架测试。

覆盖 AgentTeam、TaskDistributor、CollaborationBus 三个核心类。
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from src.core.agent_team import (
    AgentInfo,
    AgentStatus,
    AgentTeam,
    CollaborationBus,
    MessagePriority,
    TaskAssignment,
    TaskDistributor,
    TeamMessage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def team() -> AgentTeam:
    """创建一个空团队。"""
    return AgentTeam(name="test_team")


@pytest_asyncio.fixture
async def populated_team() -> AgentTeam:
    """创建包含 3 个成员的团队。"""
    t = AgentTeam(name="populated_team")
    await t.add_agent("coder", "开发者", ["code", "programming", "testing"])
    await t.add_agent("researcher", "研究员", ["search", "analysis", "data"])
    await t.add_agent("operator", "运维", ["system", "file", "os"])
    return t


@pytest_asyncio.fixture
def bus() -> CollaborationBus:
    """创建通信总线。"""
    return CollaborationBus()


@pytest_asyncio.fixture
def distributor() -> TaskDistributor:
    """创建任务分发器。"""
    return TaskDistributor(llm_client=None)


# ---------------------------------------------------------------------------
# AgentTeam 测试
# ---------------------------------------------------------------------------


class TestAgentTeamAddRemove:
    """AgentTeam 添加/移除成员测试。"""

    @pytest.mark.asyncio
    async def test_add_agent(self, team: AgentTeam) -> None:
        """添加 agent 应返回 AgentInfo 并更新成员列表。"""
        info = await team.add_agent("a1", "测试员", ["test"])

        assert isinstance(info, AgentInfo)
        assert info.agent_id == "a1"
        assert info.role == "测试员"
        assert info.capabilities == ["test"]
        assert info.status == AgentStatus.IDLE
        assert team.member_count == 1

    @pytest.mark.asyncio
    async def test_add_agent_duplicate_raises(self, team: AgentTeam) -> None:
        """重复添加同一 agent 应抛出 ValueError。"""
        await team.add_agent("a1", "测试员", ["test"])

        with pytest.raises(ValueError, match="已在团队中"):
            await team.add_agent("a1", "测试员", ["test"])

    @pytest.mark.asyncio
    async def test_remove_agent(self, team: AgentTeam) -> None:
        """移除 agent 后成员数应减少。"""
        await team.add_agent("a1", "测试员", ["test"])
        await team.remove_agent("a1")

        assert team.member_count == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent_raises(self, team: AgentTeam) -> None:
        """移除不存在的 agent 应抛出 KeyError。"""
        with pytest.raises(KeyError, match="不在团队中"):
            await team.remove_agent("ghost")

    @pytest.mark.asyncio
    async def test_list_members(self, populated_team: AgentTeam) -> None:
        """列出成员应返回正确的信息。"""
        members = populated_team.list_members()

        assert len(members) == 3
        ids = {m["agent_id"] for m in members}
        assert ids == {"coder", "researcher", "operator"}

    @pytest.mark.asyncio
    async def test_list_members_empty(self, team: AgentTeam) -> None:
        """空团队返回空列表。"""
        assert team.list_members() == []

    @pytest.mark.asyncio
    async def test_get_member(self, populated_team: AgentTeam) -> None:
        """获取指定成员信息。"""
        info = populated_team.get_member("coder")
        assert info is not None
        assert info.role == "开发者"

    @pytest.mark.asyncio
    async def test_get_member_nonexistent(self, team: AgentTeam) -> None:
        """获取不存在的成员返回 None。"""
        assert team.get_member("nobody") is None


# ---------------------------------------------------------------------------
# 任务分配测试
# ---------------------------------------------------------------------------


class TestAgentTeamAssignTask:
    """AgentTeam 任务分配测试。"""

    @pytest.mark.asyncio
    async def test_assign_task_auto(self, populated_team: AgentTeam) -> None:
        """自动分配任务应成功。"""
        result = await populated_team.assign_task("写一个函数")

        assert result["success"] is True
        assert result["agent_id"] in ("coder", "researcher", "operator")
        assert "assignment_id" in result

    @pytest.mark.asyncio
    async def test_assign_task_preferred(self, populated_team: AgentTeam) -> None:
        """指定首选 agent 应分配给该 agent。"""
        result = await populated_team.assign_task("搜索资料", preferred_agent="researcher")

        assert result["success"] is True
        assert result["agent_id"] == "researcher"

    @pytest.mark.asyncio
    async def test_assign_task_preferred_nonexistent(self, populated_team: AgentTeam) -> None:
        """指定不存在的 agent 应返回失败。"""
        result = await populated_team.assign_task("测试", preferred_agent="ghost")

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_assign_task_empty_team(self, team: AgentTeam) -> None:
        """空团队分配任务应返回错误。"""
        result = await team.assign_task("测试任务")

        assert result["success"] is False
        assert "没有可用 agent" in result["error"]

    @pytest.mark.asyncio
    async def test_assign_sets_agent_busy(self, populated_team: AgentTeam) -> None:
        """分配任务后 agent 状态应变为 BUSY。"""
        await populated_team.assign_task("任务", preferred_agent="coder")

        info = populated_team.get_member("coder")
        assert info is not None
        assert info.status == AgentStatus.BUSY

    @pytest.mark.asyncio
    async def test_complete_assignment(self, populated_team: AgentTeam) -> None:
        """完成任务后 agent 状态应恢复 IDLE。"""
        result = await populated_team.assign_task("任务", preferred_agent="coder")
        assignment_id = result["assignment_id"]

        populated_team.complete_assignment(assignment_id, {"output": "done"})

        info = populated_team.get_member("coder")
        assert info is not None
        assert info.status == AgentStatus.IDLE
        assert info.current_task is None


# ---------------------------------------------------------------------------
# AgentTeam 广播与状态测试
# ---------------------------------------------------------------------------


class TestAgentTeamBroadcastStatus:
    """AgentTeam 广播和状态查询测试。"""

    @pytest.mark.asyncio
    async def test_broadcast(self, populated_team: AgentTeam) -> None:
        """广播消息应发送给所有成员。"""
        # 广播前需要让 bus 知道各 agent 的邮箱
        messages = await populated_team.broadcast("大家好")

        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_get_team_status(self, populated_team: AgentTeam) -> None:
        """获取团队状态应返回正确信息。"""
        status = await populated_team.get_team_status()

        assert status["team_name"] == "populated_team"
        assert status["total_members"] == 3
        assert status["idle_members"] == 3
        assert status["busy_members"] == 0
        assert len(status["members"]) == 3

    @pytest.mark.asyncio
    async def test_team_status_reflects_busy(self, populated_team: AgentTeam) -> None:
        """分配任务后团队状态应反映忙碌成员。"""
        await populated_team.assign_task("任务", preferred_agent="coder")

        status = await populated_team.get_team_status()
        assert status["busy_members"] == 1
        assert status["idle_members"] == 2


# ---------------------------------------------------------------------------
# CollaborationBus 测试
# ---------------------------------------------------------------------------


class TestCollaborationBus:
    """CollaborationBus 消息收发测试。"""

    @pytest.mark.asyncio
    async def test_send_message(self, bus: CollaborationBus) -> None:
        """发送点对点消息应存入接收者邮箱。"""
        msg = await bus.send_message("a1", "a2", "你好")

        assert isinstance(msg, TeamMessage)
        assert msg.from_id == "a1"
        assert msg.to_id == "a2"
        assert msg.content == "你好"
        assert msg.read is False

    @pytest.mark.asyncio
    async def test_send_message_empty_to_raises(self, bus: CollaborationBus) -> None:
        """发送到空 ID 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="to_id"):
            await bus.send_message("a1", "", "test")

    @pytest.mark.asyncio
    async def test_get_messages_unread(self, bus: CollaborationBus) -> None:
        """获取未读消息应返回消息并标记已读。"""
        await bus.send_message("a1", "a2", "msg1")
        await bus.send_message("a1", "a2", "msg2")

        messages = await bus.get_messages("a2")

        assert len(messages) == 2
        assert all(m.read for m in messages)

    @pytest.mark.asyncio
    async def test_get_messages_empty(self, bus: CollaborationBus) -> None:
        """没有消息时应返回空列表。"""
        messages = await bus.get_messages("nobody")
        assert messages == []

    @pytest.mark.asyncio
    async def test_get_messages_consumes_unread(self, bus: CollaborationBus) -> None:
        """第二次获取应没有新消息。"""
        await bus.send_message("a1", "a2", "msg")

        first = await bus.get_messages("a2")
        assert len(first) == 1

        second = await bus.get_messages("a2")
        assert len(second) == 0

    @pytest.mark.asyncio
    async def test_broadcast(self, bus: CollaborationBus) -> None:
        """广播消息应发给所有已注册邮箱的 agent（排除发送者）。"""
        # 先注册邮箱
        await bus.send_message("a0", "a1", "init")
        await bus.send_message("a0", "a2", "init")

        messages = await bus.broadcast("a0", "广播消息")

        # 广播给 a1 和 a2（排除 a0）
        assert len(messages) == 2
        recipients = {m.to_id for m in messages}
        assert recipients == {"a1", "a2"}

    @pytest.mark.asyncio
    async def test_broadcast_no_recipients(self, bus: CollaborationBus) -> None:
        """没有注册邮箱时广播应返回空列表。"""
        messages = await bus.broadcast("a0", "广播消息")
        assert messages == []

    @pytest.mark.asyncio
    async def test_register_handler(self, bus: CollaborationBus) -> None:
        """注册处理器后发送消息应触发处理器。"""
        received: list[TeamMessage] = []

        async def handler(msg: TeamMessage) -> None:
            received.append(msg)

        await bus.register_handler("a2", handler)
        await bus.send_message("a1", "a2", "触发处理器")

        assert len(received) == 1
        assert received[0].content == "触发处理器"

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_crash(self, bus: CollaborationBus) -> None:
        """处理器抛异常不应影响消息存储。"""
        async def bad_handler(msg: TeamMessage) -> None:
            raise RuntimeError("handler error")

        await bus.register_handler("a2", bad_handler)
        msg = await bus.send_message("a1", "a2", "test")

        # 消息仍然存在
        assert msg is not None
        all_msgs = await bus.get_all_messages("a2")
        assert len(all_msgs) == 1

    @pytest.mark.asyncio
    async def test_reset(self, bus: CollaborationBus) -> None:
        """reset 应清空所有消息和处理器。"""
        await bus.send_message("a1", "a2", "msg")
        bus.reset()

        messages = await bus.get_all_messages("a2")
        assert messages == []


# ---------------------------------------------------------------------------
# TaskDistributor 测试
# ---------------------------------------------------------------------------


class TestTaskDistributor:
    """TaskDistributor 智能分发测试。"""

    @pytest.mark.asyncio
    async def test_distribute_simple_task(self, populated_team: AgentTeam) -> None:
        """简单任务应能分发成功。"""
        distributor = TaskDistributor()
        results = await distributor.distribute("搜索Python资料", populated_team)

        assert len(results) >= 1
        assert results[0]["success"] is True
        assert results[0]["agent_id"] == "researcher"  # 搜索能力匹配

    @pytest.mark.asyncio
    async def test_distribute_empty_team(self, team: AgentTeam) -> None:
        """空团队应返回错误。"""
        distributor = TaskDistributor()
        results = await distributor.distribute("测试任务", team)

        assert len(results) == 1
        assert results[0]["success"] is False

    @pytest.mark.asyncio
    async def test_distribute_multi_subtask(self, populated_team: AgentTeam) -> None:
        """复合任务应被拆分并分配给不同 agent。"""
        distributor = TaskDistributor()
        task = "搜索最新AI论文；编写代码实现模型；整理数据到文档"
        results = await distributor.distribute(task, populated_team)

        # 应拆分为 3 个子任务
        assert len(results) == 3

        # 每个 agent 分配到的任务
        assigned_agents = [r["agent_id"] for r in results if r.get("success")]
        assert len(assigned_agents) > 0

    @pytest.mark.asyncio
    async def test_distribute_capability_matching(
        self, populated_team: AgentTeam
    ) -> None:
        """代码任务应优先匹配 coder agent。"""
        distributor = TaskDistributor()
        results = await distributor.distribute("编写测试代码", populated_team)

        assert results[0]["success"] is True
        assert results[0]["agent_id"] == "coder"

    @pytest.mark.asyncio
    async def test_distribute_system_task(
        self, populated_team: AgentTeam
    ) -> None:
        """系统任务应匹配 operator agent。"""
        distributor = TaskDistributor()
        results = await distributor.distribute("检查系统文件状态", populated_team)

        assert results[0]["success"] is True
        assert results[0]["agent_id"] == "operator"

    @pytest.mark.asyncio
    async def test_merge_results_all_success(self) -> None:
        """合并全部成功的结果。"""
        distributor = TaskDistributor()
        results = [
            {"success": True, "agent_id": "a1", "subtask": "t1", "result": {"output": "r1"}},
            {"success": True, "agent_id": "a2", "subtask": "t2", "result": {"output": "r2"}},
        ]

        merged = await distributor.merge_results(results)

        assert merged["success"] is True
        assert merged["total_subtasks"] == 2
        assert merged["successful"] == 2
        assert merged["failed"] == 0

    @pytest.mark.asyncio
    async def test_merge_results_partial_failure(self) -> None:
        """合并部分失败的结果。"""
        distributor = TaskDistributor()
        results = [
            {"success": True, "agent_id": "a1", "subtask": "t1", "result": {"output": "r1"}},
            {"success": False, "error": "执行失败"},
        ]

        merged = await distributor.merge_results(results)

        assert merged["success"] is False
        assert merged["successful"] == 1
        assert merged["failed"] == 1
        assert len(merged["errors"]) == 1

    @pytest.mark.asyncio
    async def test_merge_results_empty(self) -> None:
        """合并空结果应返回错误。"""
        distributor = TaskDistributor()
        merged = await distributor.merge_results([])

        assert merged["success"] is False
        assert "没有结果" in merged["error"]


# ---------------------------------------------------------------------------
# AgentInfo 数据模型测试
# ---------------------------------------------------------------------------


class TestAgentInfo:
    """AgentInfo 辅助方法测试。"""

    def test_has_capability(self) -> None:
        """has_capability 应支持模糊匹配。"""
        info = AgentInfo(agent_id="a1", role="dev", capabilities=["code", "web_search"])
        assert info.has_capability("code") is True
        assert info.has_capability("search") is True  # web_search 包含 search
        assert info.has_capability("image") is False

    def test_capability_score(self) -> None:
        """capability_score 应计算正确匹配度。"""
        info = AgentInfo(agent_id="a1", role="dev", capabilities=["code", "testing"])

        score = info.capability_score(["code", "testing"])
        assert score == 1.0

        score = info.capability_score(["code"])
        assert score == 1.0

        score = info.capability_score(["code", "image"])
        assert score == 0.5

    def test_capability_score_empty_required(self) -> None:
        """空需求应返回 1.0。"""
        info = AgentInfo(agent_id="a1", role="dev", capabilities=["code"])
        assert info.capability_score([]) == 1.0
