# -*- coding: utf-8 -*-
"""IPC 消息协议测试。"""

import json
import struct

import pytest

from src.daemon.ipc_protocol import (
    HEADER_SIZE,
    IPCError,
    IPCMessage,
    IPCRequest,
    IPCResponse,
    METHOD_CHAT,
    METHOD_STATUS,
    METHOD_STOP,
    decode_message,
    encode_message,
    read_frame,
)


class TestIPCRequest:
    """IPCRequest 构造测试。"""

    def test_basic_request(self):
        req = IPCRequest(id=1, method=METHOD_CHAT, params={"text": "hello"})
        d = req.to_dict()
        assert d["jsonrpc"] == "2.0"
        assert d["method"] == "chat"
        assert d["id"] == 1
        assert d["params"] == {"text": "hello"}

    def test_request_without_params(self):
        req = IPCRequest(id=2, method=METHOD_STATUS)
        d = req.to_dict()
        assert "params" not in d or d.get("params") == {}

    def test_request_without_id(self):
        req = IPCRequest(method="test")
        d = req.to_dict()
        assert "id" not in d


class TestIPCResponse:
    """IPCResponse 构造测试。"""

    def test_basic_response(self):
        resp = IPCResponse(id=1, result={"status": "ok"})
        d = resp.to_dict()
        assert d["jsonrpc"] == "2.0"
        assert d["id"] == 1
        assert d["result"] == {"status": "ok"}

    def test_response_without_result(self):
        resp = IPCResponse(id=2)
        d = resp.to_dict()
        assert "result" not in d or d.get("result") is None


class TestIPCError:
    """IPCError 构造测试。"""

    def test_basic_error(self):
        err = IPCError(id=1, code=-32601, message="Method not found")
        d = err.to_dict()
        assert d["jsonrpc"] == "2.0"
        assert d["id"] == 1
        assert d["error"]["code"] == -32601
        assert d["error"]["message"] == "Method not found"

    def test_error_with_data(self):
        err = IPCError(id=2, code=-32603, message="Internal error", data="detail")
        d = err.to_dict()
        assert d["error"]["data"] == "detail"


class TestEncodeDecode:
    """encode / decode 往返测试。"""

    def test_request_roundtrip(self):
        req = IPCRequest(id=42, method=METHOD_CHAT, params={"text": "测试"})
        encoded = encode_message(req)
        # 前缀 4 字节长度
        length = struct.unpack(">I", encoded[:HEADER_SIZE])[0]
        payload = encoded[HEADER_SIZE:]
        assert len(payload) == length

        decoded = decode_message(payload)
        assert isinstance(decoded, IPCRequest)
        assert decoded.id == 42
        assert decoded.method == "chat"
        assert decoded.params == {"text": "测试"}

    def test_response_roundtrip(self):
        resp = IPCResponse(id=1, result={"status": "running"})
        encoded = encode_message(resp)
        payload = encoded[HEADER_SIZE:]
        decoded = decode_message(payload)
        assert isinstance(decoded, IPCResponse)
        assert decoded.result == {"status": "running"}

    def test_error_roundtrip(self):
        err = IPCError(id=1, code=-32000, message="Server error")
        encoded = encode_message(err)
        payload = encoded[HEADER_SIZE:]
        decoded = decode_message(payload)
        assert isinstance(decoded, IPCError)
        assert decoded.code == -32000
        assert decoded.message == "Server error"

    def test_length_prefix_correct(self):
        req = IPCRequest(id=1, method="test")
        data = encode_message(req)
        # 前 4 字节是大端 uint32
        length = struct.unpack(">I", data[:4])[0]
        assert length == len(data) - 4

    def test_utf8_support(self):
        req = IPCRequest(id=1, method=METHOD_CHAT, params={"text": "中文消息🤖"})
        encoded = encode_message(req)
        payload = encoded[HEADER_SIZE:]
        decoded = decode_message(payload)
        assert decoded.params["text"] == "中文消息🤖"


class TestReadFrame:
    """read_frame 帧解析测试。"""

    def test_complete_frame(self):
        req = IPCRequest(id=1, method="test")
        encoded = encode_message(req)
        payload, consumed = read_frame(encoded)
        assert consumed == len(encoded)
        assert len(payload) > 0

    def test_incomplete_header(self):
        payload, consumed = read_frame(b"\x00")
        assert consumed == 0
        assert payload == b""

    def test_incomplete_payload(self):
        req = IPCRequest(id=1, method="test")
        encoded = encode_message(req)
        # 截断：只有 header + 部分数据
        truncated = encoded[:HEADER_SIZE + 2]
        payload, consumed = read_frame(truncated)
        assert consumed == 0
        assert payload == b""

    def test_multiple_frames(self):
        req1 = IPCRequest(id=1, method="a")
        req2 = IPCRequest(id=2, method="b")
        data = encode_message(req1) + encode_message(req2)

        payload1, consumed1 = read_frame(data)
        assert consumed1 > 0
        decoded1 = decode_message(payload1)
        assert decoded1.method == "a"

        payload2, consumed2 = read_frame(data[consumed1:])
        assert consumed2 > 0
        decoded2 = decode_message(payload2)
        assert decoded2.method == "b"
