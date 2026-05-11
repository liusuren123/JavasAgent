"""Windows 平台适配器。

使用 pyautogui + Win32 API 实现 Windows 桌面操控。
支持中文输入（通过剪贴板粘贴方式）。
"""

from __future__ import annotations

import io
from typing import Any

import pyautogui
from loguru import logger

from src.platforms.base import PlatformAdapter


def _paste_via_clipboard(text: str) -> None:
    """通过剪贴板粘贴文本，支持中文和特殊字符。

    优先使用 pyperclip 库操作剪贴板（成熟、跨平台、正确处理 Unicode），
    若 pyperclip 不可用则回退到 ctypes Win32 API（已修复 64 位兼容性）。

    Args:
        text: 要输入的文本
    """
    import time

    # 优先使用 pyperclip
    try:
        import pyperclip

        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        return
    except ImportError:
        logger.warning("pyperclip 未安装，尝试 ctypes 回退方案")

    # 回退：使用 ctypes（修复 64 位指针兼容性）
    import ctypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    # 设置参数和返回值类型（修复 64 位系统上指针截断问题）
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    if not user32.OpenClipboard(0):
        logger.error("无法打开剪贴板")
        return

    try:
        user32.EmptyClipboard()

        text_bytes = text.encode("utf-16-le") + b"\x00\x00"
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_bytes))
        if not h_mem:
            logger.error("无法分配剪贴板内存")
            return

        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            kernel32.GlobalFree(h_mem)
            logger.error("无法锁定剪贴板内存")
            return

        ctypes.cdll.msvcrt.memcpy(p_mem, text_bytes, len(text_bytes))
        kernel32.GlobalUnlock(h_mem)

        if not user32.SetClipboardData(CF_UNICODETEXT, h_mem):
            kernel32.GlobalFree(h_mem)
            logger.error("无法设置剪贴板数据")
            return
    finally:
        user32.CloseClipboard()

    time.sleep(0.05)
    pyautogui.hotkey("ctrl", "v")


def _has_non_ascii(text: str) -> bool:
    """检查文本是否包含非 ASCII 字符。"""
    return any(ord(c) > 127 for c in text)


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
        """输入文字。

        自动检测文本内容：
        - 纯 ASCII 文本：使用 pyautogui.typewrite（逐字输入）
        - 包含中文/特殊字符：使用剪贴板粘贴（一次性输入）

        Args:
            text: 要输入的文本
            interval: 逐字输入时的字符间隔（仅对 ASCII 文本有效）
        """
        if _has_non_ascii(text):
            _paste_via_clipboard(text)
            logger.debug(f"粘贴输入文本: {text[:20]}...")
        else:
            pyautogui.typewrite(text, interval=interval)
            logger.debug(f"键盘输入文本: {text[:20]}...")

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

    async def scroll(self, clicks: int = 3, direction: str = "down") -> None:
        """滚动鼠标滚轮。

        Args:
            clicks: 滚动次数
            direction: 滚动方向 ("up" 或 "down")
        """
        pyautogui.scroll(clicks if direction == "up" else -clicks)
        logger.debug(f"滚动: {direction} {clicks} 次")

    async def move_to(self, x: int, y: int, duration: float = 0.3) -> None:
        """移动鼠标到指定坐标。

        Args:
            x: 目标 X 坐标
            y: 目标 Y 坐标
            duration: 移动持续时间（秒）
        """
        pyautogui.moveTo(x, y, duration=duration)
        logger.debug(f"移动鼠标到: ({x}, {y})")

    async def drag_to(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
        button: str = "left",
    ) -> None:
        """从起点拖拽到终点。

        Args:
            start_x: 起点 X
            start_y: 起点 Y
            end_x: 终点 X
            end_y: 终点 Y
            duration: 拖拽持续时间
            button: 鼠标按钮
        """
        pyautogui.moveTo(start_x, start_y)
        pyautogui.drag(
            end_x - start_x,
            end_y - start_y,
            duration=duration,
            button=button,
        )
        logger.debug(f"拖拽: ({start_x},{start_y}) -> ({end_x},{end_y})")

    async def get_screen_size(self) -> dict[str, int]:
        """获取屏幕分辨率。

        Returns:
            包含 width 和 height 的字典
        """
        size = pyautogui.size()
        return {"width": size.width, "height": size.height}
