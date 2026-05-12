# -*- coding: utf-8 -*-
"""系统托盘图标 — 基于 pystray。

在系统托盘显示 JavasAgent 状态图标，右键菜单提供快捷操作。
图标用 Pillow 动态生成纯色圆形 PNG，无需外部图标文件。
"""

from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger("javas.daemon.tray")


class TrayStatus(Enum):
    """托盘图标状态（对应不同颜色）。"""
    ACTIVE = "active"        # 绿色 — 正常运行
    PROCESSING = "processing"  # 黄色 — 处理任务中
    ERROR = "error"          # 红色 — 出错
    PAUSED = "paused"        # 灰色 — 已暂停


# 状态 → RGB 颜色映射
_STATUS_COLORS: dict[TrayStatus, tuple[int, int, int]] = {
    TrayStatus.ACTIVE: (76, 175, 80),       # 绿色
    TrayStatus.PROCESSING: (255, 193, 7),    # 黄色
    TrayStatus.ERROR: (244, 67, 54),         # 红色
    TrayStatus.PAUSED: (158, 158, 158),     # 灰色
}


def _generate_icon_image(color: tuple[int, int, int], size: int = 64) -> "PIL.Image.Image":
    """用 Pillow 生成纯色圆形图标。"""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(*color, 255),
    )
    return img


class TrayIcon:
    """系统托盘图标管理器。

    用法:
        tray = TrayIcon(
            on_quit=handle_quit,
            on_chat=handle_chat,
            on_voice_toggle=handle_voice_toggle,
            on_settings=handle_settings,
        )
        tray.start()
        ...
        tray.update_status(TrayStatus.ACTIVE)
        ...
        tray.stop()
    """

    def __init__(
        self,
        on_quit: Optional[Callable] = None,
        on_chat: Optional[Callable] = None,
        on_voice_toggle: Optional[Callable] = None,
        on_settings: Optional[Callable] = None,
        tooltip: str = "JavasAgent",
    ) -> None:
        self._on_quit = on_quit
        self._on_chat = on_chat
        self._on_voice_toggle = on_voice_toggle
        self._on_settings = on_settings
        self._tooltip = tooltip

        self._icon: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None
        self._current_status = TrayStatus.ACTIVE
        self._voice_enabled = True

    @property
    def current_status(self) -> TrayStatus:
        return self._current_status

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------
    def start(self) -> None:
        """在独立线程中启动托盘图标。"""
        if self._icon is not None:
            return

        try:
            import pystray
        except ImportError:
            logger.warning("pystray 未安装，托盘图标不可用")
            return

        self._icon = pystray.Icon(
            name="JavasAgent",
            icon=_generate_icon_image(_STATUS_COLORS[TrayStatus.ACTIVE]),
            title=self._tooltip,
            menu=self._create_menu(),
        )

        self._thread = threading.Thread(
            target=self._icon.run, name="tray-icon", daemon=True
        )
        self._thread.start()
        logger.info("系统托盘图标已启动")

    def stop(self) -> None:
        """停止托盘图标。"""
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception as exc:
                logger.debug("托盘图标停止异常: %s", exc)
            self._icon = None
        logger.info("系统托盘图标已停止")

    # ------------------------------------------------------------------
    # 状态更新
    # ------------------------------------------------------------------
    def update_status(self, status: TrayStatus) -> None:
        """切换图标状态（颜色）。"""
        self._current_status = status
        if self._icon is not None:
            try:
                self._icon.icon = _generate_icon_image(_STATUS_COLORS[status])
                self._icon.title = f"{self._tooltip} - {status.value}"
            except Exception as exc:
                logger.debug("更新图标状态异常: %s", exc)

    def set_tooltip(self, text: str) -> None:
        """设置鼠标悬停提示。"""
        self._tooltip = text
        if self._icon is not None:
            try:
                self._icon.title = text
            except Exception as exc:
                logger.debug("设置 tooltip 异常: %s", exc)

    # ------------------------------------------------------------------
    # 菜单
    # ------------------------------------------------------------------
    def _create_menu(self) -> "pystray.Menu":
        """创建右键菜单。"""
        import pystray

        voice_label = "🎤 关闭语音" if self._voice_enabled else "🎤 开启语音"

        return pystray.Menu(
            pystray.MenuItem("📋 打开对话窗口", self._on_chat_action),
            pystray.MenuItem(voice_label, self._on_voice_toggle_action),
            pystray.MenuItem("⚙️ 设置", self._on_settings_action),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ 退出", self._on_quit_action),
        )

    def _on_chat_action(self, icon: Any, item: Any) -> None:
        if self._on_chat:
            self._on_chat()

    def _on_voice_toggle_action(self, icon: Any, item: Any) -> None:
        self._voice_enabled = not self._voice_enabled
        if self._on_voice_toggle:
            self._on_voice_toggle()

    def _on_settings_action(self, icon: Any, item: Any) -> None:
        if self._on_settings:
            self._on_settings()

    def _on_quit_action(self, icon: Any, item: Any) -> None:
        if self._on_quit:
            self._on_quit()
        self.stop()
