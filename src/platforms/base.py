"""平台适配基类。

定义平台操作的标准接口，各平台实现具体逻辑。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PlatformAdapter(ABC):
    """平台适配器基类。"""

    @abstractmethod
    async def screenshot(self, region: tuple[int, int, int, int] | None = None) -> bytes:
        """截屏。"""
        ...

    @abstractmethod
    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None:
        """点击屏幕坐标。"""
        ...

    @abstractmethod
    async def type_text(self, text: str, interval: float = 0.02) -> None:
        """输入文字。"""
        ...

    @abstractmethod
    async def press_key(self, key: str) -> None:
        """按下按键。"""
        ...

    @abstractmethod
    async def hotkey(self, *keys: str) -> None:
        """组合键。"""
        ...

    @abstractmethod
    async def get_active_window(self) -> dict[str, Any]:
        """获取当前活动窗口信息。"""
        ...

    @abstractmethod
    async def find_window(self, title: str) -> list[dict[str, Any]]:
        """按标题查找窗口。"""
        ...

    @abstractmethod
    async def activate_window(self, window_id: str) -> bool:
        """激活指定窗口。"""
        ...
