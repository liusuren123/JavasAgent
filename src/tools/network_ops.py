"""网络操作工具。

提供 HTTP 请求、文件下载、网络状态检测、API 调用封装能力。
基于 httpx 异步客户端实现。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable

import httpx
from loguru import logger

from src.utils.path_safety import safe_resolve_path, PathSafetyError


class NetworkOps:
    """网络操作工具集。

    支持: http_get / http_post / http_put / http_delete /
          download_file / check_connectivity / api_call

    Usage::

        net = NetworkOps()
        result = await net.execute("http_get", {"url": "https://httpbin.org/get"})
        result = await net.execute("download_file", {"url": "...", "save_path": "f.zip"})
        result = await net.execute("api_call", {"url": "...", "method": "POST", "json": {}})
    """

    DEFAULT_TIMEOUT: float = 30.0
    DEFAULT_RETRIES: int = 3
    DEFAULT_RETRY_DELAY: float = 1.0
    CHUNK_SIZE: int = 8192

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._timeout = self._config.get("timeout", self.DEFAULT_TIMEOUT)
        self._retries = self._config.get("retries", self.DEFAULT_RETRIES)
        self._retry_delay = self._config.get("retry_delay", self.DEFAULT_RETRY_DELAY)
        self._default_headers = self._config.get("default_headers", {})
        self._proxy = self._config.get("proxy", None)
        self._download_workspace = Path(
            self._config.get("download_workspace", ".")
        ).resolve()

        self._actions: dict[str, Callable[..., Any]] = {
            "http_get": self.http_get,
            "http_post": self.http_post,
            "http_put": self.http_put,
            "http_delete": self.http_delete,
            "download_file": self.download_file,
            "check_connectivity": self.check_connectivity,
            "api_call": self.api_call,
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行网络操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            操作结果字典
        """
        handler = self._actions.get(action)
        if handler is None:
            logger.error(f"未知网络操作: {action}")
            return {"error": f"未知操作: {action}，支持: {', '.join(self._actions.keys())}"}

        try:
            return await handler(params)
        except httpx.TimeoutException as exc:
            return {"error": f"请求超时: {exc}"}
        except httpx.ConnectError as exc:
            return {"error": f"连接失败: {exc}"}
        except httpx.HTTPStatusError as exc:
            return {
                "error": f"HTTP {exc.response.status_code}",
                "status_code": exc.response.status_code,
                "body": self._safe_body(exc.response),
            }
        except PathSafetyError as exc:
            return {"error": f"路径安全违规: {exc}"}
        except Exception as exc:
            logger.exception(f"网络操作异常: {exc}")
            return {"error": f"操作失败: {exc}"}

    # ------------------------------------------------------------------
    # HTTP GET
    # ------------------------------------------------------------------

    async def http_get(self, params: dict[str, Any]) -> dict[str, Any]:
        """HTTP GET 请求。支持 headers, params, timeout, retries, follow_redirects。"""
        url = params.get("url", "")
        if not url:
            return {"error": "缺少 url 参数"}
        return await self._do_request(
            method="GET", url=url,
            headers=params.get("headers"), query_params=params.get("params"),
            timeout=params.get("timeout", self._timeout),
            retries=params.get("retries", self._retries),
            follow_redirects=params.get("follow_redirects", True),
        )

    # ------------------------------------------------------------------
    # HTTP POST
    # ------------------------------------------------------------------

    async def http_post(self, params: dict[str, Any]) -> dict[str, Any]:
        """HTTP POST 请求。额外支持 body / json 参数。"""
        url = params.get("url", "")
        if not url:
            return {"error": "缺少 url 参数"}
        return await self._do_request(
            method="POST", url=url,
            headers=params.get("headers"), query_params=params.get("params"),
            body=params.get("body"), json_body=params.get("json"),
            timeout=params.get("timeout", self._timeout),
            retries=params.get("retries", self._retries),
            follow_redirects=params.get("follow_redirects", True),
        )

    # ------------------------------------------------------------------
    # HTTP PUT
    # ------------------------------------------------------------------

    async def http_put(self, params: dict[str, Any]) -> dict[str, Any]:
        """HTTP PUT 请求。参数同 http_post。"""
        url = params.get("url", "")
        if not url:
            return {"error": "缺少 url 参数"}
        return await self._do_request(
            method="PUT", url=url,
            headers=params.get("headers"), query_params=params.get("params"),
            body=params.get("body"), json_body=params.get("json"),
            timeout=params.get("timeout", self._timeout),
            retries=params.get("retries", self._retries),
            follow_redirects=params.get("follow_redirects", True),
        )

    # ------------------------------------------------------------------
    # HTTP DELETE
    # ------------------------------------------------------------------

    async def http_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        """HTTP DELETE 请求。"""
        url = params.get("url", "")
        if not url:
            return {"error": "缺少 url 参数"}
        return await self._do_request(
            method="DELETE", url=url,
            headers=params.get("headers"), query_params=params.get("params"),
            timeout=params.get("timeout", self._timeout),
            retries=params.get("retries", self._retries),
            follow_redirects=params.get("follow_redirects", True),
        )

    # ------------------------------------------------------------------
    # 文件下载
    # ------------------------------------------------------------------

    async def download_file(self, params: dict[str, Any]) -> dict[str, Any]:
        """下载文件，支持断点续传和大小校验。

        Args:
            params: url, save_path, headers, timeout,
                    verify_size, expected_size, on_progress
        """
        url = params.get("url", "")
        save_path = params.get("save_path", "")
        if not url:
            return {"error": "缺少 url 参数"}
        if not save_path:
            return {"error": "缺少 save_path 参数"}

        try:
            target = safe_resolve_path(
                self._download_workspace, save_path, allow_create_parents=True,
            )
        except PathSafetyError as exc:
            return {"error": f"路径安全违规: {exc}"}

        headers = dict(self._default_headers)
        if extra := params.get("headers"):
            headers.update(extra)

        timeout = params.get("timeout", self._timeout)
        on_progress: Callable | None = params.get("on_progress")
        verify_size = params.get("verify_size", True)
        expected_size = params.get("expected_size")

        # 断点续传：检测已有文件大小
        resume_from = 0
        if target.exists() and target.is_file():
            resume_from = target.stat().st_size
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"
                logger.info(f"断点续传: 已有 {resume_from} 字节")

        start_time = time.monotonic()
        total_size: int | None = None
        downloaded = resume_from

        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True, proxy=self._proxy,
            ) as client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resume_from > 0 and resp.status_code != 206:
                        resume_from = 0
                        downloaded = 0
                        logger.info("服务器不支持断点续传，重新下载")

                    resp.raise_for_status()

                    cl = resp.headers.get("content-length")
                    if cl:
                        if resume_from > 0 and resp.status_code == 206:
                            total_size = resume_from + int(cl)
                        else:
                            total_size = int(cl)

                    mode = "ab" if resume_from > 0 and resp.status_code == 206 else "wb"
                    with open(target, mode) as f:
                        async for chunk in resp.aiter_bytes(self.CHUNK_SIZE):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if on_progress:
                                on_progress(downloaded, total_size)

        except httpx.TimeoutException as exc:
            return {"error": f"下载超时: {exc}", "partial_path": str(target)}
        except httpx.ConnectError as exc:
            return {"error": f"下载连接失败: {exc}"}
        except Exception as exc:
            return {"error": f"下载失败: {exc}", "partial_path": str(target)}

        elapsed = time.monotonic() - start_time
        actual_size = target.stat().st_size if target.exists() else 0

        if verify_size and expected_size is not None and actual_size != expected_size:
            return {
                "error": f"文件大小不匹配: 实际 {actual_size}，预期 {expected_size}",
                "save_path": str(target), "size_bytes": actual_size,
            }

        logger.info(f"下载完成: {url} -> {target} ({actual_size} bytes, {elapsed:.2f}s)")
        return {
            "success": True, "save_path": str(target),
            "size_bytes": actual_size,
            "elapsed_seconds": round(elapsed, 3),
            "resumed": resume_from > 0,
        }

    # ------------------------------------------------------------------
    # 网络连通性检测
    # ------------------------------------------------------------------

    async def check_connectivity(self, params: dict[str, Any]) -> dict[str, Any]:
        """检测网络连通性。

        Args:
            params: url (optional, 默认检测多个公共端点), timeout

        Returns:
            connected, latency_ms, target 等信息
        """
        url = params.get("url")
        timeout = params.get("timeout", 10.0)
        test_urls = [url] if url else [
            "https://www.baidu.com",
            "https://www.google.com",
            "https://1.1.1.1",
        ]

        results: list[dict[str, Any]] = []
        overall_connected = False

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for test_url in test_urls:
                r = await self._ping_url(client, test_url, timeout)
                results.append(r)
                if r.get("connected"):
                    overall_connected = True

        if url:
            return results[0]
        return {"connected": overall_connected, "targets": results}

    async def _ping_url(
        self, client: httpx.AsyncClient, url: str, timeout: float,
    ) -> dict[str, Any]:
        """检测单个 URL 连通性。"""
        start = time.monotonic()
        try:
            resp = await client.head(url)
            latency = (time.monotonic() - start) * 1000
            return {
                "connected": True, "target": url,
                "status_code": resp.status_code,
                "latency_ms": round(latency, 1),
            }
        except httpx.TimeoutException:
            return {"connected": False, "target": url,
                    "latency_ms": round((time.monotonic() - start) * 1000, 1),
                    "error": "超时"}
        except Exception as exc:
            return {"connected": False, "target": url,
                    "latency_ms": round((time.monotonic() - start) * 1000, 1),
                    "error": str(exc)}

    # ------------------------------------------------------------------
    # API 调用封装
    # ------------------------------------------------------------------

    async def api_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """统一 API 调用封装，自动处理 JSON 和认证。

        Args:
            params: url, method, json, headers, params,
                    auth_type (bearer/api_key/none),
                    token, api_key, api_key_header,
                    timeout, retries
        """
        url = params.get("url", "")
        if not url:
            return {"error": "缺少 url 参数"}

        method = params.get("method", "GET").upper()
        auth_type = params.get("auth_type", "none")
        timeout = params.get("timeout", self._timeout)
        retries = params.get("retries", self._retries)

        headers = dict(self._default_headers)
        headers["Accept"] = "application/json"
        if extra := params.get("headers"):
            headers.update(extra)

        if auth_type == "bearer":
            token = params.get("token", "")
            if not token:
                return {"error": "bearer 认证需要 token 参数"}
            headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            api_key = params.get("api_key", "")
            if not api_key:
                return {"error": "api_key 认证需要 api_key 参数"}
            headers[params.get("api_key_header", "X-API-Key")] = api_key

        json_body = params.get("json")
        if json_body is not None:
            headers.setdefault("Content-Type", "application/json")

        start = time.monotonic()
        last_exc: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout, follow_redirects=True, proxy=self._proxy,
                ) as client:
                    resp = await client.request(
                        method=method, url=url, headers=headers,
                        params=params.get("params"), json=json_body,
                    )
                    resp.raise_for_status()
                    elapsed = time.monotonic() - start
                    data = self._parse_json_response(resp)
                    logger.info(f"API 调用成功: {method} {url} -> {resp.status_code}")
                    return {
                        "success": True, "status_code": resp.status_code,
                        "headers": dict(resp.headers), "data": data,
                        "elapsed_seconds": round(elapsed, 3),
                    }
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(self._retry_delay * attempt)
                continue
            except httpx.HTTPStatusError as exc:
                elapsed = time.monotonic() - start
                body = self._safe_body(exc.response)
                return {
                    "error": f"HTTP {exc.response.status_code}",
                    "status_code": exc.response.status_code,
                    "data": self._try_parse_json(body),
                    "elapsed_seconds": round(elapsed, 3),
                }

        return {"error": f"重试 {retries} 次后仍失败: {last_exc}",
                "elapsed_seconds": round(time.monotonic() - start, 3)}

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    async def _do_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        body: Any = None,
        json_body: Any = None,
        timeout: float | None = None,
        retries: int = 1,
        follow_redirects: bool = True,
    ) -> dict[str, Any]:
        """执行 HTTP 请求（带重试）。"""
        merged_headers = dict(self._default_headers)
        if headers:
            merged_headers.update(headers)

        actual_timeout = timeout or self._timeout
        last_exc: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=actual_timeout,
                    follow_redirects=follow_redirects,
                    proxy=self._proxy,
                ) as client:
                    resp = await client.request(
                        method=method, url=url,
                        headers=merged_headers,
                        params=query_params,
                        content=body, json=json_body,
                    )
                    resp.raise_for_status()
                    return {
                        "success": True,
                        "status_code": resp.status_code,
                        "headers": dict(resp.headers),
                        "body": self._safe_body(resp),
                    }
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(self._retry_delay * attempt)
                continue
            except httpx.HTTPStatusError:
                raise

        raise last_exc or httpx.ConnectError("未知连接错误")

    @staticmethod
    def _safe_body(response: httpx.Response) -> str:
        """安全获取响应体文本。"""
        try:
            return response.text
        except Exception:
            return ""

    @staticmethod
    def _parse_json_response(response: httpx.Response) -> Any:
        """解析 JSON 响应体，失败返回原始文本。"""
        try:
            return response.json()
        except Exception:
            return response.text

    @staticmethod
    def _try_parse_json(text: str) -> Any:
        """尝试将文本解析为 JSON。"""
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
