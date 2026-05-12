# -*- coding: utf-8 -*-
"""AutoStart 单元测试。

关键：winreg 是 Python 内置 C 扩展模块，不能用 patch("winreg") 直接 mock。
正确做法：用 patch("src.daemon.autostart.winreg.SetValueEx") 等 mock 模块中的函数。
对于 _WINREG_AVAILABLE 标志，用 patch.object 或直接 patch 属性。
"""

from unittest.mock import MagicMock, patch

import pytest

from src.daemon.autostart import AutoStart, _REG_KEY_NAME, _REG_PATH


# ---------------------------------------------------------------------------
# 辅助：创建 mock winreg 模块
# ---------------------------------------------------------------------------
def _make_mock_winreg():
    """创建一个模拟 winreg 模块的对象。"""
    mock = MagicMock()
    mock.HKEY_CURRENT_USER = 0x80000001
    mock.KEY_SET_VALUE = 0x0002
    mock.KEY_READ = 0x20019
    mock.REG_SZ = 1
    return mock


class TestAutoStartEnable:
    """AutoStart.enable() 测试。"""

    @patch("src.daemon.autostart._get_command_line", return_value='"pythonw" "main.py" service --background')
    @patch("src.daemon.autostart.winreg")
    def test_enable_writes_registry(self, mock_winreg, mock_cmd):
        """enable() 应写入注册表。"""
        mock_key = MagicMock()
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_SET_VALUE = 0x0002
        mock_winreg.REG_SZ = 1
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)

        AutoStart.enable()

        mock_winreg.OpenKey.assert_called_once_with(
            0x80000001, _REG_PATH, 0, 0x0002
        )
        mock_winreg.SetValueEx.assert_called_once_with(
            mock_key, _REG_KEY_NAME, 0, 1, '"pythonw" "main.py" service --background'
        )

    @patch("src.daemon.autostart._WINREG_AVAILABLE", False)
    def test_enable_without_winreg(self):
        """winreg 不可用时抛 RuntimeError。"""
        with pytest.raises(RuntimeError, match="仅支持 Windows"):
            AutoStart.enable()

    @patch("src.daemon.autostart._get_command_line", return_value="test_cmd")
    @patch("src.daemon.autostart.winreg")
    def test_enable_registry_error(self, mock_winreg, mock_cmd):
        """注册表写入失败时抛 OSError。"""
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_SET_VALUE = 0x0002
        mock_winreg.OpenKey.side_effect = OSError("access denied")

        with pytest.raises(OSError):
            AutoStart.enable()


class TestAutoStartDisable:
    """AutoStart.disable() 测试。"""

    @patch("src.daemon.autostart.winreg")
    def test_disable_deletes_registry(self, mock_winreg):
        """disable() 应删除注册表值。"""
        mock_key = MagicMock()
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_SET_VALUE = 0x0002
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)

        AutoStart.disable()

        mock_winreg.DeleteValue.assert_called_once_with(mock_key, _REG_KEY_NAME)

    @patch("src.daemon.autostart.winreg")
    def test_disable_not_found_is_ok(self, mock_winreg):
        """注册表项不存在时视为已禁用，不报错。"""
        mock_key = MagicMock()
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_SET_VALUE = 0x0002
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.DeleteValue.side_effect = FileNotFoundError()

        AutoStart.disable()  # 不报错

    @patch("src.daemon.autostart._WINREG_AVAILABLE", False)
    def test_disable_without_winreg(self):
        """winreg 不可用时抛 RuntimeError。"""
        with pytest.raises(RuntimeError, match="仅支持 Windows"):
            AutoStart.disable()


class TestAutoStartIsEnabled:
    """AutoStart.is_enabled() 测试。"""

    @patch("src.daemon.autostart.winreg")
    def test_enabled(self, mock_winreg):
        """注册表有值 → True。"""
        mock_key = MagicMock()
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_READ = 0x20019
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.QueryValueEx.return_value = ("some_command", 1)

        assert AutoStart.is_enabled() is True

    @patch("src.daemon.autostart.winreg")
    def test_not_enabled(self, mock_winreg):
        """注册表无值 → False。"""
        mock_key = MagicMock()
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_READ = 0x20019
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.QueryValueEx.side_effect = FileNotFoundError()

        assert AutoStart.is_enabled() is False

    @patch("src.daemon.autostart.winreg")
    def test_empty_value_is_disabled(self, mock_winreg):
        """空值视为未启用。"""
        mock_key = MagicMock()
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_READ = 0x20019
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.QueryValueEx.return_value = ("", 1)

        assert AutoStart.is_enabled() is False

    @patch("src.daemon.autostart._WINREG_AVAILABLE", False)
    def test_without_winreg(self):
        """winreg 不可用时返回 False。"""
        assert AutoStart.is_enabled() is False


class TestRegistryConstants:
    """注册表路径和键名验证。"""

    def test_reg_path(self):
        assert _REG_PATH == r"Software\Microsoft\Windows\CurrentVersion\Run"

    def test_reg_key_name(self):
        assert _REG_KEY_NAME == "JavasAgent"
