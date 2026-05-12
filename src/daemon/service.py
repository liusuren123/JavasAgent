# -*- coding: utf-8 -*-
"""JavasAgent 后台服务主类。

管理所有子系统（Agent、语音管道、IPC、托盘、热键、窗口）的完整生命周期。
Step 7: 串联所有组件 + IPC handler。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .autostart import AutoStart
from .chat_window import ChatWindow
from .hotkey_manager import HotkeyManager
from .ipc_protocol import METHOD_CHAT, METHOD_STATUS, METHOD_STOP, METHOD_VOICE_TOGGLE, METHOD_SHOW_WINDOW
from .ipc_server import IPCServer
from .tray_icon import TrayIcon, TrayStatus

logger = logging.getLogger("javas.daemon")


class ServiceState(Enum):
    """服务运行状态。"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class ServiceConfig:
    """服务配置。"""
    enabled: bool = True
    pipe_name: str = "javasagent_pipe"
    autostart: bool = False
    tray_enabled: bool = True
    tray_tooltip: str = "JavasAgent"
    hotkeys: dict[str, str] = field(default_factory=lambda: {
        "chat": "ctrl+alt+j",
        "voice_toggle": "ctrl+alt+v",
        "stop_task": "ctrl+alt+s",
    })
    window_width: int = 600
    window_height: int = 400
    window_always_on_top: bool = True


