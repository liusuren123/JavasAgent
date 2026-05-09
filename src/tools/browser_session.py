"""浏览器会话管理模块。

提供 BrowserControl 的 Cookie 管理、文件下载、页面信息获取等会话级操作。
从 browser_control.py 拆分而来，通过混入（Mixin）方式组合到 BrowserControl。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger


class BrowserSessionMixin:
    """浏览器会话管理混入类。

    要求宿主类具有以下属性：
        _page: Playwright Page 对象
        _context: Playwright BrowserContext 对象
    """

    async def _get_cookies(self, params: dict) -> dict:
        """获取当前页面的 Cookie。"""
        try:
            cookies = await self._context.cookies()
            return {"cookies": cookies, "count": len(cookies)}
        except Exception as e:
            return {"error": f"获取 Cookie 失败: {e}"}

    async def _set_cookies(self, params: dict) -> dict:
        """设置 Cookie。

        Params:
            cookies: Cookie 列表，格式同 Playwright
                [{"name": "key", "value": "val", "url": "https://..."}]
        """
        cookies = params.get("cookies", [])
        if not cookies:
            return {"error": "缺少参数: cookies"}

        try:
            await self._context.add_cookies(cookies)
            logger.info(f"设置 {len(cookies)} 个 Cookie")
            return {"set": len(cookies)}
        except Exception as e:
            return {"error": f"设置 Cookie 失败: {e}"}

    async def _download(self, params: dict) -> dict:
        """下载文件。

        Params:
            url: 文件 URL
            save_path: 保存路径
            timeout: 超时毫秒（默认 60000）
        """
        url = params.get("url", "")
        save_path = params.get("save_path", "")
        if not url or not save_path:
            return {"error": "缺少参数: url 或 save_path"}

        try:
            # 使用 page.evaluate 传参，避免 JS 注入
            async with self._page.expect_download(timeout=params.get("timeout", 60000)) as download_info:
                await self._page.evaluate("url => window.location.href = url", url)
            download = await download_info.value

            dest = Path(save_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            await download.save_as(str(dest))

            logger.info(f"下载完成: {dest} ({dest.stat().st_size} bytes)")
            return {
                "path": str(dest),
                "size": dest.stat().st_size,
                "suggested_filename": download.suggested_filename,
            }
        except Exception as e:
            return {"error": f"下载失败: {e}"}

    async def _get_page_info(self, params: dict) -> dict:
        """获取当前页面基本信息。"""
        try:
            return {
                "url": self._page.url,
                "title": await self._page.title(),
                "viewport": self._page.viewport_size,
            }
        except Exception as e:
            return {"error": f"获取页面信息失败: {e}"}
