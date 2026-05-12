# -*- coding: utf-8 -*-
"""开机自启管理 — 基于 Windows 注册表。

通过写入注册表实现开机自启。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("javas.daemon.autostart")

# 尝试导入 winreg（Windows 内置）
try:
    import winreg
    _WINREG_AVAILABLE = True
except ImportError:
    winreg = None  # type: ignore
    _WINREG_AVAILABLE = False

# 注册表路径和键名
_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_KEY_NAME = "JavasAgent"


def _get_command_line() -> str:
    """获取启动命令行字符串。"""
    python_exe = sys.executable
    if python_exe.endswith("python.exe"):
        pythonw = python_exe[:-10] + "pythonw.exe"
        if os.path.exists(pythonw):
            python_exe = pythonw

    import src.daemon.service as _svc
    service_dir = Path(_svc.__file__).parent
    entry_script = service_dir.parent / "main.py"

    return f'"{python_exe}" "{entry_script}" service --background'


class AutoStart:
    """开机自启管理器。"""

    @staticmethod
    def enable() -> None:
        """启用开机自启 — 写入注册表 Run 键。"""
        if not _WINREG_AVAILABLE:
            raise RuntimeError("开机自启仅支持 Windows")

        command = _get_command_line()
        logger.info("注册开机自启: %s", command)

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, _REG_KEY_NAME, 0, winreg.REG_SZ, command)
            logger.info("开机自启已启用")
        except OSError as exc:
            logger.error("写入注册表失败: %s", exc)
            raise

    @staticmethod
    def disable() -> None:
        """禁用开机自启 — 删除注册表 Run 键值。"""
        if not _WINREG_AVAILABLE:
            raise RuntimeError("开机自启仅支持 Windows")

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, _REG_KEY_NAME)
            logger.info("开机自启已禁用")
        except FileNotFoundError:
            logger.debug("注册表项不存在，视为已禁用")
        except OSError as exc:
            logger.error("删除注册表失败: %s", exc)
            raise

    @staticmethod
    def is_enabled() -> bool:
        """检查开机自启是否已启用。"""
        if not _WINREG_AVAILABLE:
            return False

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_READ
            ) as key:
                value, _ = winreg.QueryValueEx(key, _REG_KEY_NAME)
                return bool(value)
        except FileNotFoundError:
            return False
        except OSError:
            return False
