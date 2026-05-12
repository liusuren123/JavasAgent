# -*- coding: utf-8 -*-
"""全局热键管理器 — 基于 keyboard 库。

注册系统级快捷键，无论焦点在哪个应用都能响应。
当 keyboard 库不可用时（如无管理员权限），优雅降级为空操作。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger("javas.daemon.hotkey")

# 默认热键组合
DEFAULT_HOTKEYS = {
    "chat": "ctrl+alt+j",
    "voice_toggle": "ctrl+alt+v",
    "stop_task": "ctrl+alt+s",
}


class HotkeyManager:
    """全局热键管理器。

    用法:
        hm = HotkeyManager()
        hm.register("ctrl+alt+j", lambda: print("chat"))
        hm.start()
        ...
        hm.stop()
    """

    def __init__(self) -> None:
        self._hotkeys: dict[str, Callable] = {}
        self._registered: dict[str, Any] = {}  # keyboard 返回的 hook 对象
        self._active = False
        self._keyboard_available = False

        # 检测 keyboard 库是否可用
        try:
            import keyboard  # noqa: F401
            self._keyboard_available = True
        except ImportError:
            logger.warning("keyboard 库未安装，全局热键不可用")
        except Exception as exc:
            logger.warning("keyboard 库初始化失败（可能缺少管理员权限）: %s", exc)

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_available(self) -> bool:
        return self._keyboard_available

    # ------------------------------------------------------------------
    # 注册 / 取消注册
    # ------------------------------------------------------------------
    def register(self, key_combo: str, callback: Callable) -> None:
        """注册快捷键和回调。

        Args:
            key_combo: 快捷键组合，如 "ctrl+alt+j"
            callback: 按下时的回调函数
        """
        normalized = self._normalize_combo(key_combo)
        self._hotkeys[normalized] = callback
        logger.debug("注册热键: %s -> %s", normalized, callback.__name__ if hasattr(callback, '__name__') else 'callback')

    def unregister(self, key_combo: str) -> None:
        """取消注册快捷键。"""
        normalized = self._normalize_combo(key_combo)
        if normalized in self._hotkeys:
            del self._hotkeys[normalized]
        # 如果正在运行，也移除已注册的 hook
        if normalized in self._registered:
            try:
                import keyboard
                keyboard.remove_hotkey(self._registered[normalized])
            except Exception:
                pass
            del self._registered[normalized]

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------
    def start(self) -> None:
        """开始监听所有已注册的热键。"""
        if self._active:
            return

        if not self._keyboard_available:
            logger.warning("keyboard 库不可用，热键监听已跳过")
            return

        try:
            import keyboard
        except Exception as exc:
            logger.error("无法导入 keyboard: %s", exc)
            return

        self._active = True

        for combo, callback in self._hotkeys.items():
            try:
                hook = keyboard.add_hotkey(combo, callback, suppress=False)
                self._registered[combo] = hook
                logger.info("热键已注册: %s", combo)
            except Exception as exc:
                logger.error("热键 '%s' 注册失败: %s", combo, exc)

        logger.info("全局热键监听已启动 (%d 个热键)", len(self._registered))

    def stop(self) -> None:
        """停止监听所有热键。"""
        if not self._active:
            return

        try:
            import keyboard
            keyboard.unhook_all()
        except Exception as exc:
            logger.debug("keyboard unhook_all 异常: %s", exc)

        self._registered.clear()
        self._active = False
        logger.info("全局热键监听已停止")

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_combo(combo: str) -> str:
        """规范化快捷键字符串（小写，去空格）。"""
        return "+".join(part.strip().lower() for part in combo.split("+"))

    def get_registered_hotkeys(self) -> dict[str, str]:
        """获取已注册热键列表（用于状态展示）。"""
        return {combo: cb.__name__ if hasattr(cb, '__name__') else 'callback'
                for combo, cb in self._hotkeys.items()}
