# -*- coding: utf-8 -*-
"""TrayIcon 单元测试。"""

from unittest.mock import MagicMock, patch

import pytest

from src.daemon.tray_icon import TrayIcon, TrayStatus, _generate_icon_image, _STATUS_COLORS


class TestGenerateIconImage:
    """图标生成测试。"""

    def test_generates_image(self):
        img = _generate_icon_image((255, 0, 0), size=32)
        assert img.size == (32, 32)
        assert img.mode == "RGBA"

    def test_different_colors(self):
        for status, color in _STATUS_COLORS.items():
            img = _generate_icon_image(color)
            assert img.size == (64, 64)


class TestTrayIconInit:
    """TrayIcon.__init__ 测试。"""

    def test_callbacks_stored(self):
        quit_cb = MagicMock()
        chat_cb = MagicMock()
        voice_cb = MagicMock()
        settings_cb = MagicMock()

        tray = TrayIcon(
            on_quit=quit_cb,
            on_chat=chat_cb,
            on_voice_toggle=voice_cb,
            on_settings=settings_cb,
        )

        assert tray._on_quit is quit_cb
        assert tray._on_chat is chat_cb
        assert tray._on_voice_toggle is voice_cb
        assert tray._on_settings is settings_cb

    def test_default_tooltip(self):
        tray = TrayIcon()
        assert tray._tooltip == "JavasAgent"

    def test_custom_tooltip(self):
        tray = TrayIcon(tooltip="Custom")
        assert tray._tooltip == "Custom"

    def test_initial_status_active(self):
        tray = TrayIcon()
        assert tray.current_status == TrayStatus.ACTIVE


class TestTrayIconStatus:
    """update_status 测试。"""

    def test_status_changes(self):
        tray = TrayIcon()
        for status in TrayStatus:
            tray.update_status(status)
            assert tray.current_status == status

    def test_update_without_icon(self):
        """无 icon 实例时 update_status 不崩溃。"""
        tray = TrayIcon()
        tray.update_status(TrayStatus.ERROR)
        assert tray.current_status == TrayStatus.ERROR

    def test_set_tooltip(self):
        tray = TrayIcon()
        tray.set_tooltip("新提示")
        assert tray._tooltip == "新提示"


class TestTrayIconStartStop:
    """start / stop 测试。"""

    def test_start_without_pystray(self):
        """pystray 不可用时 start 不崩溃。"""
        tray = TrayIcon()
        with patch.dict("sys.modules", {"pystray": None}):
            tray.start()  # 应该优雅跳过

    def test_stop_when_not_started(self):
        tray = TrayIcon()
        tray.stop()  # 不报错

    def test_menu_callbacks(self):
        """菜单回调触发测试。"""
        quit_cb = MagicMock()
        chat_cb = MagicMock()
        voice_cb = MagicMock()
        settings_cb = MagicMock()

        tray = TrayIcon(
            on_quit=quit_cb,
            on_chat=chat_cb,
            on_voice_toggle=voice_cb,
            on_settings=settings_cb,
        )

        # 模拟菜单动作
        tray._on_chat_action(None, None)
        chat_cb.assert_called_once()

        tray._on_settings_action(None, None)
        settings_cb.assert_called_once()

        tray._on_voice_toggle_action(None, None)
        voice_cb.assert_called_once()
        assert tray._voice_enabled is False  # 切换

        tray._on_quit_action(None, None)
        quit_cb.assert_called_once()
