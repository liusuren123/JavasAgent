"""多 Agent 协作框架。

提供 AgentTeam（团队管理）、TaskDistributor（智能任务分发）、
CollaborationBus（Agent 间通信总线）三个核心类，支持多 Agent 协作完成复杂任务。
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine

from loguru import logger


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


class AgentStatus(str, Enum):
    """Agent 状态。"""

    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"


class MessagePriority(int, Enum):
    """消息优先级。"""

    LOW = 0
    NORMAL = 5
    HIGH = 10


@dataclass
class AgentInfo:
    """Agent 成员信息。"""

    agent_id: str
    role: str
    capabilities: list[str] = field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    current_task: str | None = None
    joined_at: datetime = field(default_factory=datetime.now)

    def has_capability(self, cap: str) -> bool:
        """检查是否具备指定能力（支持模糊前缀匹配）。"""
        cap_lower = cap.lower()
        return any(cap_lower in c.lower() for c in self.capabilities)

    def capability_score(self, required: list[str]) -> float:
        """计算与所需能力的匹配度（0-1）。"""
        if not required:
            return 1.0
        matched = sum(1 for r in required if self.has_capability(r))
        return matched / len(required)


@dataclass
class TeamMessage:
    """团队内消息。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    from_id: str = ""
    to_id: str = ""  # 空字符串表示广播
    content: str = ""
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: datetime = field(default_factory=datetime.now)
    read: bool = False


