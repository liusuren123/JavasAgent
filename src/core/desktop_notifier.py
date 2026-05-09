"""Windows 桌面通知发送器。

作为 NotificationManager 的内置通知渠道，支持：
- Windows 10/11 原生 Toast 通知（winotify）
- 按通知级别播放系统声音
- 非 Windows 平台 graceful 降级
"""

from __future__ import annotations

import sys
import threading
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from src.core.notification import Notification, NotificationLevel


class DesktopNotifier:
    """Windows 桌面通知发送器。

    使用 winotify 发送 Windows 10/11 原生 Toast 通知，
    并根据通知级别播放系统声音。

    在非 Windows 平台上自动 graceful 降级（仅记录日志）。

    Args:
        config: 配置字典，支持以下键：
            - enabled: 是否启用桌面通知，默认 True
            - sound_enabled: 是否启用声音，默认 True
            - toast_duration: Toast 显示秒数，默认 5
    """

    __name__ = "DesktopNotifier"  # 供 NotificationManager.register_handler 日志使用

    # 声音级别映射：NotificationLevel -> winsound 常量名
    _SOUND_MAP: dict[str, int | None] = {
        "info": None,  # INFO 级别无声音
        "warning": 0x00000040,  # MB_ICONEXCLAMATION
        "urgent": 0x00000010,  # MB_ICONHAND
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._enabled: bool = self._config.get("enabled", True)
        self._sound_enabled: bool = self._config.get("sound_enabled", True)
        self._toast_duration: int = self._config.get("toast_duration", 5)

        self._platform_windows = sys.platform == "win32"
        self._winotify_available = False
        self._winsound_available = False

        # 检测 winotify 可用性
        if self._platform_windows:
            try:
                import winotify  # noqa: F401

                self._winotify_available = True
                logger.debug("winotify 可用，Toast 通知已启用")
            except ImportError:
                logger.warning("winotify 未安装，Toast 通知不可用（pip install winotify）")

            try:
                import winsound  # noqa: F401

                self._winsound_available = True
            except ImportError:
                logger.warning("winsound 不可用，通知声音已禁用")

        if not self._platform_windows:
            logger.info(f"当前平台 {sys.platform!r} 不支持原生桌面通知，已降级为日志模式")

        if not self._winotify_available:
            logger.info("Toast 通知不可用，桌面通知降级为日志模式")

    @property
    def enabled(self) -> bool:
        """是否启用桌面通知。"""
        return self._enabled

    @property
    def is_toast_available(self) -> bool:
        """Toast 通知是否可用（需要 Windows + winotify）。"""
        return self._platform_windows and self._winotify_available

    @property
    def is_sound_available(self) -> bool:
        """声音是否可用（需要 Windows + winsound）。"""
        return self._platform_windows and self._winsound_available

    async def __call__(self, notification: Notification) -> None:
        """作为 NotificationManager handler 被调用。

        Args:
            notification: 通知对象
        """
        if not self._enabled:
            logger.debug(f"桌面通知已禁用，跳过: {notification.title}")
            return

        # 在后台线程中发送，避免阻塞事件循环
        thread = threading.Thread(
            target=self._dispatch_sync,
            args=(notification,),
            daemon=True,
        )
        thread.start()

    def _dispatch_sync(self, notification: Notification) -> None:
        """同步执行通知分发（在后台线程中运行）。"""
        try:
            self._send_toast(notification)
            self._play_sound(notification.level)
        except Exception as e:
            logger.error(f"桌面通知发送失败: {e}")

    def _send_toast(self, notification: Notification) -> None:
        """发送 Windows Toast 通知。

        使用 winotify 构建并显示原生 Toast 通知。
        如果 winotify 不可用则 fallback 到日志输出。

        Args:
            notification: 通知对象
        """
        if not self.is_toast_available:
            logger.info(
                f"[桌面通知] [{notification.level.value.upper()}] "
                f"{notification.title}: {notification.message}"
            )
            return

        try:
            from winotify import Notification as WinotifyNotification, audio

            # 根据级别选择图标
            level_icon = self._get_level_icon(notification.level)

            toast = WinotifyNotification(
                app_id="JavasAgent",
                title=notification.title,
                msg=notification.message,
                duration=f"short" if self._toast_duration <= 5 else "long",
                icon=level_icon,
            )

            # 设置声音（winotify 内置声音）
            if self._sound_enabled and notification.level != "info":
                try:
                    toast.set_audio(audio.Default, loop=False)
                except Exception:
                    pass  # 声音设置失败不影响通知

            # 支持点击回调：如果 metadata 中有 url，设置点击动作
            url = notification.metadata.get("url")
            action = notification.metadata.get("action")
            if url:
                toast.add_actions(
                    actions=[("打开链接", url)],
                )
            elif action:
                toast.add_actions(
                    actions=[("执行动作", action)],
                )

            toast.show()
            logger.debug(f"Toast 通知已发送: {notification.title}")

        except Exception as e:
            logger.warning(f"Toast 通知发送失败，fallback 到日志: {e}")
            logger.info(
                f"[桌面通知] [{notification.level.value.upper()}] "
                f"{notification.title}: {notification.message}"
            )

    def _play_sound(self, level: NotificationLevel) -> None:
        """根据通知级别播放系统声音。

        - INFO: 无声音
        - WARNING: 系统提示音 (MB_ICONEXCLAMATION)
        - URGENT: 系统警告音 (MB_ICONHAND)

        Args:
            level: 通知级别
        """
        if not self._sound_enabled:
            return

        if not self.is_sound_available:
            return

        sound_type = self._SOUND_MAP.get(level.value)
        if sound_type is None:
            return  # INFO 级别无声音

        try:
            import winsound

            winsound.MessageBeep(sound_type)
            logger.debug(f"已播放 {level.value} 级别提示音")
        except Exception as e:
            logger.warning(f"播放提示音失败: {e}")

    @staticmethod
    def _get_level_icon(level: NotificationLevel) -> str | None:
        """获取通知级别对应的图标路径。

        使用 Windows 系统内置图标。

        Args:
            level: 通知级别

        Returns:
            图标文件路径，或 None
        """
        # winotify 可以不指定 icon，使用默认图标
        # 也可以使用系统图标路径，但不同 Windows 版本路径不同
        # 简单起见，URGENT/WARNING 不设置 icon（依赖标题传达紧急程度）
        return None
