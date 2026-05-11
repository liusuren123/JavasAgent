"""T-TL-05: NetworkOps 网络请求 — 实操测试。

真实调用 httpx 发送 HTTP 请求。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.tools.network_ops import NetworkOps


@pytest.fixture
def net():
    return NetworkOps()


@pytest.mark.asyncio
async def test_http_get(net):
    """HTTP GET 请求 httpbin.org。"""
    result = await net.execute("http_get", {
        "url": "https://httpbin.org/get",
        "timeout": 15.0,
    })

    assert "error" not in result, f"请求失败: {result.get('error')}"
    assert result["success"] is True
    assert result["status_code"] == 200
    assert "body" in result

    # httpbin.org/get 返回 JSON，包含 url 字段
    body = json.loads(result["body"])
    assert "url" in body
    print(f"[OK] HTTP GET: status={result['status_code']}, url={body['url']}")


@pytest.mark.asyncio
async def test_http_get_with_params(net):
    """HTTP GET 带查询参数。"""
    result = await net.execute("http_get", {
        "url": "https://httpbin.org/get",
        "params": {"foo": "bar", "test": "123"},
        "timeout": 15.0,
    })

    assert result["success"] is True
    body = json.loads(result["body"])
    assert body.get("args", {}).get("foo") == "bar"
    print(f"[OK] GET 带参数: args={body.get('args')}")


@pytest.mark.asyncio
async def test_http_post(net):
    """HTTP POST 请求。"""
    result = await net.execute("http_post", {
        "url": "https://httpbin.org/post",
        "json": {"key": "value"},
        "timeout": 15.0,
    })

    assert result["success"] is True
    assert result["status_code"] == 200
    body = json.loads(result["body"])
    assert body.get("json") == {"key": "value"}
    print(f"[OK] HTTP POST: json={body.get('json')}")


@pytest.mark.asyncio
async def test_check_connectivity(net):
    """网络连通性检测。"""
    result = await net.execute("check_connectivity", {
        "url": "https://httpbin.org/get",
        "timeout": 10.0,
    })

    assert result.get("connected") is True
    assert "latency_ms" in result
    print(f"[OK] 连通性: connected={result['connected']}, latency={result['latency_ms']}ms")


@pytest.mark.asyncio
async def test_unknown_action(net):
    """未知操作应返回错误。"""
    result = await net.execute("nonexistent", {})
    assert "error" in result
    assert "未知操作" in result["error"]
    print(f"[OK] 未知操作错误: {result['error'][:50]}")


@pytest.mark.asyncio
async def test_missing_url(net):
    """缺少 url 应返回错误。"""
    result = await net.execute("http_get", {})
    assert "error" in result
    assert "缺少" in result["error"]
    print(f"[OK] 缺少 url: {result['error']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
