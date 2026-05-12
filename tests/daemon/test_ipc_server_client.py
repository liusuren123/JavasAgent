# -*- coding: utf-8 -*-
"""IPC 服务端 + 客户端集成测试。

使用 mock 替代 win32pipe/win32file，避免依赖 pywin32。
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from src.daemon.ipc_protocol import IPCError, IPCRequest, IPCResponse, encode_message
from src.daemon.ipc_server import IPCServer
from src.daemon.ipc_client import IPCClient


# ---------------------------------------------------------------------------
# IPCServer 测试
# ---------------------------------------------------------------------------

class TestIPCServer:
    """IPCServer 测试（不依赖真实 Named Pipe）。"""

    def test_init_defaults(self):
        server = IPCServer()
        assert server.pipe_name == "javasagent_pipe"
        assert server.is_running is False

    def test_register_handler(self):
        server = IPCServer()
        callback = lambda params: {"ok": True}
        server.register_handler("test", callback)
        assert "test" in server._handlers

    def test_unregister_handler(self):
        server = IPCServer()
        server.register_handler("test", lambda p: {})
        server.unregister_handler("test")
        assert "test" not in server._handlers

    def test_unregister_nonexistent(self):
        server = IPCServer()
        server.unregister_handler("nope")  # 不报错

    def test_route_request_known_method(self):
        server = IPCServer()
        server.register_handler("echo", lambda params: params)

        req = IPCRequest(id=1, method="echo", params={"msg": "hi"})
        resp = server._route_request(req)
        assert isinstance(resp, IPCResponse)
        assert resp.result == {"msg": "hi"}

    def test_route_request_unknown_method(self):
        server = IPCServer()
        req = IPCRequest(id=1, method="nonexistent")
        resp = server._route_request(req)
        assert isinstance(resp, IPCError)
        assert resp.code == -32601

    def test_route_request_handler_exception(self):
        server = IPCServer()

        def bad_handler(params):
            raise ValueError("boom")

        server.register_handler("bad", bad_handler)
        req = IPCRequest(id=1, method="bad")
        resp = server._route_request(req)
        assert isinstance(resp, IPCError)
        assert resp.code == -32603

    def test_start_stop_without_pywin32(self):
        """pywin32 不可用时 start/stop 不崩溃。"""
        server = IPCServer()
        # 模拟 win32pipe 不可用
        with patch.dict("sys.modules", {"win32pipe": None, "win32file": None, "pywintypes": None}):
            # start 会启动线程，但 _listen_loop 中 import 失败会退出
            server.start()
            # 给线程一点时间
            import time
            time.sleep(0.2)
            server.stop()

    def test_stop_when_not_running(self):
        server = IPCServer()
        server.stop()  # 不报错


# ---------------------------------------------------------------------------
# IPCClient 测试
# ---------------------------------------------------------------------------

class TestIPCClient:
    """IPCClient 测试（mock win32）。"""

    def test_init_defaults(self):
        client = IPCClient()
        assert client._pipe_name == "javasagent_pipe"
        assert client.is_connected is False

    def test_close_when_not_connected(self):
        client = IPCClient()
        client.close()  # 不报错

    def test_send_request_not_connected(self):
        client = IPCClient()
        with pytest.raises(RuntimeError, match="未连接"):
            client.send_request("chat", {"text": "hi"})

    def test_check_service_running_returns_false(self):
        """没有真实服务时返回 False。"""
        result = IPCClient.check_service_running(pipe_name="nonexistent_test_pipe")
        assert result is False