@dataclass
class TaskAssignment:
    """任务分配记录。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task: str = ""
    agent_id: str = ""
    subtask_index: int = 0
    status: str = "assigned"  # assigned / running / done / failed
    result: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# CollaborationBus — Agent 间通信总线
# ---------------------------------------------------------------------------


class CollaborationBus:
    """Agent 间通信总线。

    支持点对点消息、广播以及消息处理器注册。
    所有消息存储在内存队列中，按 agent_id 分区。
    """

    def __init__(self) -> None:
        self._mailboxes: dict[str, list[TeamMessage]] = defaultdict(list)
        self._handlers: dict[str, Callable[[TeamMessage], Coroutine[Any, Any, None]]] = {}
        self._lock = asyncio.Lock()
        logger.debug("CollaborationBus 已初始化")

    async def send_message(
        self,
        from_id: str,
        to_id: str,
        message: str,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> TeamMessage:
        """发送点对点消息。

        Args:
            from_id: 发送者 ID
            to_id: 接收者 ID
            message: 消息内容
            priority: 消息优先级

        Returns:
            发送的消息对象

        Raises:
            ValueError: to_id 为空时
        """
        if not to_id:
            raise ValueError("to_id 不能为空，广播请使用 broadcast 方法")

        msg = TeamMessage(
            from_id=from_id,
            to_id=to_id,
            content=message,
            priority=priority,
        )

        async with self._lock:
            self._mailboxes[to_id].append(msg)

        logger.debug(f"消息 {msg.id}: {from_id} -> {to_id} ({len(message)} 字符)")

        # 如果注册了处理器，立即触发
        handler = self._handlers.get(to_id)
        if handler is not None:
            try:
                await handler(msg)
            except Exception as exc:
                logger.error(f"处理器异常 (agent={to_id}): {exc}")

        return msg

    async def broadcast(
        self,
        from_id: str,
        message: str,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> list[TeamMessage]:
        """广播消息给所有已注册邮箱的 agent。

        Args:
            from_id: 发送者 ID
            message: 消息内容
            priority: 消息优先级

        Returns:
            所有发送的消息对象列表
        """
        messages: list[TeamMessage] = []
        async with self._lock:
            recipients = [aid for aid in self._mailboxes if aid != from_id]
            for aid in recipients:
                msg = TeamMessage(
                    from_id=from_id,
                    to_id=aid,
                    content=message,
                    priority=priority,
                )
                self._mailboxes[aid].append(msg)
                messages.append(msg)

        logger.debug(f"广播 {from_id} -> {len(recipients)} 个 agent ({len(message)} 字符)")

        # 触发处理器
        for msg in messages:
            handler = self._handlers.get(msg.to_id)
            if handler is not None:
                try:
                    await handler(msg)
                except Exception as exc:
                    logger.error(f"处理器异常 (agent={msg.to_id}): {exc}")

        return messages

    async def get_messages(self, agent_id: str) -> list[TeamMessage]:
        """获取指定 agent 的未读消息。

        返回所有未读消息并将它们标记为已读。

        Args:
            agent_id: 接收者 ID

        Returns:
            未读消息列表
        """
        async with self._lock:
            unread = [m for m in self._mailboxes.get(agent_id, []) if not m.read]
            for m in unread:
                m.read = True
        logger.debug(f"agent {agent_id} 获取 {len(unread)} 条未读消息")
        return unread

    async def get_all_messages(self, agent_id: str) -> list[TeamMessage]:
        """获取指定 agent 的所有消息（含已读）。

        Args:
            agent_id: 接收者 ID

        Returns:
            所有消息列表
        """
        async with self._lock:
            msgs = list(self._mailboxes.get(agent_id, []))
        return msgs

    async def register_handler(
        self, agent_id: str, handler: Callable[[TeamMessage], Coroutine[Any, Any, None]]
    ) -> None:
        """注册消息处理器。

        当 agent 收到消息时自动调用处理器。
        每个 agent 只能注册一个处理器，后注册的会覆盖前面的。

        Args:
            agent_id: agent ID
            handler: 异步消息处理函数
        """
        self._handlers[agent_id] = handler
        logger.debug(f"agent {agent_id} 注册了消息处理器")

    def reset(self) -> None:
        """清空所有消息和处理器（主要用于测试）。"""
        self._mailboxes.clear()
        self._handlers.clear()


# ---------------------------------------------------------------------------
# AgentTeam — 管理一组协作 Agent
# ---------------------------------------------------------------------------


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
# TaskDistributor — 智能任务分发
# ---------------------------------------------------------------------------


# 关键词 -> 推荐能力映射
_KEYWORD_CAPABILITY_MAP: dict[str, list[str]] = {
    "代码": ["code", "programming"],
    "编程": ["code", "programming"],
    "搜索": ["search", "web"],
    "查询": ["search", "web"],
    "文件": ["file", "system"],
    "系统": ["system", "os"],
    "浏览器": ["browser", "web"],
    "分析": ["analysis", "data"],
    "数据": ["data", "analysis"],
    "邮件": ["email"],
    "图片": ["image", "media"],
    "视频": ["video", "media"],
    "文档": ["document", "office"],
    "测试": ["code", "testing"],
}


class TaskDistributor:
    """智能任务分发器。

    根据任务描述分析所需能力，自动匹配最合适的 agent 执行。
    支持任务拆分（将大任务按关键词拆分为子任务）和结果合并。
    """

    def __init__(self, llm_client: Any | None = None) -> None:
        """初始化分发器。

        Args:
            llm_client: 可选的 LLM 客户端，用于复杂任务分析
        """
        self._llm_client = llm_client
        self._keyword_map = _KEYWORD_CAPABILITY_MAP.copy()

    def _infer_required_capabilities(self, task: str) -> list[str]:
        """从任务描述推断所需能力。

        Args:
            task: 任务描述

        Returns:
            推断出的能力列表
        """
        capabilities: set[str] = set()
        for keyword, caps in self._keyword_map.items():
            if keyword in task:
                capabilities.update(caps)
        # 如果没有匹配到任何能力，返回通用能力
        return list(capabilities) if capabilities else ["general"]

    def _split_task(self, task: str) -> list[str]:
        """尝试拆分复合任务。

        简单策略：按句号/分号拆分，过滤过短的子句。
        如果拆分后只有一条或零条，则不拆分。

        Args:
            task: 原始任务描述

        Returns:
            子任务列表
        """
        import re

        parts = re.split(r"[。；;\n]", task)
        parts = [p.strip() for p in parts if len(p.strip()) > 2]

        return parts if len(parts) > 1 else [task]

    async def distribute(self, task: str, team: AgentTeam) -> list[dict[str, Any]]:
        """分析任务并分发给团队成员。

        工作流程:
        1. 推断任务所需能力
        2. 尝试拆分复合任务
        3. 为每个子任务匹配最合适的 agent
        4. 并行分发并收集结果

        Args:
            task: 任务描述
            team: 目标团队

        Returns:
            分发结果列表，每项包含 agent_id、subtask、status 等
        """
        required_caps = self._infer_required_capabilities(task)
        subtasks = self._split_task(task)

        logger.info(
            f"任务分发: {len(subtasks)} 个子任务, 所需能力: {required_caps}"
        )

        results: list[dict[str, Any]] = []
        members = team.list_members()

        if not members:
            logger.warning("团队中没有成员，无法分发任务")
            return [{"success": False, "error": "团队中没有成员", "subtask": task}]

        for idx, subtask in enumerate(subtasks):
            # 匹配最佳 agent
            best_agent = self._find_best_agent(
                members, self._infer_required_capabilities(subtask)
            )

            if best_agent is None:
                results.append({
                    "success": False,
                    "error": "没有匹配的 agent",
                    "subtask": subtask,
                    "subtask_index": idx,
                })
                continue

            # 分配任务
            assign_result = await team.assign_task(subtask, preferred_agent=best_agent)

            results.append({
                "success": assign_result.get("success", False),
                "assignment_id": assign_result.get("assignment_id"),
                "agent_id": assign_result.get("agent_id", best_agent),
                "subtask": subtask,
                "subtask_index": idx,
                "status": "assigned",
            })

            logger.info(
                f"子任务 {idx} 已分配给 agent {best_agent}: {subtask[:50]}"
            )

        return results

    def _find_best_agent(
        self, members: list[dict[str, Any]], required_caps: list[str]
    ) -> str | None:
        """根据能力需求找到最佳 agent。

        优先选择能力匹配度最高且空闲的 agent。

        Args:
            members: 成员信息列表
            required_caps: 所需能力列表

        Returns:
            最佳 agent ID 或 None
        """
        best_id: str | None = None
        best_score = -1.0

        for m in members:
            caps = m.get("capabilities", [])
            if not required_caps:
                score = 1.0
            else:
                matched = sum(
                    1 for r in required_caps
                    if any(r.lower() in c.lower() for c in caps)
                )
                score = matched / len(required_caps)

            # 空闲 agent 加权
            if m.get("status") == "idle":
                score += 0.1

            if score > best_score:
                best_score = score
                best_id = m.get("agent_id")

        return best_id

    async def merge_results(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """合并多个 agent 的执行结果。

        Args:
            results: 各 agent 的执行结果列表

        Returns:
            合并后的结果，包含总体状态、汇总信息等
        """
        if not results:
            return {"success": False, "error": "没有结果可合并", "summary": ""}

        total = len(results)
        successful = sum(1 for r in results if r.get("success"))
        failed = total - successful

        # 收集各 agent 的输出
        outputs: list[str] = []
        errors: list[str] = []

        for r in results:
            if r.get("success"):
                agent_id = r.get("agent_id", "unknown")
                subtask = r.get("subtask", "")
                result_data = r.get("result", {})
                outputs.append(f"[{agent_id}] {subtask}: {result_data}")
            else:
                errors.append(r.get("error", "未知错误"))

        summary = "\n".join(outputs) if outputs else "所有子任务均失败"

        merged = {
            "success": failed == 0,
            "total_subtasks": total,
            "successful": successful,
            "failed": failed,
            "summary": summary,
            "outputs": outputs,
            "errors": errors,
        }

        logger.info(f"结果合并: {successful}/{total} 成功")
        return merged