class JavasService:
    """后台服务主类，管理所有子系统的启动、运行和停止。"""

    def __init__(self, config: Optional[ServiceConfig] = None) -> None:
        self._config = config or ServiceConfig()
        self._state = ServiceState.STOPPED

        # 子系统引用（由 start() 初始化）
        self._agent: Any = None
        self._voice_pipeline: Any = None
        self._ipc_server: Optional[IPCServer] = None
        self._tray: Optional[TrayIcon] = None
        self._hotkey: Optional[HotkeyManager] = None
        self._chat_window: Optional[ChatWindow] = None

        # 事件循环引用
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False

        # 语音开关状态
        self._voice_enabled = False

    # ------------------------------------------------------------------
    # 公共属性
    # ------------------------------------------------------------------
    @property
    def state(self) -> ServiceState:
        """当前服务状态。"""
        return self._state

    @property
    def config(self) -> ServiceConfig:
        """服务配置。"""
        return self._config

    @property
    def is_running(self) -> bool:
        """服务是否正在运行。"""
        return self._running

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """启动所有子系统。

        按顺序启动，每个子系统独立 try/except，
        单个组件失败不阻塞其他组件。
        """
        if self._state == ServiceState.RUNNING:
            logger.warning("服务已在运行中，跳过重复启动")
            return

        self._state = ServiceState.STARTING
        self._loop = asyncio.get_running_loop()
        self._running = True
        logger.info("JavasAgent 服务启动中...")

        # 1. Agent（核心）
        await self._start_agent()

        # 2. 语音管道（可选）
        await self._start_voice_pipeline()

        # 3. IPC 服务器
        await self._start_ipc_server()

        # 4. 系统托盘
        self._start_tray()

        # 5. 全局热键
        self._start_hotkey()

        # 6. 对话窗口（懒加载，不在此启动）
        self._init_chat_window()

        self._state = ServiceState.RUNNING
        logger.info("JavasAgent 服务已启动，所有子系统就绪")

    async def stop(self) -> None:
        """按逆序停止所有子系统。"""
        if self._state in (ServiceState.STOPPED, ServiceState.STOPPING):
            return

        self._state = ServiceState.STOPPING
        self._running = False
        logger.info("JavasAgent 服务停止中...")

        # 逆序停止
        await self._stop_component("对话窗口", self._stop_chat_window)
        await self._stop_component("全局热键", self._stop_hotkey)
        await self._stop_component("系统托盘", self._stop_tray)
        await self._stop_component("IPC 服务器", self._stop_ipc_server)
        await self._stop_component("语音管道", self._stop_voice_pipeline)
        await self._stop_component("Agent", self._stop_agent)

        self._state = ServiceState.STOPPED
        logger.info("JavasAgent 服务已停止")

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """返回各子系统运行状态。"""
        return {
            "state": self._state.value,
            "agent": self._agent is not None,
            "voice_pipeline": self._voice_pipeline is not None,
            "voice_enabled": self._voice_enabled,
            "ipc_server": self._ipc_server is not None and self._ipc_server.is_running,
            "tray": self._tray is not None,
            "hotkey": self._hotkey is not None and self._hotkey.is_active,
            "chat_window": self._chat_window is not None,
        }

    # ------------------------------------------------------------------
    # 子系统启动
    # ------------------------------------------------------------------
    async def _start_agent(self) -> None:
        """初始化 BaseAgent。"""
        try:
            # 延迟导入避免在 import 时触发大量依赖
            import importlib
            main_mod = importlib.import_module("src.main")
            create_fn = getattr(main_mod, "create_agent", None)
            if create_fn is not None:
                self._agent = create_fn()
                logger.info("Agent 已初始化")
            else:
                logger.warning("create_agent 函数未找到")
        except Exception as exc:
            logger.error("Agent 启动失败: %s", exc)

    async def _start_voice_pipeline(self) -> None:
        """初始化语音管道（可选）。"""
        try:
            # 语音管道需要 Agent 先就绪，按需启动
            logger.info("语音管道待命（按需启动）")
        except Exception as exc:
            logger.error("语音管道启动失败: %s", exc)

    async def _start_ipc_server(self) -> None:
        """初始化 IPC 服务端并注册 handler。"""
        try:
            self._ipc_server = IPCServer(pipe_name=self._config.pipe_name)

            # 注册 handler
            self._ipc_server.register_handler(METHOD_CHAT, self._handle_chat)
            self._ipc_server.register_handler(METHOD_STATUS, self._handle_status)
            self._ipc_server.register_handler(METHOD_STOP, self._handle_stop)
            self._ipc_server.register_handler(METHOD_VOICE_TOGGLE, self._handle_voice_toggle)
            self._ipc_server.register_handler(METHOD_SHOW_WINDOW, self._handle_show_window)

            self._ipc_server.start()
            logger.info("IPC 服务器已启动 (pipe=%s)", self._config.pipe_name)
        except Exception as exc:
            logger.error("IPC 服务器启动失败: %s", exc)

    def _start_tray(self) -> None:
        """初始化系统托盘。"""
        try:
            if not self._config.tray_enabled:
                logger.info("托盘图标已禁用")
                return

            self._tray = TrayIcon(
                on_quit=self._on_tray_quit,
                on_chat=self._on_tray_chat,
                on_voice_toggle=self._on_tray_voice_toggle,
                on_settings=self._on_tray_settings,
                tooltip=self._config.tray_tooltip,
            )
            self._tray.start()
            logger.info("系统托盘已启动")
        except Exception as exc:
            logger.error("系统托盘启动失败: %s", exc)

    def _start_hotkey(self) -> None:
        """初始化全局热键。"""
        try:
            self._hotkey = HotkeyManager()

            # 注册默认热键
            hotkey_map = {
                "chat": self._on_hotkey_chat,
                "voice_toggle": self._on_hotkey_voice_toggle,
                "stop_task": self._on_hotkey_stop_task,
            }
            for name, callback in hotkey_map.items():
                combo = self._config.hotkeys.get(name)
                if combo:
                    self._hotkey.register(combo, callback)

            self._hotkey.start()
            logger.info("全局热键已启动")
        except Exception as exc:
            logger.error("全局热键启动失败: %s", exc)

    def _init_chat_window(self) -> None:
        """初始化对话窗口（不立即显示）。"""
        try:
            self._chat_window = ChatWindow(
                on_send_message=self._on_chat_send,
                width=self._config.window_width,
                height=self._config.window_height,
                always_on_top=self._config.window_always_on_top,
            )
            logger.info("对话窗口已初始化")
        except Exception as exc:
            logger.error("对话窗口初始化失败: %s", exc)

    # ------------------------------------------------------------------
    # 子系统停止
    # ------------------------------------------------------------------
    async def _stop_component(self, name: str, stop_fn: Callable) -> None:
        """安全停止单个组件。"""
        try:
            await stop_fn()
        except Exception as exc:
            logger.error("%s 停止失败: %s", name, exc)

    async def _stop_agent(self) -> None:
        if self._agent is not None:
            logger.info("Agent 停止")
            self._agent = None

    async def _stop_voice_pipeline(self) -> None:
        if self._voice_pipeline is not None:
            logger.info("语音管道停止")
            self._voice_pipeline = None

    async def _stop_ipc_server(self) -> None:
        if self._ipc_server is not None:
            self._ipc_server.stop()
            self._ipc_server = None
            logger.info("IPC 服务器已停止")

    async def _stop_tray(self) -> None:
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
            logger.info("系统托盘已停止")

    async def _stop_hotkey(self) -> None:
        if self._hotkey is not None:
            self._hotkey.stop()
            self._hotkey = None
            logger.info("全局热键已停止")

    async def _stop_chat_window(self) -> None:
        if self._chat_window is not None:
            self._chat_window.close()
            self._chat_window = None
            logger.info("对话窗口已关闭")

    # ------------------------------------------------------------------
    # IPC Handler
    # ------------------------------------------------------------------
    def _handle_chat(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理聊天请求。"""
        text = params.get("text", "")
        if not text:
            return {"status": "error", "message": "消息不能为空"}

        if self._agent is None:
            return {"status": "error", "message": "Agent 未就绪"}

        try:
            result = asyncio.run(self._agent.process(text))
            return {"status": "ok", "response": str(result)}
        except Exception as exc:
            logger.error("chat handler 异常: %s", exc)
            return {"status": "error", "message": str(exc)}

    def _handle_status(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理状态查询。"""
        return self.status()

    def _handle_stop(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理停止请求。"""
        # 在后台线程中触发停止
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self.stop(), self._loop)
        return {"status": "ok", "message": "服务正在停止"}

    def _handle_voice_toggle(self, params: dict[str, Any]) -> dict[str, Any]:
        """切换语音模式。"""
        self._voice_enabled = not self._voice_enabled
        state_text = "开启" if self._voice_enabled else "关闭"

        # 更新托盘状态
        if self._tray is not None:
            if self._voice_enabled:
                self._tray.update_status(TrayStatus.ACTIVE)
            else:
                self._tray.update_status(TrayStatus.PAUSED)

        return {"status": "ok", "voice_enabled": self._voice_enabled}

    def _handle_show_window(self, params: dict[str, Any]) -> dict[str, Any]:
        """显示对话窗口。"""
        if self._chat_window is not None:
            self._chat_window.show()
            return {"status": "ok"}
        return {"status": "error", "message": "对话窗口未初始化"}

    # ------------------------------------------------------------------
    # 回调
    # ------------------------------------------------------------------
    def _on_tray_quit(self) -> None:
        """托盘 → 退出。"""
        logger.info("托盘菜单触发退出")
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self.stop(), self._loop)

    def _on_tray_chat(self) -> None:
        """托盘 → 打开对话窗口。"""
        if self._chat_window is not None:
            self._chat_window.show()

    def _on_tray_voice_toggle(self) -> None:
        """托盘 → 切换语音。"""
        self._handle_voice_toggle({})

    def _on_tray_settings(self) -> None:
        """托盘 → 打开配置文件。"""
        import os
        import sys
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "default.yaml")
        config_path = os.path.abspath(config_path)
        logger.info("打开配置文件: %s", config_path)
        try:
            os.startfile(config_path)
        except Exception as exc:
            logger.error("打开配置文件失败: %s", exc)

    def _on_hotkey_chat(self) -> None:
        """热键 → 打开对话窗口。"""
        if self._chat_window is not None:
            self._chat_window.show()

    def _on_hotkey_voice_toggle(self) -> None:
        """热键 → 切换语音。"""
        self._handle_voice_toggle({})

    def _on_hotkey_stop_task(self) -> None:
        """热键 → 停止当前任务。"""
        logger.info("热键触发停止当前任务")
        # TODO: 实现任务中断

    def _on_chat_send(self, text: str) -> None:
        """对话窗口发送消息。"""
        if self._chat_window is not None:
            self._chat_window.set_status("思考中...")

        if self._agent is None:
            if self._chat_window is not None:
                self._chat_window.add_message("system", "Agent 未就绪")
                self._chat_window.set_status("错误")
            return

        try:
            result = asyncio.run(self._agent.process(text))
            if self._chat_window is not None:
                self._chat_window.add_message("agent", str(result))
                self._chat_window.set_status("就绪")
        except Exception as exc:
            if self._chat_window is not None:
                self._chat_window.add_message("system", f"错误: {exc}")
                self._chat_window.set_status("错误")
