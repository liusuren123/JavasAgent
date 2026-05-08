"""Windows 平台适配器。

使用 pyautogui + Win32 API 实现 Windows 桌面操控。
"""

from __future__ import annotations

import io
from typing import Any

import pyautogui
from loguru import logger

from src.platforms.base import PlatformAdapter


class WindowsAdapter(PlatformAdapter):
    """Windows 平台适配器。"""

    def __init__(self, action_delay: float = 0.5) -> None:
        self._delay = action_delay
        pyautogui.PAUSE = action_delay
        pyautogui.FAILSAFE = True  # 鼠标移到角落紧急停止

    async def screenshot(self, region: tuple[int, int, int, int] | None = None) -> bytes:
        """截屏并返回 PNG bytes。"""
        img = pyautogui.screenshot(region=region)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        logger.debug(f"截屏完成, 区域: {region or '全屏'}")
        return buf.getvalue()

    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None:
        """点击屏幕坐标。"""
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
        logger.debug(f"点击: ({x}, {y}), 按钮: {button}, 次数: {clicks}")

    async def type_text(self, text: str, interval: float = 0.02) -> None:
        """输入文字。"""
        pyautogui.typewrite(text, interval=interval)
        logger.debug(f"输入文字: {text[:20]}...")

    async def press_key(self, key: str) -> None:
        """按下按键。"""
        pyautogui.press(key)
        logger.debug(f"按键: {key}")

    async def hotkey(self, *keys: str) -> None:
        """组合键。"""
        pyautogui.hotkey(*keys)
        logger.debug(f"组合键: {'+'.join(keys)}")

    async def get_active_window(self) -> dict[str, Any]:
        """获取当前活动窗口信息。

        使用 pywin32 获取窗口详情。
        """
        try:
            import win32gui
            import win32process

            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            rect = win32gui.GetWindowRect(hwnd)

            return {
                "hwnd": hwnd,
                "title": title,
                "pid": pid,
                "rect": {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]},
            }
        except ImportError:
            logger.warning("pywin32 未安装，返回基础窗口信息")
            return {"title": "unknown", "hwnd": 0}

    async def find_window(self, title: str) -> list[dict[str, Any]]:
        """按标题查找窗口。"""
        try:
            import win32gui

            results: list[dict[str, Any]] = []

            def _enum_cb(hwnd: int, _: Any) -> None:
                if win32gui.IsWindowVisible(hwnd):
                    win_title = win32gui.GetWindowText(hwnd)
                    if title.lower() in win_title.lower():
                        results.append({"hwnd": hwnd, "title": win_title})

            win32gui.EnumWindows(_enum_cb, None)
            return results
        except ImportError:
            logger.warning("pywin32 未安装")
            return []

    async def activate_window(self, window_id: str) -> bool:
        """激活指定窗口。"""
        try:
            import win32gui

            hwnd = int(window_id)
            win32gui.SetForegroundWindow(hwnd)
            logger.info(f"激活窗口: {hwnd}")
            return True
        except Exception as e:
            logger.error(f"激活窗口失败: {e}")
            return False
