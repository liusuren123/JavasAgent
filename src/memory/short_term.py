"""短期记忆模块。

管理当前会话的上下文信息和任务执行状态。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger


@dataclass
class Message:
    """对话消息。"""

    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


class ShortTermMemory:
    """短期记忆（会话级）。"""

    def __init__(self, max_messages: int = 50) -> None:
        self._messages: deque[Message] = deque(maxlen=max_messages)
        self._context: dict[str, Any] = {}
        self._max_messages = max_messages

    def add(self, role: str, content: str, **metadata: Any) -> None:
        """添加一条消息。"""
        msg = Message(role=role, content=content, metadata=metadata)
        self._messages.append(msg)
        logger.debug(f"短期记忆添加: {role} ({len(content)} 字符)")

    def get_messages(self, last_n: int | None = None) -> list[Message]:
        """获取消息列表。

        Args:
            last_n: 只获取最后 N 条，为 None 则返回全部
        """
        msgs = list(self._messages)
        if last_n:
            return msgs[-last_n:]
        return msgs

    def get_context_for_llm(self, max_chars: int = 8000) -> list[dict[str, str]]:
        """生成适合传给 LLM 的上下文消息列表。

        从最新的消息开始取，直到达到字符限制。
        """
        result: list[dict[str, str]] = []
        total_chars = 0

        for msg in reversed(self._messages):
            entry = {"role": msg.role, "content": msg.content}
            total_chars += len(msg.content)

            if total_chars > max_chars:
                break
            result.insert(0, entry)

        return result

    def set(self, key: str, value: Any) -> None:
        """设置上下文变量。"""
        self._context[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """获取上下文变量。"""
        return self._context.get(key, default)

    def clear(self) -> None:
        """清空短期记忆。"""
        self._messages.clear()
        self._context.clear()
        logger.info("短期记忆已清空")

    @property
    def size(self) -> int:
        """当前消息数量。"""
        return len(self._messages)
