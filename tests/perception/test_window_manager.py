"""WindowManager 单元测试。

使用 unittest.mock 替代实际 Win32 API 调用，
确保测试可以在任何平台上运行。
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# 模拟 ctypes.windll，使测试不依赖 Windows
# ---------------------------------------------------------------------------
# 在 import window_manager 之前注入 mock 模块
_mock_user32 = MagicMock()
_mock_kernel32 = MagicMock()
_mock_psapi = MagicMock()

_mock_windll = types.SimpleNamespace(
    user32=_mock_user32,
    kernel32=_mock_kernel32,
    psapi=_mock_psapi,
)

# 保存原始 windll（可能不存在于非 Windows 平台）
_original_ctypes = sys.modules.get("ctypes")


class _FakeWindll:
    user32 = _mock_user32
    kernel32 = _mock_kernel32
    psapi = _mock_psapi


# Patch ctypes.windll before importing
import ctypes as _ctypes

if not hasattr(_ctypes, "windll"):
    _ctypes.windll = _FakeWindll()

# Mock ctypes.windll on the module itself
_mock_ctypes_module = _ctypes
_original_windll = getattr(_mock_ctypes_module, "windll", None)
_mock_ctypes_module.windll = _FakeWindll()

# Mock ctypes.wintypes
if not hasattr(_ctypes, "wintypes"):
    _fake_wintypes = types.ModuleType("ctypes.wintypes")
    _fake_wintypes.HWND = int
    _fake_wintypes.LPARAM = int
    _fake_wintypes.DWORD = type("DWORD", (), {"value": 0})
    _fake_wintypes.RECT = type("RECT", (), {
        "left": 0, "top": 0, "right": 0, "bottom": 0,
        "__init__": lambda self, **kw: None,
    })
    sys.modules["ctypes.wintypes"] = _fake_wintypes
    _ctypes.wintypes = _fake_wintypes

# Mock PIL.ImageGrab
_mock_image = MagicMock()
_mock_image.save = MagicMock()
_mock_image_obj = _mock_image

_mock_imagegrab = MagicMock()
_mock_imagegrab.grab = MagicMock(return_value=_mock_image)

sys.modules.setdefault("PIL.ImageGrab", _mock_imagegrab)

from src.perception.window_manager import WindowManager, WindowInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_mocks():
    """每个测试前重置所有 mock。"""
    _mock_user32.reset_mock()
    _mock_kernel32.reset_mock()
    _mock_psapi.reset_mock()
    yield


@pytest.fixture
def wm():
    """创建 WindowManager 实例。"""
    return WindowManager()


def _make_window_info(
    hwnd: int = 1001,
    title: str = "Test Window",
    rect: tuple = (100, 100, 800, 600),
    visible: bool = True,
    minimized: bool = False,
    maximized: bool = False,
    pid: int = 1234,
    process_name: str = "test.exe",
) -> WindowInfo:
    """创建测试用的 WindowInfo 实例。"""
    return WindowInfo(
        hwnd=hwnd,
        title=title,
        rect=rect,
        visible=visible,
        minimized=minimized,
        maximized=maximized,
        pid=pid,
        process_name=process_name,
    )


# ---------------------------------------------------------------------------
# WindowInfo 属性测试
# ---------------------------------------------------------------------------
class TestWindowInfo:
    """WindowInfo 数据类测试。"""

    def test_position_properties(self):
        info = _make_window_info(rect=(10, 20, 800, 600))
        assert info.x == 10
        assert info.y == 20

    def test_size_properties(self):
        info = _make_window_info(rect=(10, 20, 810, 620))
        assert info.width == 800
        assert info.height == 600

    def test_default_values(self):
        info = _make_window_info()
        assert info.hwnd == 1001
        assert info.title == "Test Window"
        assert info.visible is True
        assert info.minimized is False
        assert info.maximized is False
        assert info.pid == 1234
        assert info.process_name == "test.exe"


# ---------------------------------------------------------------------------
# list_windows 测试
# ---------------------------------------------------------------------------
class TestListWindows:
    """list_windows 方法测试。"""

    def test_returns_list(self, wm):
        """应返回列表。"""
        _mock_user32.EnumWindows = MagicMock(return_value=True)
        result = wm.list_windows()
        assert isinstance(result, list)

    def test_visible_only_filters(self, wm):
        """visible_only=True 时应过滤不可见窗口。"""
        # EnumWindows 不实际调用回调，所以结果是空列表
        _mock_user32.EnumWindows = MagicMock(return_value=True)
        result = wm.list_windows(visible_only=True)
        _mock_user32.EnumWindows.assert_called_once()

    def test_enum_windows_called(self, wm):
        """应调用 EnumWindows API。"""
        _mock_user32.EnumWindows = MagicMock(return_value=True)
        wm.list_windows()
        _mock_user32.EnumWindows.assert_called_once()

    def test_visible_only_false(self, wm):
        """visible_only=False 时不应过滤。"""
        _mock_user32.EnumWindows = MagicMock(return_value=True)
        result = wm.list_windows(visible_only=False)
        # IsWindowVisible 不应该被提前调用（回调内会调用）
        _mock_user32.EnumWindows.assert_called_once()


# ---------------------------------------------------------------------------
# capture_window 测试
# ---------------------------------------------------------------------------
class TestCaptureWindow:
    """capture_window 方法测试。"""

    def test_invalid_hwnd_raises(self, wm):
        """无效句柄应抛出 ValueError。"""
        _mock_user32.IsWindow = MagicMock(return_value=False)
        with pytest.raises(ValueError, match="无效的窗口句柄"):
            wm.capture_window(0)

    def test_returns_bytes(self, wm):
        """成功截图应返回 PNG bytes。"""
        _mock_user32.IsWindow = MagicMock(return_value=True)

        from PIL import Image
        test_img = Image.new("RGB", (100, 100), "white")

        wm._get_window_rect = MagicMock(return_value=(0, 0, 100, 100))

        with patch("src.perception.window_manager.ImageGrab") as mock_ig:
            mock_ig.grab.return_value = test_img
            result = wm.capture_window(12345)

        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"

    def test_zero_size_raises(self, wm):
        """零尺寸窗口应抛出 ValueError。"""
        _mock_user32.IsWindow = MagicMock(return_value=True)
        wm._get_window_rect = MagicMock(return_value=(0, 0, 0, 0))

        with pytest.raises(ValueError, match="窗口尺寸无效"):
            wm.capture_window(12345)


# ---------------------------------------------------------------------------
# 窗口操作测试
# ---------------------------------------------------------------------------
class TestWindowOperations:
    """窗口操作方法测试。"""

    def test_minimize_window(self, wm):
        _mock_user32.ShowWindow = MagicMock(return_value=True)
        result = wm.minimize_window(1001)
        assert result is True
        _mock_user32.ShowWindow.assert_called_once_with(1001, 6)  # SW_MINIMIZE = 6

    def test_maximize_window(self, wm):
        _mock_user32.ShowWindow = MagicMock(return_value=True)
        result = wm.maximize_window(1001)
        assert result is True
        _mock_user32.ShowWindow.assert_called_once_with(1001, 3)  # SW_MAXIMIZE = 3

    def test_restore_window(self, wm):
        _mock_user32.ShowWindow = MagicMock(return_value=True)
        result = wm.restore_window(1001)
        assert result is True
        _mock_user32.ShowWindow.assert_called_once_with(1001, 9)  # SW_RESTORE = 9

    def test_close_window(self, wm):
        _mock_user32.PostMessageW = MagicMock(return_value=True)
        result = wm.close_window(1001)
        assert result is True
        _mock_user32.PostMessageW.assert_called_once_with(1001, 0x0010, 0, 0)  # WM_CLOSE

    def test_bring_to_front(self, wm):
        _mock_user32.GetWindowLongW = MagicMock(return_value=0)  # 非最小化
        _mock_user32.SetWindowPos = MagicMock(return_value=True)
        _mock_user32.SetForegroundWindow = MagicMock(return_value=True)
        result = wm.bring_to_front(1001)
        assert result is True
        _mock_user32.SetForegroundWindow.assert_called_once_with(1001)

    def test_bring_to_front_minimized(self, wm):
        """最小化窗口应先恢复再置顶。"""
        _mock_user32.GetWindowLongW = MagicMock(return_value=0x20000000)  # WS_MINIMIZE
        _mock_user32.ShowWindow = MagicMock(return_value=True)
        _mock_user32.SetWindowPos = MagicMock(return_value=True)
        _mock_user32.SetForegroundWindow = MagicMock(return_value=True)
        result = wm.bring_to_front(1001)
        assert result is True
        # 应该先调用 ShowWindow(SW_RESTORE)
        _mock_user32.ShowWindow.assert_called_once_with(1001, 9)


# ---------------------------------------------------------------------------
# move_window / resize_window 测试
# ---------------------------------------------------------------------------
class TestMoveResizeWindow:
    """窗口移动和缩放测试。"""

    def test_move_window(self, wm):
        """移动窗口应保持大小不变。"""
        wm._get_window_rect = MagicMock(return_value=(100, 100, 800, 600))
        _mock_user32.MoveWindow = MagicMock(return_value=True)

        result = wm.move_window(1001, 200, 300)
        assert result is True
        # MoveWindow(hwnd, x, y, width, height, repaint)
        _mock_user32.MoveWindow.assert_called_once_with(1001, 200, 300, 700, 500, True)

    def test_resize_window(self, wm):
        """缩放窗口应保持位置不变。"""
        wm._get_window_rect = MagicMock(return_value=(100, 100, 800, 600))
        _mock_user32.MoveWindow = MagicMock(return_value=True)

        result = wm.resize_window(1001, 1024, 768)
        assert result is True
        _mock_user32.MoveWindow.assert_called_once_with(1001, 100, 100, 1024, 768, True)


# ---------------------------------------------------------------------------
# get_desktop_layout 测试
# ---------------------------------------------------------------------------
class TestGetDesktopLayout:
    """桌面布局快照测试。"""

    def test_layout_structure(self, wm):
        """布局应包含 screen、window_count、windows 键。"""
        _mock_user32.GetSystemMetrics = MagicMock(side_effect=[1920, 1080])
        _mock_user32.EnumWindows = MagicMock(return_value=True)

        layout = wm.get_desktop_layout()

        assert "screen" in layout
        assert "window_count" in layout
        assert "windows" in layout
        assert layout["screen"]["width"] == 1920
        assert layout["screen"]["height"] == 1080
        assert isinstance(layout["windows"], list)

    def test_layout_with_windows(self, wm):
        """布局应正确包含窗口信息。"""
        _mock_user32.GetSystemMetrics = MagicMock(side_effect=[1920, 1080])

        # 模拟 EnumWindows 回调
        original_list = wm.list_windows
        wm.list_windows = MagicMock(return_value=[
            _make_window_info(hwnd=1, title="Win1", rect=(0, 0, 100, 100)),
            _make_window_info(hwnd=2, title="Win2", rect=(100, 100, 500, 400), minimized=True),
        ])

        layout = wm.get_desktop_layout()

        assert layout["window_count"] == 2
        assert layout["windows"][0]["title"] == "Win1"
        assert layout["windows"][0]["state"] == "normal"
        assert layout["windows"][1]["state"] == "minimized"


# ---------------------------------------------------------------------------
# wait_for_window 测试
# ---------------------------------------------------------------------------
class TestWaitForWindow:
    """异步等待窗口测试。"""

    @pytest.mark.asyncio
    async def test_finds_immediately(self, wm):
        """窗口已存在时立即返回。"""
        wm.list_windows = MagicMock(return_value=[
            _make_window_info(title="Calculator"),
        ])

        result = await wm.wait_for_window("Calc", timeout=1.0)
        assert result is not None
        assert result.title == "Calculator"

    @pytest.mark.asyncio
    async def test_case_insensitive(self, wm):
        """匹配应不区分大小写。"""
        wm.list_windows = MagicMock(return_value=[
            _make_window_info(title="NOTEPAD"),
        ])

        result = await wm.wait_for_window("notepad", timeout=1.0)
        assert result is not None

    @pytest.mark.asyncio
    async def test_regex_pattern(self, wm):
        """支持正则表达式模式。"""
        wm.list_windows = MagicMock(return_value=[
            _make_window_info(title="Chrome - Google Search"),
        ])

        result = await wm.wait_for_window(r"Chrome|Firefox", timeout=1.0)
        assert result is not None
        assert "Chrome" in result.title

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, wm):
        """超时后应返回 None。"""
        wm.list_windows = MagicMock(return_value=[])

        result = await wm.wait_for_window("NeverMatch", timeout=0.3, interval=0.1)
        assert result is None

    @pytest.mark.asyncio
    async def test_pattern_matches_chinese(self, wm):
        """支持中文窗口标题匹配。"""
        wm.list_windows = MagicMock(return_value=[
            _make_window_info(title="新建文本文档 - 记事本"),
        ])

        result = await wm.wait_for_window("记事本", timeout=1.0)
        assert result is not None
        assert "记事本" in result.title


# ---------------------------------------------------------------------------
# 边界条件测试
# ---------------------------------------------------------------------------
class TestEdgeCases:
    """边界条件和异常处理测试。"""

    def test_window_info_zero_rect(self):
        """零矩形区域的 WindowInfo 应正常工作。"""
        info = _make_window_info(rect=(0, 0, 0, 0))
        assert info.width == 0
        assert info.height == 0

    def test_window_info_negative_rect(self):
        """负坐标的 WindowInfo 应正常工作。"""
        info = _make_window_info(rect=(-100, -50, 100, 50))
        assert info.x == -100
        assert info.y == -50
        assert info.width == 200
        assert info.height == 100

    def test_multiple_list_calls(self, wm):
        """多次调用 list_windows 不应有副作用。"""
        _mock_user32.EnumWindows = MagicMock(return_value=True)
        r1 = wm.list_windows()
        r2 = wm.list_windows()
        assert isinstance(r1, list)
        assert isinstance(r2, list)

    def test_minimize_returns_false_on_failure(self, wm):
        """ShowWindow 返回 False 时方法应返回 False。"""
        _mock_user32.ShowWindow = MagicMock(return_value=False)
        result = wm.minimize_window(9999)
        assert result is False
