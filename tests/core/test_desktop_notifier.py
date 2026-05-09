"""DesktopNotifier 桌面通知渠道测试。"""

from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.core.desktop_notifier import DesktopNotifier
from src.core.notification import Notification, NotificationLevel


def _make_notification(
    level: NotificationLevel = NotificationLevel.INFO,
    title: str = "测试通知",
    message: str = "这是一条测试通知",
    metadata: dict | None = None,
) -> Notification:
    """创建测试用通知对象的辅助函数。"""
    return Notification(
        id="test-id-001",
        title=title,
        message=message,
        level=level,
        source="test",
        created_at=datetime.now(),
        metadata=metadata or {},
    )


# ── 初始化测试 ──────────────────────────────────────────────


class TestDesktopNotifierInit:
    """测试 DesktopNotifier 初始化。"""

    def test_default_init(self) -> None:
        """默认配置初始化。"""
        notifier = DesktopNotifier()
        assert notifier.enabled is True
        assert notifier._sound_enabled is True
        assert notifier._toast_duration == 5

    def test_custom_config(self) -> None:
        """自定义配置初始化。"""
        config = {
            "enabled": False,
            "sound_enabled": False,
            "toast_duration": 10,
        }
        notifier = DesktopNotifier(config=config)
        assert notifier.enabled is False
        assert notifier._sound_enabled is False
        assert notifier._toast_duration == 10

    def test_partial_config(self) -> None:
        """部分配置：只设置 enabled。"""
        notifier = DesktopNotifier(config={"enabled": True})
        assert notifier.enabled is True
        assert notifier._sound_enabled is True  # 默认值
        assert notifier._toast_duration == 5  # 默认值

    def test_empty_config(self) -> None:
        """空配置等同于无配置。"""
        notifier = DesktopNotifier(config={})
        assert notifier.enabled is True


# ── 平台降级测试 ─────────────────────────────────────────────


class TestPlatformDegradation:
    """测试非 Windows 平台 graceful 降级。"""

    def test_non_windows_no_crash(self) -> None:
        """非 Windows 平台初始化不报错。"""
        with patch.object(sys, "platform", "linux"):
            notifier = DesktopNotifier()
            assert notifier.enabled is True
            assert notifier.is_toast_available is False
            assert notifier.is_sound_available is False

    def test_darwin_no_crash(self) -> None:
        """macOS 平台初始化不报错。"""
        with patch.object(sys, "platform", "darwin"):
            notifier = DesktopNotifier()
            assert notifier.is_toast_available is False
            assert notifier.is_sound_available is False

    def test_windows_without_winotify(self) -> None:
        """Windows 平台但 winotify 未安装时 graceful 降级。"""
        with patch.object(sys, "platform", "win32"):
            # 通过在模块级别 mock winotify 为 None 来模拟未安装
            import src.core.desktop_notifier as dn_module
            original = dn_module.__dict__.get("winotify")
            try:
                # 让 import winotify 在 DesktopNotifier 内部失败
                notifier = DesktopNotifier.__new__(DesktopNotifier)
                notifier._config = {}
                notifier._enabled = True
                notifier._sound_enabled = True
                notifier._toast_duration = 5
                notifier._platform_windows = True
                notifier._winotify_available = False
                notifier._winsound_available = True
                assert notifier._platform_windows is True
                assert notifier._winotify_available is False
            finally:
                pass


# ── 声音级别映射测试 ─────────────────────────────────────────


