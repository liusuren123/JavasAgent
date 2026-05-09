"""Windows 平台适配器测试。

使用 mock 替代 pyautogui 和 win32gui，确保在无 GUI 环境下可运行。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCreatePlatformAdapter:
    """测试 create_platform_adapter 工厂函数。"""

    def test_windows_platform(self) -> None:
        """Windows 平台应返回 WindowsAdapter。"""
        with patch("src.platforms.platform") as mock_platform:
            mock_platform.system.return_value = "Windows"
            from src.platforms import create_platform_adapter
            from src.utils.config import AppConfig

            adapter = create_platform_adapter(AppConfig())
            assert adapter is not None
            assert hasattr(adapter, "screenshot")

    def test_unsupported_platform(self) -> None:
        """不支持的平台应返回 None。"""
        with patch("src.platforms.platform") as mock_platform:
            mock_platform.system.return_value = "Linux"
            from src.platforms import create_platform_adapter

            adapter = create_platform_adapter()
            assert adapter is None


class TestWindowsAdapter:
    """WindowsAdapter 测试。"""

    def _make_adapter(self):
        with patch("src.platforms.windows.pyautogui"):
            from src.platforms.windows import WindowsAdapter
            return WindowsAdapter(action_delay=0.1)

    def test_init_sets_failsafe(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter(action_delay=0.2)
            assert mock_pag.PAUSE == 0.2
            assert mock_pag.FAILSAFE is True

    @pytest.mark.asyncio
    async def test_screenshot(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            mock_img = MagicMock()
            mock_img.save = MagicMock()
            mock_pag.screenshot.return_value = mock_img

            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            result = await adapter.screenshot()
            mock_pag.screenshot.assert_called_once_with(region=None)
            mock_img.save.assert_called_once()
            assert isinstance(result, bytes)

    @pytest.mark.asyncio
    async def test_screenshot_with_region(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            mock_img = MagicMock()
            mock_img.save = MagicMock()
            mock_pag.screenshot.return_value = mock_img

            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.screenshot(region=(0, 0, 100, 100))
            mock_pag.screenshot.assert_called_once_with(region=(0, 0, 100, 100))

    @pytest.mark.asyncio
    async def test_click(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.click(100, 200, button="left", clicks=2)
            mock_pag.click.assert_called_once_with(x=100, y=200, button="left", clicks=2)

    @pytest.mark.asyncio
    async def test_type_text_ascii(self) -> None:
        """纯 ASCII 文本应使用 pyautogui.typewrite。"""
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.type_text("hello world", interval=0.01)
            mock_pag.typewrite.assert_called_once_with("hello world", interval=0.01)

    @pytest.mark.asyncio
    async def test_type_text_chinese_uses_clipboard(self) -> None:
        """中文文本应使用剪贴板粘贴方式（不调用 typewrite）。"""
        with patch("src.platforms.windows.pyautogui") as mock_pag, \
             patch("src.platforms.windows._paste_via_clipboard") as mock_paste:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.type_text("你好世界")
            mock_paste.assert_called_once_with("你好世界")
            mock_pag.typewrite.assert_not_called()

    @pytest.mark.asyncio
    async def test_type_text_mixed_uses_clipboard(self) -> None:
        """中英混合文本应使用剪贴板粘贴方式。"""
        with patch("src.platforms.windows.pyautogui") as mock_pag, \
             patch("src.platforms.windows._paste_via_clipboard") as mock_paste:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.type_text("Hello你好")
            mock_paste.assert_called_once_with("Hello你好")
            mock_pag.typewrite.assert_not_called()

    @pytest.mark.asyncio
    async def test_type_text_special_chars_uses_clipboard(self) -> None:
        """特殊 Unicode 字符应使用剪贴板粘贴方式。"""
        with patch("src.platforms.windows.pyautogui") as mock_pag, \
             patch("src.platforms.windows._paste_via_clipboard") as mock_paste:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.type_text("€¥£")
            mock_paste.assert_called_once_with("€¥£")
            mock_pag.typewrite.assert_not_called()

    @pytest.mark.asyncio
    async def test_has_non_ascii(self) -> None:
        """测试 _has_non_ascii 辅助函数。"""
        from src.platforms.windows import _has_non_ascii

        assert _has_non_ascii("你好") is True
        assert _has_non_ascii("hello") is False
        assert _has_non_ascii("Hello世界") is True
        assert _has_non_ascii("€") is True
        assert _has_non_ascii("") is False
        assert _has_non_ascii("abc123") is False

    @pytest.mark.asyncio
    async def test_press_key(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.press_key("enter")
            mock_pag.press.assert_called_once_with("enter")

    @pytest.mark.asyncio
    async def test_hotkey(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.hotkey("ctrl", "c")
            mock_pag.hotkey.assert_called_once_with("ctrl", "c")

    @pytest.mark.asyncio
    async def test_get_active_window_without_win32(self) -> None:
        with patch("src.platforms.windows.pyautogui"):
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            # win32gui import fails → fallback
            with patch.dict("sys.modules", {"win32gui": None, "win32process": None}):
                result = await adapter.get_active_window()
                assert "title" in result

    @pytest.mark.asyncio
    async def test_find_window_without_win32(self) -> None:
        with patch("src.platforms.windows.pyautogui"):
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            with patch.dict("sys.modules", {"win32gui": None}):
                result = await adapter.find_window("notepad")
                assert result == []

    @pytest.mark.asyncio
    async def test_activate_window_failure(self) -> None:
        with patch("src.platforms.windows.pyautogui"):
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            with patch.dict("sys.modules", {"win32gui": None}):
                result = await adapter.activate_window("12345")
                assert result is False

    @pytest.mark.asyncio
    async def test_scroll_down(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.scroll(clicks=3, direction="down")
            mock_pag.scroll.assert_called_once_with(-3)

    @pytest.mark.asyncio
    async def test_scroll_up(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.scroll(clicks=5, direction="up")
            mock_pag.scroll.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_move_to(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.move_to(500, 300, duration=0.2)
            mock_pag.moveTo.assert_called_once_with(500, 300, duration=0.2)

    @pytest.mark.asyncio
    async def test_drag_to(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.drag_to(100, 200, 300, 400, duration=0.5, button="left")
            mock_pag.moveTo.assert_called_once_with(100, 200)
            mock_pag.drag.assert_called_once_with(200, 200, duration=0.5, button="left")

    @pytest.mark.asyncio
    async def test_get_screen_size(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            mock_pag.size.return_value = MagicMock(width=1920, height=1080)
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            result = await adapter.get_screen_size()
            assert result == {"width": 1920, "height": 1080}
