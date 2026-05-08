"""Windows 平台适配器测试。

使用 mock 替代 pyautogui 和 win32gui，确保在无 GUI 环境下可运行。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
    async def test_type_text(self) -> None:
        with patch("src.platforms.windows.pyautogui") as mock_pag:
            from src.platforms.windows import WindowsAdapter
            adapter = WindowsAdapter()

            await adapter.type_text("hello world", interval=0.01)
            mock_pag.typewrite.assert_called_once_with("hello world", interval=0.01)

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
