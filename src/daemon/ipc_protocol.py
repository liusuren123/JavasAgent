# -*- coding: utf-8 -*-
"""IPC 消息协议定义。

使用 JSON-RPC 2.0 风格的消息格式，4 字节大端长度前缀用于帧分割。
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Any, Optional

# 协议常量
HEADER_SIZE = 4  # 4 字节长度前缀

# 方法名常量
METHOD_CHAT = "chat"
METHOD_STATUS = "status"
METHOD_STOP = "stop"
METHOD_VOICE_TOGGLE = "voice_toggle"
METHOD_SHOW_WINDOW = "show_window"

JSONRPC_VERSION = "2.0"


@dataclass
class IPCMessage:
    """IPC 消息基类。"""
    id: Optional[int] = None


@dataclass
class IPCRequest(IPCMessage):
    """IPC 请求消息。"""
    method: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": self.method}
        if self.id is not None:
            d["id"] = self.id
        if self.params:
            d["params"] = self.params
        return d


@dataclass
class IPCResponse(IPCMessage):
    """IPC 响应消息。"""
    result: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION}
        if self.id is not None:
            d["id"] = self.id
        if self.result is not None:
            d["result"] = self.result
        return d


@dataclass
class IPCError(IPCMessage):
    """IPC 错误响应。"""
    code: int = -1
    message: str = ""
    data: Optional[Any] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "error": {"code": self.code, "message": self.message},
        }
        if self.id is not None:
            d["id"] = self.id
        if self.data is not None:
            d["error"]["data"] = self.data
        return d


# ---------------------------------------------------------------------------
# 序列化 / 反序列化
# ---------------------------------------------------------------------------

def encode_message(msg: IPCMessage) -> bytes:
    """将 IPCMessage 编码为带长度前缀的字节流。

    格式: [4 字节大端长度][JSON 字节流]
    """
    payload = json.dumps(msg.to_dict(), ensure_ascii=False).encode("utf-8")
    length_prefix = struct.pack(">I", len(payload))
    return length_prefix + payload


def decode_message(data: bytes) -> IPCMessage:
    """从字节流解析 IPCMessage（不含长度前缀，纯 JSON 部分）。"""
    obj = json.loads(data.decode("utf-8"))

    if "error" in obj:
        err = obj["error"]
        return IPCError(
            id=obj.get("id"),
            code=err.get("code", -1),
            message=err.get("message", ""),
            data=err.get("data"),
        )

    if "method" in obj:
        return IPCRequest(
            id=obj.get("id"),
            method=obj["method"],
            params=obj.get("params", {}),
        )

    return IPCResponse(
        id=obj.get("id"),
        result=obj.get("result"),
    )


def read_frame(data: bytes) -> tuple[bytes, int]:
    """从带长度前缀的数据中读取一帧。

    返回: (payload_bytes, total_bytes_consumed)
    如果数据不完整，返回 (b"", 0)
    """
    if len(data) < HEADER_SIZE:
        return b"", 0

    payload_len = struct.unpack(">I", data[:HEADER_SIZE])[0]
    total = HEADER_SIZE + payload_len

    if len(data) < total:
        return b"", 0

    return data[HEADER_SIZE:total], total
