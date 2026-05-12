# -*- coding: utf-8 -*-
"""IPC 客户端 — 连接 Named Pipe 与后台服务通信。

CLI 端使用，用于向后台服务发送命令并接收响应。
"""

from __future__ import annotations

import logging
import struct
import time
from typing import Any, Optional

from .ipc_protocol import (
    HEADER_SIZE,
    IPCError,
    IPCRequest,
    IPCResponse,
    decode_message,
    encode_message,
    read_frame,
)

logger = logging.getLogger("javas.daemon.ipc_client")

# 默认连接超时（秒）
DEFAULT_TIMEOUT = 5.0
# 读写缓冲区
BUFFER_SIZE = 65536


class IPCClient:
    """Named Pipe IPC 客户端。

    用法:
        client = IPCClient()
        client.connect()
        response = client.send_request("chat", {"text": "你好"})
        client.close()
    """

    def __init__(
        self,
        pipe_name: str = "javasagent_pipe",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._pipe_name = pipe_name
        self._timeout = timeout
        self._handle: Any = None
        self._request_id = 0

    @property
    def is_connected(self) -> bool:
        """是否已连接。"""
        return self._handle is not None

    # ------------------------------------------------------------------
    # 连接 / 断开
    # ------------------------------------------------------------------
    def connect(self) -> None:
        """连接 Named Pipe，超时抛异常。"""
        if self._handle is not None:
            return

        try:
            import win32file
        except ImportError:
            raise RuntimeError("pywin32 未安装，无法使用 IPC 客户端")

        deadline = time.monotonic() + self._timeout

        while time.monotonic() < deadline:
            try:
                self._handle = win32file.CreateFile(
                    f"\\\\.\\pipe\\{self._pipe_name}",
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,
                    None,
                    win32file.OPEN_EXISTING,
                    0,
                    None,
                )

                # 设置消息模式
                import win32pipe
                win32pipe.SetNamedPipeHandleState(
                    self._handle,
                    win32pipe.PIPE_READMODE_MESSAGE,
                    None,
                    None,
                )
                logger.debug("IPC 客户端已连接 (pipe=%s)", self._pipe_name)
                return

            except Exception:
                time.sleep(0.1)

        raise ConnectionError(
            f"无法连接 Named Pipe '{self._pipe_name}'，超时 {self._timeout}s"
        )

    def close(self) -> None:
        """断开连接。"""
        if self._handle is not None:
            try:
                import win32file
                win32file.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None

    # ------------------------------------------------------------------
    # 请求
    # ------------------------------------------------------------------
    def send_request(
        self, method: str, params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """发送请求并等待响应。

        返回响应的 result 字段，错误时抛 IPCError。
        """
        if self._handle is None:
            raise RuntimeError("未连接")

        import win32file

        self._request_id += 1
        request = IPCRequest(
            id=self._request_id, method=method, params=params or {}
        )

        # 发送
        data = encode_message(request)
        win32file.WriteFile(self._handle, data)

        # 接收
        buf = b""
        deadline = time.monotonic() + self._timeout

        while time.monotonic() < deadline:
            try:
                _, chunk = win32file.ReadFile(self._handle, BUFFER_SIZE)
                buf += chunk

                payload, consumed = read_frame(buf)
                if consumed > 0:
                    msg = decode_message(payload)
                    if isinstance(msg, IPCError):
                        raise RuntimeError(f"IPC 错误 [{msg.code}]: {msg.message}")
                    if isinstance(msg, IPCResponse):
                        return msg.result or {}

            except RuntimeError:
                raise
            except Exception:
                time.sleep(0.05)

        raise TimeoutError(f"IPC 请求超时 ({self._timeout}s)")

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @classmethod
    def check_service_running(cls, pipe_name: str = "javasagent_pipe") -> bool:
        """检测后台服务是否在运行。

        尝试连接 Named Pipe，成功返回 True。
        """
        try:
            client = cls(pipe_name=pipe_name, timeout=1.0)
            client.connect()
            client.close()
            return True
        except Exception:
            return False
