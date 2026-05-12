# -*- coding: utf-8 -*-
"""HotkeyManager 单元测试。"""

from unittest.mock import MagicMock, patch

import pytest

from src.daemon.hotkey_manager import HotkeyManager, DEFAULT_HOTKEYS


class TestHotkeyManagerInit:
    """初始化测试。"""

    def test_initial_state(self):
        hm = HotkeyManager()
        assert hm.is_active is False
        assert len(hm._hotkeys) == 0

    def test_keyboard_not_available(self):
        """keyboard 不可用时 is_available 为 False。"""
        with patch.dict("sys.modules", {"keyboard": None}):
            hm = HotkeyManager()
            assert hm.is_available is False


class TestRegisterUnregister:
    """注册 / 取消注册测试。"""

    def test_register_stores_callback(self):
        hm = HotkeyManager()
        cb = lambda: None
        hm.register("ctrl+alt+j", cb)
        assert "ctrl+alt+j" in hm._hotkeys
        assert hm._hotkeys["ctrl+alt+j"] is cb

    def test_register_normalizes_combo(self):
        hm = HotkeyManager()
        hm.register("Ctrl + Alt + J", lambda: None)
        assert "ctrl+alt+j" in hm._hotkeys

    def test_register_multiple(self):
        hm = HotkeyManager()
        hm.register("ctrl+alt+j", lambda: None)
        hm.register("ctrl+alt+v", lambda: None)
        hm.register("ctrl+alt+s", lambda: None)
        assert len(hm._hotkeys) == 3

    def test_unregister_removes(self):
        hm = HotkeyManager()
        hm.register("ctrl+alt+j", lambda: None)
        hm.unregister("ctrl+alt+j")
        assert "ctrl+alt+j" not in hm._hotkeys

    def test_unregister_nonexistent(self):
        hm = HotkeyManager()
        hm.unregister("nonexistent")  # 不报错

    def test_overwrite_registration(self):
        hm = HotkeyManager()
        cb1 = lambda: "first"
        cb2 = lambda: "second"
        hm.register("ctrl+alt+j", cb1)
        hm.register("ctrl+alt+j", cb2)
        assert hm._hotkeys["ctrl+alt+j"] is cb2


class TestNormalizeCombo:
    """_normalize_combo 测试。"""

    def test_lowercase(self):
        assert HotkeyManager._normalize_combo("Ctrl+Alt+J") == "ctrl+alt+j"

    def test_strip_spaces(self):
        assert HotkeyManager._normalize_combo("Ctrl + Alt + J") == "ctrl+alt+j"

    def test_single_key(self):
        assert HotkeyManager._normalize_combo("F12") == "f12"

    def test_mixed_case(self):
        assert HotkeyManager._normalize_combo("CTRL+shift+ESC") == "ctrl+shift+esc"


class TestStartStop:
    """start / stop 测试。"""

    def test_start_without_keyboard(self):
        """keyboard 不可用时 start 优雅跳过。"""
        hm = HotkeyManager()
        hm._keyboard_available = False
        hm.register("ctrl+alt+j", lambda: None)
        hm.start()
        assert hm.is_active is False

    def test_stop_when_not_active(self):
        hm = HotkeyManager()
        hm.stop()  # 不报错
        assert hm.is_active is False

    def test_start_idempotent(self):
        hm = HotkeyManager()
        hm._active = True
        hm.start()  # 重复调用不报错
        assert hm.is_active is True

    def test_get_registered_hotkeys(self):
        hm = HotkeyManager()
        hm.register("ctrl+alt+j", lambda: None)
        result = hm.get_registered_hotkeys()
        assert "ctrl+alt+j" in result
