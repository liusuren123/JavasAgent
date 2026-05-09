"""Agent 间通信总线与数据模型。

提供 AgentStatus、MessagePriority、AgentInfo、TeamMessage、TaskAssignment
等数据模型，以及 CollaborationBus 通信总线类。
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