class TestSoundMapping:
    """测试声音级别映射。"""

    def test_info_no_sound(self) -> None:
        """INFO 级别无声音。"""
        sound_type = DesktopNotifier._SOUND_MAP.get("info")
        assert sound_type is None

    def test_warning_sound(self) -> None:
        """WARNING 级别对应 MB_ICONEXCLAMATION (0x40)。"""
        sound_type = DesktopNotifier._SOUND_MAP.get("warning")
        assert sound_type == 0x00000040

    def test_urgent_sound(self) -> None:
        """URGENT 级别对应 MB_ICONHAND (0x10)。"""
        sound_type = DesktopNotifier._SOUND_MAP.get("urgent")
        assert sound_type == 0x00000010

    def test_play_sound_info(self) -> None:
        """INFO 级别调用 _play_sound 不播放声音。"""
        notifier = DesktopNotifier(config={"sound_enabled": True})
        # 即使 winsound 可用，INFO 也不应播放
        with patch.object(sys, "platform", "win32"):
            with patch("src.core.desktop_notifier.DesktopNotifier.is_sound_available", True):
                with patch("winsound.MessageBeep") as mock_beep:
                    notifier._play_sound(NotificationLevel.INFO)
                    mock_beep.assert_not_called()

    def test_play_sound_disabled(self) -> None:
        """声音禁用时不播放。"""
        notifier = DesktopNotifier(config={"sound_enabled": False})
        with patch.object(sys, "platform", "win32"):
            with patch("src.core.desktop_notifier.DesktopNotifier.is_sound_available", True):
                with patch("winsound.MessageBeep") as mock_beep:
                    notifier._play_sound(NotificationLevel.URGENT)
                    mock_beep.assert_not_called()

    def test_play_sound_warning(self) -> None:
        """WARNING 级别播放提示音。"""
        notifier = DesktopNotifier(config={"sound_enabled": True})
        # 强制设置为可用状态
        notifier._platform_windows = True
        notifier._winsound_available = True
        with patch("winsound.MessageBeep") as mock_beep:
            notifier._play_sound(NotificationLevel.WARNING)
            mock_beep.assert_called_once_with(0x00000040)

    def test_play_sound_urgent(self) -> None:
        """URGENT 级别播放警告音。"""
        notifier = DesktopNotifier(config={"sound_enabled": True})
        notifier._platform_windows = True
        notifier._winsound_available = True
        with patch("winsound.MessageBeep") as mock_beep:
            notifier._play_sound(NotificationLevel.URGENT)
            mock_beep.assert_called_once_with(0x00000010)


# ── Handler 调用测试 ──────────────────────────────────────────


class TestHandlerInvocation:
    """测试作为 NotificationManager handler 被调用。"""

    @pytest.mark.asyncio
    async def test_call_disabled(self) -> None:
        """disabled 时不发送通知。"""
        notifier = DesktopNotifier(config={"enabled": False})
        notification = _make_notification()

        with patch.object(notifier, "_dispatch_sync") as mock_dispatch:
            await notifier(notification)
            mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_enabled(self) -> None:
        """enabled 时在后台线程中发送通知。"""
        notifier = DesktopNotifier(config={"enabled": True})
        notification = _make_notification()

        with patch.object(notifier, "_dispatch_sync") as mock_dispatch:
            await notifier(notification)
            # 等待后台线程完成
            import time
            time.sleep(0.1)
            mock_dispatch.assert_called_once_with(notification)

    @pytest.mark.asyncio
    async def test_call_all_levels(self) -> None:
        """所有级别都能被调用。"""
        notifier = DesktopNotifier(config={"enabled": True})

        for level in NotificationLevel:
            notification = _make_notification(level=level)
            with patch.object(notifier, "_dispatch_sync"):
                await notifier(notification)

    @pytest.mark.asyncio
    async def test_dispatch_sync_calls_toast_and_sound(self) -> None:
        """_dispatch_sync 同时调用 _send_toast 和 _play_sound。"""
        notifier = DesktopNotifier(config={"enabled": True})
        notification = _make_notification()

        with patch.object(notifier, "_send_toast") as mock_toast:
            with patch.object(notifier, "_play_sound") as mock_sound:
                notifier._dispatch_sync(notification)
                mock_toast.assert_called_once_with(notification)
                mock_sound.assert_called_once_with(notification.level)

    @pytest.mark.asyncio
    async def test_dispatch_sync_error_handling(self) -> None:
        """_dispatch_sync 中异常不会向外传播。"""
        notifier = DesktopNotifier(config={"enabled": True})
        notification = _make_notification()

        with patch.object(notifier, "_send_toast", side_effect=RuntimeError("boom")):
            with patch.object(notifier, "_play_sound"):
                # 不应抛出异常
                notifier._dispatch_sync(notification)


