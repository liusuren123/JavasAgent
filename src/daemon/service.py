# -*- coding: utf-8 -*-
"""JavasAgent 后台服务主类。

管理所有子系统（Agent、语音管道、IPC、托盘、热键、窗口）的完整生命周期。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

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
        self._ipc_server: Any = None
        self._tray: Any = None
        self._hotkey: Any = None
        self._chat_window: Any = None

        # 事件循环引用
        self._loop: Optional[asyncio.AbstractEventLoop] = None

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
        self._state = ServiceState.RUNNING
        logger.info("JavasAgent 服务已启动")

    async def stop(self) -> None:
        """按逆序停止所有子系统。"""
        if self._state in (ServiceState.STOPPED, ServiceState.STOPPING):
            return

        self._state = ServiceState.STOPPING
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
            "ipc_server": self._ipc_server is not None,
            "tray": self._tray is not None,
            "hotkey": self._hotkey is not None,
            "chat_window": self._chat_window is not None,
        }

    # ------------------------------------------------------------------
    # 子系统启动辅助（骨架，Step 7 完善）
    # ------------------------------------------------------------------
    async def _start_agent(self) -> None:
        """初始化 BaseAgent。"""
        try:
            # Step 7 将实现真正的 Agent 创建
            logger.info("Agent 初始化（骨架）")
        except Exception as exc:
            logger.error("Agent 启动失败: %s", exc)

    async def _start_voice_pipeline(self) -> None:
        """初始化语音管道（可选）。"""
        try:
            logger.info("语音管道初始化（骨架）")
        except Exception as exc:
            logger.error("语音管道启动失败: %s", exc)

    async def _start_ipc_server(self) -> None:
        """初始化 IPC 服务端。"""
        try:
            logger.info("IPC 服务器初始化（骨架）")
        except Exception as exc:
            logger.error("IPC 服务器启动失败: %s", exc)

    def _start_tray(self) -> None:
        """初始化系统托盘。"""
        try:
            logger.info("系统托盘初始化（骨架）")
        except Exception as exc:
            logger.error("系统托盘启动失败: %s", exc)

    def _start_hotkey(self) -> None:
        """初始化全局热键。"""
        try:
            logger.info("全局热键初始化（骨架）")
        except Exception as exc:
            logger.error("全局热键启动失败: %s", exc)

    # ------------------------------------------------------------------
    # 子系统停止辅助
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
            logger.info("IPC 服务器停止")
            self._ipc_server = None

    async def _stop_tray(self) -> None:
        if self._tray is not None:
            logger.info("系统托盘停止")
            self._tray = None

    async def _stop_hotkey(self) -> None:
        if self._hotkey is not None:
            logger.info("全局热键停止")
            self._hotkey = None

    async def _stop_chat_window(self) -> None:
        if self._chat_window is not None:
            logger.info("对话窗口停止")
            self._chat_window = None
