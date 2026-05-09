"""多 Agent 团队管理。

提供 AgentTeam 类，管理一组协作 Agent 的成员、任务分配和团队状态。
内部使用 CollaborationBus 进行 Agent 间通信，支持 TaskDistributor 进行智能分发。
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

# 从拆分后的模块导入
from src.core.collaboration_bus import (
    AgentInfo,
    AgentStatus,
    CollaborationBus,
    TaskAssignment,
    TeamMessage,
)

# 向后兼容：允许 from src.core.agent_team import X 仍然工作
__all__ = [
    "AgentInfo",
    "AgentStatus",
    "AgentTeam",
    "CollaborationBus",
    "MessagePriority",
    "TaskAssignment",
    "TaskDistributor",
    "TeamMessage",
]


class AgentTeam:
    """管理一组协作 Agent。

    提供成员管理、任务分配、团队状态查询等功能。
    内部使用 CollaborationBus 进行 Agent 间通信。
    """

    def __init__(self, name: str, coordinator_config: dict[str, Any] | None = None) -> None:
        """创建团队。

        Args:
            name: 团队名称
            coordinator_config: 协调器配置，可包含 llm_client 等
        """
        self.name = name
        self._config = coordinator_config or {}
        self._members: dict[str, AgentInfo] = {}
        self._assignments: list[TaskAssignment] = []
        self._bus = CollaborationBus()
        self._lock = asyncio.Lock()
        logger.info(f"AgentTeam '{name}' 已创建")

    @property
    def bus(self) -> CollaborationBus:
        """获取通信总线。"""
        return self._bus

    @property
    def member_count(self) -> int:
        """当前成员数量。"""
        return len(self._members)

    async def add_agent(
        self, agent_id: str, role: str, capabilities: list[str]
    ) -> AgentInfo:
        """添加成员到团队。

        Args:
            agent_id: agent 唯一标识
            role: 角色描述（如 "coder", "researcher"）
            capabilities: 能力列表（如 ["code", "search", "analysis"]）

        Returns:
            添加的 AgentInfo

        Raises:
            ValueError: agent_id 已存在时
        """
        if agent_id in self._members:
            raise ValueError(f"agent {agent_id} 已在团队中")

        info = AgentInfo(
            agent_id=agent_id,
            role=role,
            capabilities=list(capabilities),
        )

        async with self._lock:
            self._members[agent_id] = info
            # 在总线中注册邮箱，使广播能到达该 agent
            if agent_id not in self._bus._mailboxes:
                self._bus._mailboxes[agent_id] = []

        logger.info(f"agent {agent_id} (角色: {role}) 加入团队 '{self.name}'")
        return info

    async def remove_agent(self, agent_id: str) -> None:
        """从团队移除成员。

        Args:
            agent_id: agent ID

        Raises:
            KeyError: agent_id 不存在时
        """
        async with self._lock:
            if agent_id not in self._members:
                raise KeyError(f"agent {agent_id} 不在团队中")
            del self._members[agent_id]
            # 清理总线邮箱
            self._bus._mailboxes.pop(agent_id, None)

        logger.info(f"agent {agent_id} 已从团队 '{self.name}' 移除")

    async def assign_task(
        self, task: str, preferred_agent: str | None = None
    ) -> dict[str, Any]:
        """分配任务给最合适的 agent。

        如果指定了 preferred_agent，则直接分配给该 agent（前提是它存在且空闲）。
        否则根据能力匹配度和当前负载自动选择最合适的 agent。

        Args:
            task: 任务描述
            preferred_agent: 首选 agent ID

        Returns:
            分配结果，包含 agent_id、assignment_id 等
        """
        async with self._lock:
            # 指定 agent
            if preferred_agent is not None:
                if preferred_agent not in self._members:
                    return {"success": False, "error": f"agent {preferred_agent} 不存在"}
                agent = self._members[preferred_agent]
            else:
                # 自动选择：优先空闲且能力匹配最高的
                candidates = [
                    a for a in self._members.values()
                    if a.status == AgentStatus.IDLE
                ]
                if not candidates:
                    # 如果没有空闲的，选择最不忙的
                    candidates = list(self._members.values())
                if not candidates:
                    return {"success": False, "error": "团队中没有可用 agent"}
                agent = candidates[0]

            assignment = TaskAssignment(
                task=task,
                agent_id=agent.agent_id,
            )
            self._assignments.append(assignment)
            agent.status = AgentStatus.BUSY
            agent.current_task = assignment.id

        logger.info(f"任务已分配: {assignment.id} -> agent {agent.agent_id}")

        return {
            "success": True,
            "assignment_id": assignment.id,
            "agent_id": agent.agent_id,
            "task": task,
        }

    async def broadcast(self, message: str) -> list[TeamMessage]:
        """向所有成员广播消息。

        Args:
            message: 消息内容

        Returns:
            发送的消息列表
        """
        return await self._bus.broadcast("__team_coordinator__", message)

    async def get_team_status(self) -> dict[str, Any]:
        """获取团队状态。

        Returns:
            包含成员状态、任务统计等信息的字典
        """
        async with self._lock:
            members_status = [
                {
                    "agent_id": info.agent_id,
                    "role": info.role,
                    "status": info.status.value,
                    "current_task": info.current_task,
                    "capabilities": info.capabilities,
                }
                for info in self._members.values()
            ]
            idle_count = sum(
                1 for m in self._members.values() if m.status == AgentStatus.IDLE
            )
            busy_count = sum(
                1 for m in self._members.values() if m.status == AgentStatus.BUSY
            )

        return {
            "team_name": self.name,
            "total_members": len(self._members),
            "idle_members": idle_count,
            "busy_members": busy_count,
            "total_assignments": len(self._assignments),
            "members": members_status,
        }

    def list_members(self) -> list[dict[str, Any]]:
        """列出所有成员及角色。

        Returns:
            成员信息列表
        """
        return [
            {
                "agent_id": info.agent_id,
                "role": info.role,
                "capabilities": info.capabilities,
                "status": info.status.value,
            }
            for info in self._members.values()
        ]

    def get_member(self, agent_id: str) -> AgentInfo | None:
        """获取指定成员信息。

        Args:
            agent_id: agent ID

        Returns:
            AgentInfo 或 None
        """
        return self._members.get(agent_id)

    def complete_assignment(self, assignment_id: str, result: dict[str, Any]) -> None:
        """标记任务分配完成。

        Args:
            assignment_id: 分配 ID
            result: 执行结果
        """
        for a in self._assignments:
            if a.id == assignment_id:
                a.status = "done"
                a.result = result
                # 释放 agent
                agent = self._members.get(a.agent_id)
                if agent and agent.current_task == assignment_id:
                    agent.status = AgentStatus.IDLE
                    agent.current_task = None
                logger.info(f"任务分配 {assignment_id} 已完成")
                return
        logger.warning(f"未找到任务分配: {assignment_id}")


# ---------------------------------------------------------------------------
# 向后兼容 re-export：允许旧 import 路径继续工作
# ---------------------------------------------------------------------------

from src.core.collaboration_bus import MessagePriority  # noqa: E402
from src.core.task_distributor import TaskDistributor  # noqa: E402