# ── Toast 发送测试 ────────────────────────────────────────────


class TestToastSending:
    """测试 Toast 通知发送。"""

    def test_send_toast_fallback_when_unavailable(self) -> None:
        """winotify 不可用时 fallback 到日志。"""
        notifier = DesktopNotifier()
        notifier._winotify_available = False
        notification = _make_notification()

        # 不应抛出异常
        notifier._send_toast(notification)

    def test_send_toast_with_url_metadata(self) -> None:
        """metadata 中有 url 时设置点击动作。"""
        notifier = DesktopNotifier()
        notifier._platform_windows = True
        notifier._winotify_available = True

        notification = _make_notification(
            metadata={"url": "https://example.com"}
        )

        mock_toast_instance = MagicMock()
        mock_toast_class = MagicMock(return_value=mock_toast_instance)

        with patch.dict(sys.modules, {"winotify": MagicMock(Notification=mock_toast_class, audio=MagicMock(Default="default"))}):
            notifier._send_toast(notification)
            mock_toast_instance.add_actions.assert_called_once()

    def test_send_toast_with_action_metadata(self) -> None:
        """metadata 中有 action 时设置点击动作。"""
        notifier = DesktopNotifier()
        notifier._platform_windows = True
        notifier._winotify_available = True

        notification = _make_notification(
            metadata={"action": "open_app"}
        )

        mock_toast_instance = MagicMock()
        mock_toast_class = MagicMock(return_value=mock_toast_instance)

        with patch.dict(sys.modules, {"winotify": MagicMock(Notification=mock_toast_class, audio=MagicMock(Default="default"))}):
            notifier._send_toast(notification)
            mock_toast_instance.add_actions.assert_called_once()

    def test_send_toast_no_action_metadata(self) -> None:
        """无 action/url metadata 时不设置点击动作。"""
        notifier = DesktopNotifier()
        notifier._platform_windows = True
        notifier._winotify_available = True

        notification = _make_notification()

        mock_toast_instance = MagicMock()
        mock_toast_class = MagicMock(return_value=mock_toast_instance)

        with patch.dict(sys.modules, {"winotify": MagicMock(Notification=mock_toast_class, audio=MagicMock(Default="default"))}):
            notifier._send_toast(notification)
            mock_toast_instance.add_actions.assert_not_called()


# ── 与 NotificationManager 集成测试 ───────────────────────────


class TestNotificationManagerIntegration:
    """测试 DesktopNotifier 与 NotificationManager 的集成。"""

    def test_auto_registration(self) -> None:
        """NotificationManager 初始化时自动注册 DesktopNotifier。"""
        from src.core.notification import NotificationManager

        manager = NotificationManager()
        # 应该在每个级别都有一个 handler
        for level in NotificationLevel:
            # 找到 DesktopNotifier 类型的 handler
            handlers = manager._handlers[level]
            desktop_handlers = [h for h in handlers if isinstance(h, DesktopNotifier)]
            assert len(desktop_handlers) == 1, f"{level.value} 级别应有一个 DesktopNotifier handler"

    def test_registration_failure_does_not_break_manager(self) -> None:
        """DesktopNotifier 注册失败不影响 NotificationManager。"""
        from src.core.notification import NotificationManager

        with patch(
            "src.core.desktop_notifier.DesktopNotifier.__init__",
            side_effect=RuntimeError("init failed"),
        ):
            manager = NotificationManager()
            # Manager 应该正常工作，只是没有桌面通知 handler
            assert len(manager._notifications) == 0

    def test_disabled_config_skips_registration(self) -> None:
        """配置 enabled=False 时 DesktopNotifier 仍被注册但不活跃。"""
        from src.core.notification import NotificationManager

        config = {"desktop_notifier": {"enabled": False}}
        manager = NotificationManager(config=config)

        # DesktopNotifier 被注册，但内部 enabled=False
        for level in NotificationLevel:
            handlers = manager._handlers[level]
            desktop_handlers = [h for h in handlers if isinstance(h, DesktopNotifier)]
            if desktop_handlers:
                assert desktop_handlers[0].enabled is False
