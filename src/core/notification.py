"""通知管理器。

支持主动通知、规则引擎和处理器分发的通知系统。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from loguru import logger


class NotificationLevel(str, Enum):
    """通知级别。"""

    INFO = "info"
    WARNING = "warning"
    URGENT = "urgent"


@dataclass
class Notification:
    """通知数据。"""

    id: str
    title: str
    message: str
    level: NotificationLevel
    source: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    is_read: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationRule:
    """通知规则。

    当事件匹配时自动调整通知级别或过滤通知。
    condition 可以是 callable（接收 title/source/metadata）或简单字符串匹配 source。
    """

    rule_id: str
    event_type: str
    condition: Callable[..., bool] | str
    level: NotificationLevel
    enabled: bool = True


class NotificationManager:
    """通知管理器。

    统一管理通知的创建、存储、分发和处理。
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        self._notifications: list[Notification] = []
        self._rules: list[NotificationRule] = []
        self._handlers: dict[NotificationLevel, list[Callable[..., Any]]] = {
            level: [] for level in NotificationLevel
        }
        self._lock = asyncio.Lock()

    async def notify(
        self,
        title: str,
        message: str,
        level: NotificationLevel = NotificationLevel.INFO,
        source: str = "",
        metadata: dict | None = None,
    ) -> Notification:
        """发送一条通知。

        先经过规则引擎匹配，可能升级级别，然后存储并分发。
        """
        # 规则引擎：检查是否需要升级级别
        effective_level = self._apply_rules(title, source, metadata, level)

        notification = Notification(
            id=str(uuid.uuid4()),
            title=title,
            message=message,
            level=effective_level,
            source=source,
            metadata=metadata or {},
        )

        async with self._lock:
            self._notifications.append(notification)

        await self.dispatch(notification)

        logger.info(
            f"通知 [{effective_level.value}]: {title} (来源: {source or '未知'})"
        )
        return notification

    async def get_unread(self, limit: int = 20) -> list[Notification]:
        """获取未读通知。"""
        async with self._lock:
            unread = [n for n in self._notifications if not n.is_read]
            return list(reversed(unread))[:limit]

    async def mark_read(self, notification_id: str) -> bool:
        """标记通知为已读。"""
        async with self._lock:
            for notification in self._notifications:
                if notification.id == notification_id:
                    notification.is_read = True
                    return True
        return False

    async def get_history(
        self,
        limit: int = 50,
        level: NotificationLevel | None = None,
    ) -> list[Notification]:
        """获取历史通知，可按级别过滤。"""
        async with self._lock:
            notifications = self._notifications
            if level is not None:
                notifications = [n for n in notifications if n.level == level]
            return list(reversed(notifications))[:limit]

    def add_rule(self, rule: NotificationRule) -> None:
        """添加通知规则。"""
        self._rules.append(rule)
        logger.debug(f"添加通知规则: {rule.rule_id} (事件: {rule.event_type})")

    def register_handler(
        self, level: NotificationLevel, handler: Callable[..., Any]
    ) -> None:
        """注册通知处理器。

        不同级别的通知可以注册不同的处理函数。
        例如 INFO -> 日志记录，WARNING -> 通知栏，URGENT -> 弹窗+语音。
        """
        self._handlers[level].append(handler)
        logger.debug(f"注册 {level.value} 级别处理器: {handler.__name__}")

    async def dispatch(self, notification: Notification) -> None:
        """根据注册的 handler 分发通知。"""
        handlers = self._handlers.get(notification.level, [])
        for handler in handlers:
            try:
                result = handler(notification)
                # 支持 async handler
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"通知处理器异常 [{notification.level.value}]: {e}")

    def get_stats(self) -> dict[str, Any]:
        """统计信息：总数、未读数、各级别数量。"""
        total = len(self._notifications)
        unread = sum(1 for n in self._notifications if not n.is_read)
        by_level: dict[str, int] = {}
        for level in NotificationLevel:
            by_level[level.value] = sum(
                1 for n in self._notifications if n.level == level
            )
        return {
            "total": total,
            "unread": unread,
            "by_level": by_level,
        }

    def _apply_rules(
        self,
        title: str,
        source: str,
        metadata: dict | None,
        original_level: NotificationLevel,
    ) -> NotificationLevel:
        """应用通知规则，返回最终级别。"""
        level = original_level
        for rule in self._rules:
            if not rule.enabled:
                continue
            matched = self._match_rule(rule, title, source, metadata)
            if matched:
                # 级别升级：取更高级别
                level = self._higher_level(level, rule.level)
        return level

    def _match_rule(
        self,
        rule: NotificationRule,
        title: str,
        source: str,
        metadata: dict | None,
    ) -> bool:
        """判断规则是否匹配。"""
        condition = rule.condition
        if callable(condition):
            try:
                return condition(title=title, source=source, metadata=metadata or {})
            except Exception:
                return False
        # 字符串条件：匹配 source
        return str(condition) == source

    @staticmethod
    def _higher_level(
        a: NotificationLevel, b: NotificationLevel
    ) -> NotificationLevel:
        """取两个级别中更高的。"""
        order = [NotificationLevel.INFO, NotificationLevel.WARNING, NotificationLevel.URGENT]
        idx_a = order.index(a)
        idx_b = order.index(b)
        return order[max(idx_a, idx_b)]
