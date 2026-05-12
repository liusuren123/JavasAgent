# -*- coding: utf-8 -*-
"""IPC 服务端 — 基于 Windows Named Pipe。

使用 pywin32 的 win32pipe + win32file 实现高性能本地 IPC。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable, Optional

from .ipc_protocol import (
    HEADER_SIZE,
    IPCError,
    IPCRequest,
    IPCResponse,
    decode_message,
    encode_message,
    read_frame,
)

logger = logging.getLogger("javas.daemon.ipc_server")

# Named Pipe 缓冲区大小
PIPE_BUFFER_SIZE = 65536
# 默认最大并发连接数
MAX_CONNECTIONS = 5


class IPCServer:
    """Named Pipe IPC 服务端。

    用法:
        server = IPCServer()
        server.register_handler("chat", my_chat_handler)
        server.start()  # 非阻塞，后台线程监听
        ...
        server.stop()
    """

    def __init__(self, pipe_name: str = "javasagent_pipe") -> None:
        self._pipe_name = pipe_name
        self._handlers: dict[str, Callable] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pipe_handle: Any = None
        self._connections: list[Any] = []

    @property
    def pipe_name(self) -> str:
        return self._pipe_name

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # handler 注册
    # ------------------------------------------------------------------
    def register_handler(self, method: str, callback: Callable) -> None:
        """注册方法处理回调。

        callback 签名: async (params: dict) -> dict
        """
        self._handlers[method] = callback
        logger.debug("注册 handler: %s", method)

    def unregister_handler(self, method: str) -> None:
        """移除方法处理回调。"""
        self._handlers.pop(method, None)

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动 IPC 服务器（后台线程）。"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop, name="ipc-listener", daemon=True
        )
        self._thread.start()
        logger.info("IPC 服务器已启动 (pipe=%s)", self._pipe_name)

    def stop(self) -> None:
        """停止 IPC 服务器。"""
        if not self._running:
            return

        self._running = False
        self._close_pipe()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("IPC 服务器已停止")

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _listen_loop(self) -> None:
        """主监听循环（运行在后台线程）。"""
        try:
            import pywintypes
            import win32file
            import win32pipe
        except ImportError:
            logger.error("pywin32 未安装，IPC 服务器无法启动")
            self._running = False
            return

        while self._running:
            try:
                # 创建 Named Pipe
                self._pipe_handle = win32pipe.CreateNamedPipe(
                    f"\\\\.\\pipe\\{self._pipe_name}",
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                    MAX_CONNECTIONS,
                    PIPE_BUFFER_SIZE,
                    PIPE_BUFFER_SIZE,
                    0,  # 默认超时
                    None,
                )

                # 等待客户端连接
                win32pipe.ConnectNamedPipe(self._pipe_handle, None)
                logger.debug("客户端已连接")

                # 在新线程中处理连接
                conn_thread = threading.Thread(
                    target=self._handle_connection,
                    args=(self._pipe_handle,),
                    daemon=True,
                )
                conn_thread.start()
                self._connections.append((self._pipe_handle, conn_thread))

            except Exception as exc:
                if self._running:
                    logger.error("IPC 监听异常: %s", exc)
                break

    def _handle_connection(self, pipe_handle: Any) -> None:
        """处理单个客户端连接。"""
        try:
            import win32file
        except ImportError:
            return

        buf = b""
        while self._running:
            try:
                # 读取数据
                result, data = win32file.ReadFile(pipe_handle, PIPE_BUFFER_SIZE)
                if result != 0:
                    break

                buf += data

                # 解帧
                while buf:
                    payload, consumed = read_frame(buf)
                    if consumed == 0:
                        break
                    buf = buf[consumed:]

                    # 处理请求
                    msg = decode_message(payload)
                    if isinstance(msg, IPCRequest):
                        response = self._route_request(msg)
                        resp_bytes = encode_message(response)
                        win32file.WriteFile(pipe_handle, resp_bytes)

            except Exception as exc:
                if self._running:
                    logger.debug("连接处理异常: %s", exc)
                break

        try:
            import win32pipe
            win32pipe.DisconnectNamedPipe(pipe_handle)
        except Exception:
            pass

    def _route_request(self, request: IPCRequest) -> Any:
        """路由请求到对应 handler。"""
        handler = self._handlers.get(request.method)
        if handler is None:
            return IPCError(
                id=request.id,
                code=-32601,
                message=f"方法未找到: {request.method}",
            )

        try:
            # 同步或异步 handler
            import asyncio
            import inspect

            if inspect.iscoroutinefunction(handler):
                # 尝试在已有事件循环中调度
                try:
                    loop = asyncio.get_running_loop()
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        result = loop.run_in_executor(pool, lambda: asyncio.run(handler(request.params)))
                        # 简化处理：直接 asyncio.run
                    result = asyncio.run(handler(request.params))
                except RuntimeError:
                    result = asyncio.run(handler(request.params))
            else:
                result = handler(request.params)

            return IPCResponse(id=request.id, result=result)

        except Exception as exc:
            logger.error("handler '%s' 执行异常: %s", request.method, exc)
            return IPCError(
                id=request.id,
                code=-32603,
                message=str(exc),
            )

    def _close_pipe(self) -> None:
        """关闭 Named Pipe。"""
        try:
            import win32pipe
            if self._pipe_handle is not None:
                try:
                    win32pipe.DisconnectNamedPipe(self._pipe_handle)
                except Exception:
                    pass
                try:
                    import win32file
                    win32file.CloseHandle(self._pipe_handle)
                except Exception:
                    pass
                self._pipe_handle = None
        except ImportError:
            pass
