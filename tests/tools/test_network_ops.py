"""网络操作工具测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.tools.network_ops import NetworkOps


# ------------------------------------------------------------------
# Fixtures & Helpers
# ------------------------------------------------------------------

@pytest.fixture
def tool() -> NetworkOps:
    return NetworkOps(config={"download_workspace": "/tmp/test_dl"})


def _mock_response(
    status_code: int = 200, text: str = "OK",
    headers: dict | None = None, json_data: Any = None,
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.headers = httpx.Headers(headers or {"content-type": "text/plain"})
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = Exception("not json")
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "err", request=MagicMock(), response=resp,
        )
    return resp


def _make_client(response: MagicMock) -> AsyncMock:
    client = AsyncMock()
    client.request = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class AsyncIterator:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)
    def __aiter__(self):
        return self
    async def __anext__(self) -> bytes:
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration


def _make_stream_client(status: int, chunks: list[bytes], cl: str | None = None) -> AsyncMock:
    stream_resp = AsyncMock()
    stream_resp.status_code = status
    hdrs = {}
    if cl:
        hdrs["content-length"] = cl
    stream_resp.headers = httpx.Headers(hdrs)
    stream_resp.raise_for_status = MagicMock()
    stream_resp.aiter_bytes = MagicMock(return_value=AsyncIterator(chunks))
    stream_resp.__aenter__ = AsyncMock(return_value=stream_resp)
    stream_resp.__aexit__ = AsyncMock(return_value=False)

    client = AsyncMock()
    client.stream = MagicMock(return_value=stream_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ------------------------------------------------------------------
# Test: execute 入口
# ------------------------------------------------------------------

class TestExecute:

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool: NetworkOps) -> None:
        result = await tool.execute("nonexistent", {})
        assert "未知操作" in result["error"]

    @pytest.mark.asyncio
    async def test_dispatch_http_get(self, tool: NetworkOps) -> None:
        mock_resp = _mock_response(200, "hello")
        client = _make_client(mock_resp)
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            result = await tool.execute("http_get", {"url": "https://example.com"})
            assert result["success"] is True


# ------------------------------------------------------------------
# Test: HTTP GET / POST / PUT / DELETE
# ------------------------------------------------------------------

class TestHttpMethods:

    @pytest.mark.asyncio
    async def test_get_success(self, tool: NetworkOps) -> None:
        client = _make_client(_mock_response(200, "body"))
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.http_get({"url": "https://example.com"})
            assert r["success"] and r["status_code"] == 200 and r["body"] == "body"

    @pytest.mark.asyncio
    async def test_get_with_params_headers(self, tool: NetworkOps) -> None:
        client = _make_client(_mock_response(200, "ok"))
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.http_get({
                "url": "https://example.com", "params": {"q": "test"},
                "headers": {"X-Custom": "val"},
            })
            assert r["success"]

    @pytest.mark.asyncio
    async def test_get_missing_url(self, tool: NetworkOps) -> None:
        assert "error" in await tool.http_get({})

    @pytest.mark.asyncio
    async def test_post_json(self, tool: NetworkOps) -> None:
        client = _make_client(_mock_response(201, '{"id":1}', json_data={"id": 1}))
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.http_post({"url": "https://api.example.com", "json": {"n": 1}})
            assert r["status_code"] == 201

    @pytest.mark.asyncio
    async def test_post_missing_url(self, tool: NetworkOps) -> None:
        assert "error" in await tool.http_post({})

    @pytest.mark.asyncio
    async def test_put_success(self, tool: NetworkOps) -> None:
        client = _make_client(_mock_response(200, "updated"))
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.http_put({"url": "https://api.example.com/1", "json": {"x": 1}})
            assert r["success"]

    @pytest.mark.asyncio
    async def test_delete_success(self, tool: NetworkOps) -> None:
        client = _make_client(_mock_response(204, ""))
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.http_delete({"url": "https://api.example.com/1"})
            assert r["status_code"] == 204

    @pytest.mark.asyncio
    async def test_timeout_error(self, tool: NetworkOps) -> None:
        client = _make_client(_mock_response(200))
        client.request = AsyncMock(side_effect=httpx.TimeoutException("t"))
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.execute("http_get", {"url": "https://slow.com"})
            assert "超时" in r["error"]

    @pytest.mark.asyncio
    async def test_connect_error(self, tool: NetworkOps) -> None:
        client = _make_client(_mock_response(200))
        client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.execute("http_get", {"url": "https://down.com"})
            assert "连接失败" in r["error"]

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self, tool: NetworkOps) -> None:
        calls = 0
        async def flaky(**kw):
            nonlocal calls; calls += 1
            if calls < 3:
                raise httpx.TimeoutException("t")
            return _mock_response(200, "ok")

        client = _make_client(_mock_response(200))
        client.request = flaky
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            with patch("src.tools.network_ops.asyncio.sleep", new_callable=AsyncMock):
                r = await tool.execute("http_get", {"url": "https://flaky.com", "retries": 3})
        assert r["success"] is True
        assert calls == 3


# ------------------------------------------------------------------
# Test: 文件下载
# ------------------------------------------------------------------

class TestDownloadFile:

    @pytest.mark.asyncio
    async def test_missing_url(self, tool: NetworkOps) -> None:
        assert "缺少 url" in (await tool.download_file({"save_path": "f.txt"}))["error"]

    @pytest.mark.asyncio
    async def test_missing_path(self, tool: NetworkOps) -> None:
        assert "缺少 save_path" in (await tool.download_file({"url": "https://x.com/f"}))["error"]

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, tool: NetworkOps) -> None:
        r = await tool.download_file({"url": "https://evil.com/m", "save_path": "../../../etc/pw"})
        assert "路径安全违规" in r.get("error", "")

    @pytest.mark.asyncio
    async def test_download_success(self, tool: NetworkOps, tmp_path: Path) -> None:
        tool._download_workspace = tmp_path
        client = _make_stream_client(200, [b"hello world!"], "12")
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.download_file({"url": "https://x.com/f.txt", "save_path": "f.txt"})
        assert r["success"] and r["size_bytes"] == 12 and r["resumed"] is False

    @pytest.mark.asyncio
    async def test_download_size_mismatch(self, tool: NetworkOps, tmp_path: Path) -> None:
        tool._download_workspace = tmp_path
        client = _make_stream_client(200, [b"hello"], "5")
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.download_file({
                "url": "https://x.com/f.txt", "save_path": "f.txt",
                "expected_size": 999,
            })
        assert "文件大小不匹配" in r.get("error", "")

    @pytest.mark.asyncio
    async def test_download_connect_error(self, tool: NetworkOps, tmp_path: Path) -> None:
        tool._download_workspace = tmp_path
        client = _make_stream_client(200, [b"x"])
        client.stream.side_effect = httpx.ConnectError("refused")
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.download_file({"url": "https://x.com/f.txt", "save_path": "f.txt"})
        assert "下载连接失败" in r["error"]


# ------------------------------------------------------------------
# Test: 网络连通性
# ------------------------------------------------------------------

class TestCheckConnectivity:

    @pytest.mark.asyncio
    async def test_single_url_ok(self, tool: NetworkOps) -> None:
        client = AsyncMock()
        client.head = AsyncMock(return_value=_mock_response(200, "ok"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.check_connectivity({"url": "https://example.com"})
        assert r["connected"] and "latency_ms" in r

    @pytest.mark.asyncio
    async def test_single_url_timeout(self, tool: NetworkOps) -> None:
        client = AsyncMock()
        client.head = AsyncMock(side_effect=httpx.TimeoutException("t"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.check_connectivity({"url": "https://slow.com"})
        assert r["connected"] is False and r["error"] == "超时"

    @pytest.mark.asyncio
    async def test_multi_url(self, tool: NetworkOps) -> None:
        n = 0
        async def head(url):
            nonlocal n; n += 1
            if n == 1:
                return _mock_response(200, "ok")
            raise httpx.ConnectError("fail")

        client = AsyncMock()
        client.head = head
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.check_connectivity({})
        assert r["connected"] is True and len(r["targets"]) == 3


# ------------------------------------------------------------------
# Test: API 调用
# ------------------------------------------------------------------

class TestApiCall:

    @pytest.mark.asyncio
    async def test_basic_get(self, tool: NetworkOps) -> None:
        client = _make_client(_mock_response(200, '{"ok":true}', json_data={"ok": True}))
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.api_call({"url": "https://api.example.com/status"})
        assert r["success"] and r["data"] == {"ok": True}

    @pytest.mark.asyncio
    async def test_bearer_auth(self, tool: NetworkOps) -> None:
        captured = {}
        async def cap(**kw):
            captured.update(kw.get("headers", {}))
            return _mock_response(200, "ok")

        client = _make_client(_mock_response(200))
        client.request = cap
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            await tool.api_call({
                "url": "https://api.example.com/me",
                "auth_type": "bearer", "token": "secret-123",
            })
        assert captured["Authorization"] == "Bearer secret-123"

    @pytest.mark.asyncio
    async def test_api_key_auth(self, tool: NetworkOps) -> None:
        captured = {}
        async def cap(**kw):
            captured.update(kw.get("headers", {}))
            return _mock_response(200, "ok")

        client = _make_client(_mock_response(200))
        client.request = cap
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            await tool.api_call({
                "url": "https://api.example.com/d",
                "auth_type": "api_key", "api_key": "key-123",
                "api_key_header": "X-Api-Key",
            })
        assert captured["X-Api-Key"] == "key-123"

    @pytest.mark.asyncio
    async def test_bearer_missing_token(self, tool: NetworkOps) -> None:
        r = await tool.api_call({"url": "https://x.com", "auth_type": "bearer"})
        assert "需要 token" in r["error"]

    @pytest.mark.asyncio
    async def test_api_key_missing_key(self, tool: NetworkOps) -> None:
        r = await tool.api_call({"url": "https://x.com", "auth_type": "api_key"})
        assert "需要 api_key" in r["error"]

    @pytest.mark.asyncio
    async def test_missing_url(self, tool: NetworkOps) -> None:
        assert "缺少 url" in (await tool.api_call({}))["error"]

    @pytest.mark.asyncio
    async def test_http_error(self, tool: NetworkOps) -> None:
        err_resp = _mock_response(404, '{"d":"nf"}', json_data={"d": "nf"})

        async def raise_it(**kw):
            err_resp.raise_for_status()
            return err_resp

        client = _make_client(_mock_response(200))
        client.request = raise_it
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            r = await tool.api_call({"url": "https://x.com/miss"})
        assert "HTTP 404" in r["error"] and r["data"] == {"d": "nf"}

    @pytest.mark.asyncio
    async def test_retries_exhausted(self, tool: NetworkOps) -> None:
        client = _make_client(_mock_response(200))
        client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with patch("src.tools.network_ops.httpx.AsyncClient", return_value=client):
            with patch("src.tools.network_ops.asyncio.sleep", new_callable=AsyncMock):
                r = await tool.api_call({"url": "https://dead.com", "retries": 2})
        assert "重试 2 次后仍失败" in r["error"]


# ------------------------------------------------------------------
# Test: 配置 & 辅助方法
# ------------------------------------------------------------------

class TestConfigAndHelpers:

    def test_default_config(self) -> None:
        t = NetworkOps()
        assert t._timeout == NetworkOps.DEFAULT_TIMEOUT

    def test_custom_config(self) -> None:
        t = NetworkOps(config={"timeout": 60, "retries": 5, "proxy": "http://p:8080"})
        assert t._timeout == 60 and t._retries == 5

    def test_try_parse_json_valid(self) -> None:
        assert NetworkOps._try_parse_json('{"a":1}') == {"a": 1}

    def test_try_parse_json_invalid(self) -> None:
        assert NetworkOps._try_parse_json("not json") == "not json"

    def test_parse_json_response_fallback(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.json.side_effect = Exception("x")
        resp.text = "plain"
        assert NetworkOps._parse_json_response(resp) == "plain"
