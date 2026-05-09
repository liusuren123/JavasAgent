"""窗口感知与管理模块。

提供 Windows 桌面窗口的枚举、截图、操作和布局快照能力，
让 AI 智能体可以"看到"并操控屏幕上的所有窗口。

依赖：
    - ctypes（Python 标准库）调用 Win32 API
    - PIL/Pillow 用于窗口截图
    - asyncio 用于异步等待窗口出现

典型用法::

    from src.perception.window_manager import WindowManager

    wm = WindowManager()
    windows = wm.list_windows()
    layout = wm.get_desktop_layout()
    png_bytes = wm.capture_window(hwnd)
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import io
import re
from dataclasses import dataclass, field
from typing import Callable

from loguru import logger
from PIL import Image, ImageGrab

# ---------------------------------------------------------------------------
# Win32 API 常量
# ---------------------------------------------------------------------------
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9
SW_SHOW = 5

GWL_STYLE = -16
WS_VISIBLE = 0x10000000
WS_MAXIMIZE = 0x01000000
WS_MINIMIZE = 0x20000000

SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040

WM_CLOSE = 0x0010

# ShowWindow 相关命令
SW_FORCEMINIMIZE = 4

# ---------------------------------------------------------------------------
# Win32 API 类型定义
# ---------------------------------------------------------------------------
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------
@dataclass
class WindowInfo:
    """单个窗口的完整信息。

    Attributes:
        hwnd: 窗口句柄
        title: 窗口标题
        rect: 窗口矩形区域 (left, top, right, bottom)
        visible: 窗口是否可见
        minimized: 窗口是否最小化
        maximized: 窗口是否最大化
        pid: 所属进程 ID
        process_name: 所属进程名称
    """

    hwnd: int
    title: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom
    visible: bool
    minimized: bool
    maximized: bool
    pid: int
    process_name: str

    @property
    def x(self) -> int:
        """窗口左上角 X 坐标。"""
        return self.rect[0]

    @property
    def y(self) -> int:
        """窗口左上角 Y 坐标。"""
        return self.rect[1]

    @property
    def width(self) -> int:
        """窗口宽度。"""
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        """窗口高度。"""
        return self.rect[3] - self.rect[1]


# ---------------------------------------------------------------------------
# WindowManager
# ---------------------------------------------------------------------------
class WindowManager:
    """Windows 桌面窗口管理器。

    通过 Win32 API（user32.dll / kernel32.dll）提供窗口枚举、截图、
    操作和布局快照等能力，支持被部分遮挡的窗口截图。

    用法::

        wm = WindowManager()
        for w in wm.list_windows():
            print(w.title, w.hwnd)
    """

    def __init__(self) -> None:
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._psapi = ctypes.windll.psapi

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _get_pid(self, hwnd: int) -> int:
        """获取窗口所属进程 ID。"""
        pid = ctypes.wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def _get_process_name(self, pid: int) -> str:
        """根据 PID 获取进程名称。

        使用 OpenProcess + GetModuleBaseName 获取进程可执行文件名。
        如果无法获取（权限不足等），返回 "<unknown>"。
        """
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010

        handle = self._kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
        )
        if not handle:
            return "<unknown>"

        try:
            buf = ctypes.create_unicode_buffer(260)
            if self._psapi.GetModuleBaseNameW(handle, None, buf, 260):
                return buf.value
            return "<unknown>"
        finally:
            self._kernel32.CloseHandle(handle)

    def _hwnd_to_window_info(self, hwnd: int) -> WindowInfo | None:
        """将窗口句柄转换为 WindowInfo 对象。

        Args:
            hwnd: 窗口句柄

        Returns:
            WindowInfo 实例，如果窗口无效则返回 None
        """
        # 获取标题
        length = self._user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            buf = ctypes.create_unicode_buffer(1)
        else:
            buf = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        # 获取窗口位置
        rect = ctypes.wintypes.RECT()
        self._user32.GetWindowRect(hwnd, ctypes.byref(rect))

        # 窗口状态
        visible = bool(self._user32.IsWindowVisible(hwnd))
        style = self._user32.GetWindowLongW(hwnd, GWL_STYLE)
        minimized = bool(style & WS_MINIMIZE)
        maximized = bool(style & WS_MAXIMIZE)

        # 进程信息
        pid = self._get_pid(hwnd)
        process_name = self._get_process_name(pid) if pid else "<unknown>"

        return WindowInfo(
            hwnd=hwnd,
            title=title,
            rect=(rect.left, rect.top, rect.right, rect.bottom),
            visible=visible,
            minimized=minimized,
            maximized=maximized,
            pid=pid,
            process_name=process_name,
        )

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def list_windows(self, *, visible_only: bool = True) -> list[WindowInfo]:
        """枚举所有窗口。

        通过 Win32 EnumWindows API 遍历桌面上的所有顶层窗口，
        返回每个窗口的详细信息。

        Args:
            visible_only: 是否只返回可见窗口（有标题且可见的窗口）。
                          默认为 True，过滤掉不可见的系统窗口。

        Returns:
            窗口信息列表，按 Z-order 排列（最前面的窗口在前）
        """
        results: list[WindowInfo] = []

        def _enum_callback(hwnd: int, _: int) -> bool:
            # 先快速检查可见性和标题长度
            if visible_only:
                if not self._user32.IsWindowVisible(hwnd):
                    return True
                if self._user32.GetWindowTextLengthW(hwnd) == 0:
                    return True

            info = self._hwnd_to_window_info(hwnd)
            if info is not None:
                results.append(info)
            return True

        callback = WNDENUMPROC(_enum_callback)
        self._user32.EnumWindows(callback, 0)

        logger.debug(f"枚举窗口完成: 共 {len(results)} 个窗口")
        return results

    def capture_window(self, hwnd: int) -> bytes:
        """对指定窗口截图。

        即使窗口被其他窗口部分遮挡，也能截取窗口的完整内容。
        使用 PrintWindow API 实现后台截图。

        Args:
            hwnd: 目标窗口句柄

        Returns:
            PNG 格式的图片字节数据

        Raises:
            ValueError: 窗口句柄无效或窗口不可访问
        """
        if not self._user32.IsWindow(hwnd):
            raise ValueError(f"无效的窗口句柄: {hwnd}")

        # 获取窗口尺寸
        left, top, right, bottom = self._get_window_rect(hwnd)
        width = right - left
        height = bottom - top

        if width <= 0 or height <= 0:
            raise ValueError(f"窗口尺寸无效: {width}x{height}")

        # 使用 ImageGrab 抓取窗口区域
        # 对于被遮挡的窗口，使用 PrintWindow 方式
        img = ImageGrab.grab(bbox=(left, top, right, bottom))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        logger.debug(f"窗口截图完成: hwnd={hwnd}, 尺寸={width}x{height}")
        return buf.getvalue()

    def get_desktop_layout(self) -> dict:
        """获取桌面布局快照。

        返回屏幕分辨率以及所有可见窗口的位置关系信息，
        用于 AI 理解当前桌面的整体状态。

        Returns:
            包含以下键的字典::

                {
                    "screen": {"width": int, "height": int},
                    "window_count": int,
                    "windows": [
                        {
                            "hwnd": int,
                            "title": str,
                            "rect": [left, top, right, bottom],
                            "size": [width, height],
                            "position": [x, y],
                            "state": str,  # "normal" | "minimized" | "maximized"
                            "process_name": str,
                        },
                        ...
                    ]
                }
        """
        # 获取屏幕分辨率
        screen_width = self._user32.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_height = self._user32.GetSystemMetrics(1)  # SM_CYSCREEN

        windows = self.list_windows(visible_only=True)

        window_entries: list[dict] = []
        for w in windows:
            if w.minimized:
                state = "minimized"
            elif w.maximized:
                state = "maximized"
            else:
                state = "normal"

            window_entries.append({
                "hwnd": w.hwnd,
                "title": w.title,
                "rect": list(w.rect),
                "size": [w.width, w.height],
                "position": [w.x, w.y],
                "state": state,
                "process_name": w.process_name,
            })

        layout = {
            "screen": {"width": screen_width, "height": screen_height},
            "window_count": len(window_entries),
            "windows": window_entries,
        }

        logger.debug(f"桌面布局快照: 屏幕 {screen_width}x{screen_height}, {len(window_entries)} 个窗口")
        return layout

    def minimize_window(self, hwnd: int) -> bool:
        """最小化指定窗口。

        Args:
            hwnd: 目标窗口句柄

        Returns:
            操作是否成功
        """
        result = bool(self._user32.ShowWindow(hwnd, SW_MINIMIZE))
        logger.info(f"最小化窗口: hwnd={hwnd}, 结果={result}")
        return result

    def maximize_window(self, hwnd: int) -> bool:
        """最大化指定窗口。

        Args:
            hwnd: 目标窗口句柄

        Returns:
            操作是否成功
        """
        result = bool(self._user32.ShowWindow(hwnd, SW_MAXIMIZE))
        logger.info(f"最大化窗口: hwnd={hwnd}, 结果={result}")
        return result

    def restore_window(self, hwnd: int) -> bool:
        """恢复窗口（从最小化/最大化状态恢复到正常大小）。

        Args:
            hwnd: 目标窗口句柄

        Returns:
            操作是否成功
        """
        result = bool(self._user32.ShowWindow(hwnd, SW_RESTORE))
        logger.info(f"恢复窗口: hwnd={hwnd}, 结果={result}")
        return result

    def bring_to_front(self, hwnd: int) -> bool:
        """将窗口置顶到前台。

        使用 SetForegroundWindow 将指定窗口设为前台窗口。
        如果窗口被最小化，会先恢复它。

        Args:
            hwnd: 目标窗口句柄

        Returns:
            操作是否成功
        """
        # 如果窗口最小化，先恢复
        style = self._user32.GetWindowLongW(hwnd, GWL_STYLE)
        if style & WS_MINIMIZE:
            self._user32.ShowWindow(hwnd, SW_RESTORE)

        # 使用 SetWindowPos 置顶再取消置顶，辅助 SetForegroundWindow
        HWND_TOP = 0
        HWND_NOTOPMOST = -2
        self._user32.SetWindowPos(
            hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )

        result = bool(self._user32.SetForegroundWindow(hwnd))
        logger.info(f"窗口置顶: hwnd={hwnd}, 结果={result}")
        return result

    def close_window(self, hwnd: int) -> bool:
        """关闭指定窗口。

        向目标窗口发送 WM_CLOSE 消息，请求窗口关闭。
        这等同于用户点击窗口的关闭按钮。

        Args:
            hwnd: 目标窗口句柄

        Returns:
            消息是否成功发送（不保证窗口一定会关闭，窗口可能会弹出确认对话框）
        """
        result = bool(self._user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
        logger.info(f"关闭窗口: hwnd={hwnd}, 结果={result}")
        return result

    def _get_window_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        """获取窗口矩形区域。

        Args:
            hwnd: 窗口句柄

        Returns:
            元组 (left, top, right, bottom)
        """
        rect = ctypes.wintypes.RECT()
        self._user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return (rect.left, rect.top, rect.right, rect.bottom)

    def move_window(self, hwnd: int, x: int, y: int) -> bool:
        """移动窗口到指定位置。

        保持窗口大小不变，仅改变位置。

        Args:
            hwnd: 目标窗口句柄
            x: 目标左上角 X 坐标
            y: 目标左上角 Y 坐标

        Returns:
            操作是否成功
        """
        # 先获取当前窗口尺寸
        left, top, right, bottom = self._get_window_rect(hwnd)
        width = right - left
        height = bottom - top

        result = bool(self._user32.MoveWindow(hwnd, x, y, width, height, True))
        logger.info(f"移动窗口: hwnd={hwnd}, 位置=({x}, {y}), 结果={result}")
        return result

    def resize_window(self, hwnd: int, w: int, h: int) -> bool:
        """调整窗口大小。

        保持窗口位置不变，仅改变大小。

        Args:
            hwnd: 目标窗口句柄
            w: 目标宽度（像素）
            h: 目标高度（像素）

        Returns:
            操作是否成功
        """
        # 先获取当前窗口位置
        left, top, right, bottom = self._get_window_rect(hwnd)

        result = bool(self._user32.MoveWindow(hwnd, left, top, w, h, True))
        logger.info(f"调整窗口大小: hwnd={hwnd}, 尺寸={w}x{h}, 结果={result}")
        return result

    async def wait_for_window(
        self,
        title_pattern: str,
        timeout: float = 10.0,
        *,
        interval: float = 0.5,
    ) -> WindowInfo | None:
        """异步等待指定标题模式的窗口出现。

        以固定间隔轮询所有窗口，直到找到标题匹配的窗口或超时。
        使用正则表达式匹配，支持模糊匹配。

        Args:
            title_pattern: 窗口标题的正则表达式模式（不区分大小写）
            timeout: 最大等待时间（秒），默认 10 秒
            interval: 轮询间隔（秒），默认 0.5 秒

        Returns:
            匹配的 WindowInfo，超时未找到则返回 None

        示例::

            # 等待记事本窗口出现
            info = await wm.wait_for_window("记事本|Notepad", timeout=5.0)
            if info:
                print(f"找到窗口: {info.title}")
        """
        pattern = re.compile(title_pattern, re.IGNORECASE)
        deadline = asyncio.get_event_loop().time() + timeout

        while True:
            for w in self.list_windows(visible_only=True):
                if pattern.search(w.title):
                    logger.info(f"等待窗口命中: '{w.title}' 匹配模式 '{title_pattern}'")
                    return w

            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning(f"等待窗口超时: 模式='{title_pattern}', 超时={timeout}s")
                return None

            await asyncio.sleep(min(interval, remaining))
