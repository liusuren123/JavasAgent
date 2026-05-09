"""浏览器控制工具。

提供网页自动化、信息检索等浏览器操控能力。
基于 Playwright 实现，支持 Chromium / Firefox / WebKit。

能力：
- 打开 / 关闭网页
- 页面导航（前进、后退、刷新）
- 页面截图
- 点击元素（CSS 选择器或文本）
- 输入文本（表单填写）
- 提取页面内容（文本 / 链接 / 表格）
- 执行 JavaScript
- 等待元素出现
- 管理 Cookie
- 文件下载
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class PageSnapshot:
    """页面快照。"""

    title: str
    url: str
    text_content: str
    links: list[dict[str, str]] = field(default_factory=list)
    status_code: int = 200


class BrowserControl:
    """浏览器控制工具集。

    使用 playwright 驱动浏览器，提供页面导航、内容提取、
    表单交互等完整的浏览器自动化能力。

    Usage::

        browser = BrowserControl()
        await browser.initialize()
        result = await browser.execute("navigate", {"url": "https://example.com"})
        content = await browser.execute("extract_text", {})
        await browser.close()
    """

    def __init__(self, headless: bool = True, browser_type: str = "chromium") -> None:
        """初始化浏览器控制工具。

        Args:
            headless: 是否使用无头模式
            browser_type: 浏览器类型 (chromium / firefox / webkit)
        """
        self._headless = headless
        self._browser_type = browser_type
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._initialized = False

    async def initialize(self) -> None:
        """初始化浏览器实例。

        启动 Playwright 并创建浏览器上下文。如果 playwright 未安装，
        会优雅降级到不初始化。
        """
        if self._initialized:
            return

        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()

            launcher = {
                "chromium": self._playwright.chromium,
                "firefox": self._playwright.firefox,
                "webkit": self._playwright.webkit,
            }.get(self._browser_type, self._playwright.chromium)

            self._browser = await launcher.launch(headless=self._headless)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            self._page = await self._context.new_page()
            self._initialized = True
            logger.info(f"浏览器初始化完成: {self._browser_type}, headless={self._headless}")

        except ImportError:
            logger.warning("playwright 未安装，浏览器控制不可用。请运行: pip install playwright && playwright install")
            self._initialized = False
        except Exception as e:
            logger.error(f"浏览器初始化失败: {e}")
            self._initialized = False

    async def close(self) -> None:
        """关闭浏览器并释放资源。"""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._initialized = False
        logger.info("浏览器已关闭")

    @property
    def is_available(self) -> bool:
        """浏览器控制是否可用。"""
        return self._initialized and self._page is not None

    async def execute(self, action: str, params: dict[str, Any]) -> Any:
        """执行浏览器控制操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            操作结果字典
        """
        if not self.is_available:
            # 如果未初始化，尝试自动初始化
            await self.initialize()
            if not self.is_available:
                return {"error": "浏览器未初始化，请安装 playwright"}

        handlers = {
            "navigate": self._navigate,
            "go_back": self._go_back,
            "go_forward": self._go_forward,
            "reload": self._reload,
            "screenshot": self._screenshot,
            "click": self._click,
            "click_text": self._click_text,
            "fill": self._fill,
            "type_text": self._type_text,
            "press_key": self._press_key,
            "extract_text": self._extract_text,
            "extract_links": self._extract_links,
            "extract_html": self._extract_html,
            "evaluate_js": self._evaluate_js,
            "wait_for_selector": self._wait_for_selector,
            "get_cookies": self._get_cookies,
            "set_cookies": self._set_cookies,
            "download": self._download,
            "get_page_info": self._get_page_info,
            "snapshot": self._snapshot,
            "search": self._search,
        }

        handler = handlers.get(action)
        if handler is None:
            logger.error(f"未知操作: {action}")
            return {"error": f"未知操作: {action}，支持: {', '.join(sorted(handlers.keys()))}"}

        return await handler(params)

    # ------------------------------------------------------------------
    # 导航操作
    # ------------------------------------------------------------------

    async def _navigate(self, params: dict) -> dict:
        """导航到指定 URL。

        Params:
            url: 目标 URL
            wait_until: 等待条件 (load / domcontentloaded / networkidle，默认 load)
            timeout: 超时毫秒（默认 30000）
        """
        url = params.get("url", "")
        if not url:
            return {"error": "缺少参数: url"}

        # 自动补全协议
        if not url.startswith(("http://", "https://", "file://")):
            url = "https://" + url

        wait_until = params.get("wait_until", "load")
        timeout = params.get("timeout", 30000)

        try:
            response = await self._page.goto(url, wait_until=wait_until, timeout=timeout)
            status = response.status if response else None
            title = await self._page.title()
            logger.info(f"导航到: {url} (状态: {status})")
            return {
                "url": self._page.url,
                "title": title,
                "status": status,
            }
        except Exception as e:
            logger.error(f"导航失败: {e}")
            return {"error": f"导航失败: {e}"}

    async def _go_back(self, params: dict) -> dict:
        """后退。"""
        try:
            await self._page.go_back(timeout=params.get("timeout", 15000))
            return {"url": self._page.url, "title": await self._page.title()}
        except Exception as e:
            return {"error": f"后退失败: {e}"}

    async def _go_forward(self, params: dict) -> dict:
        """前进。"""
        try:
            await self._page.go_forward(timeout=params.get("timeout", 15000))
            return {"url": self._page.url, "title": await self._page.title()}
        except Exception as e:
            return {"error": f"前进失败: {e}"}

    async def _reload(self, params: dict) -> dict:
        """刷新页面。"""
        try:
            await self._page.reload(timeout=params.get("timeout", 30000))
            return {"url": self._page.url, "title": await self._page.title()}
        except Exception as e:
            return {"error": f"刷新失败: {e}"}

    # ------------------------------------------------------------------
    # 页面交互
    # ------------------------------------------------------------------

    async def _click(self, params: dict) -> dict:
        """点击 CSS 选择器指定的元素。

        Params:
            selector: CSS 选择器
            button: 鼠标按钮 (left / right / middle，默认 left)
            click_count: 点击次数（默认 1）
            timeout: 等待超时毫秒
        """
        selector = params.get("selector", "")
        if not selector:
            return {"error": "缺少参数: selector"}

        try:
            await self._page.click(
                selector,
                button=params.get("button", "left"),
                click_count=params.get("click_count", 1),
                timeout=params.get("timeout", 15000),
            )
            logger.info(f"点击元素: {selector}")
            return {"clicked": selector}
        except Exception as e:
            logger.error(f"点击失败: {e}")
            return {"error": f"点击失败: {e}"}

    async def _click_text(self, params: dict) -> dict:
        """点击包含指定文本的元素。

        Params:
            text: 要点击的元素文本
            timeout: 等待超时毫秒
        """
        text = params.get("text", "")
        if not text:
            return {"error": "缺少参数: text"}

        try:
            # 尝试精确匹配
            locator = self._page.get_by_text(text, exact=False)
            count = await locator.count()
            if count > 0:
                await locator.first.click(timeout=params.get("timeout", 15000))
                logger.info(f"点击文本: {text}")
                return {"clicked_text": text}
            return {"error": f"未找到包含文本「{text}」的元素"}
        except Exception as e:
            return {"error": f"点击文本失败: {e}"}

    async def _fill(self, params: dict) -> dict:
        """清空输入框并填入文本。

        Params:
            selector: CSS 选择器
            value: 要填入的值
        """
        selector = params.get("selector", "")
        value = params.get("value", "")
        if not selector:
            return {"error": "缺少参数: selector"}

        try:
            await self._page.fill(selector, value, timeout=params.get("timeout", 10000))
            logger.info(f"填写表单: {selector} = {value[:20]}...")
            return {"filled": selector, "value": value}
        except Exception as e:
            return {"error": f"填写失败: {e}"}

    async def _type_text(self, params: dict) -> dict:
        """在当前焦点元素上逐字输入文本（模拟键盘输入）。

        Params:
            text: 要输入的文本
            delay: 每个字符间的延迟（毫秒，默认 50）
        """
        text = params.get("text", "")
        if not text:
            return {"error": "缺少参数: text"}

        try:
            await self._page.keyboard.type(text, delay=params.get("delay", 50))
            logger.info(f"输入文本: {text[:20]}...")
            return {"typed": text}
        except Exception as e:
            return {"error": f"输入失败: {e}"}

    async def _press_key(self, params: dict) -> dict:
        """按下键盘按键。

        Params:
            key: 按键名称 (Enter / Tab / Escape / ArrowDown 等)
        """
        key = params.get("key", "")
        if not key:
            return {"error": "缺少参数: key"}

        try:
            await self._page.keyboard.press(key)
            logger.info(f"按下按键: {key}")
            return {"pressed": key}
        except Exception as e:
            return {"error": f"按键失败: {e}"}

    # ------------------------------------------------------------------
    # 内容提取
    # ------------------------------------------------------------------

    async def _extract_text(self, params: dict) -> dict:
        """提取页面的纯文本内容。

        Params:
            selector: 可选 CSS 选择器，提取指定元素内的文本
        """
        try:
            selector = params.get("selector")
            if selector:
                element = await self._page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                else:
                    return {"error": f"未找到元素: {selector}"}
            else:
                text = await self._page.inner_text("body")

            # 截断过长内容
            max_length = params.get("max_length", 50000)
            truncated = len(text) > max_length
            if truncated:
                text = text[:max_length] + "\n... (内容已截断)"

            logger.info(f"提取文本: {len(text)} 字符")
            return {
                "text": text,
                "length": len(text),
                "truncated": truncated,
                "url": self._page.url,
                "title": await self._page.title(),
            }
        except Exception as e:
            return {"error": f"文本提取失败: {e}"}

    async def _extract_links(self, params: dict) -> dict:
        """提取页面上的所有链接。

        Params:
            selector: 可选 CSS 选择器，限定范围
            base_url: 可选，只返回包含此前缀的链接
        """
        try:
            js_code = """
            (selector) => {
                const root = selector ? document.querySelector(selector) : document.body;
                if (!root) return [];
                const anchors = root.querySelectorAll('a[href]');
                return Array.from(anchors).map(a => ({
                    text: a.textContent.trim().substring(0, 100),
                    href: a.href,
                })).filter(l => l.href && !l.href.startsWith('javascript:'));
            }
            """
            links = await self._page.evaluate(js_code, params.get("selector"))

            base_url = params.get("base_url")
            if base_url:
                links = [l for l in links if base_url in l["href"]]

            logger.info(f"提取链接: {len(links)} 个")
            return {"links": links, "count": len(links)}
        except Exception as e:
            return {"error": f"链接提取失败: {e}"}

    async def _extract_html(self, params: dict) -> dict:
        """提取页面 HTML。

        Params:
            selector: 可选 CSS 选择器
        """
        try:
            selector = params.get("selector", "body")
            element = await self._page.query_selector(selector)
            if element:
                html = await element.inner_html()
                return {"html": html, "length": len(html)}
            return {"error": f"未找到元素: {selector}"}
        except Exception as e:
            return {"error": f"HTML 提取失败: {e}"}

    # ------------------------------------------------------------------
    # 高级功能
    # ------------------------------------------------------------------

    async def _evaluate_js(self, params: dict) -> dict:
        """执行 JavaScript 表达式。

        Params:
            expression: JavaScript 表达式
            arg: 传递给表达式的参数（可选）
        """
        expression = params.get("expression", "")
        if not expression:
            return {"error": "缺少参数: expression"}

        try:
            arg = params.get("arg")
            result = await self._page.evaluate(expression, arg)
            # 尝试序列化结果
            try:
                serialized = json.dumps(result, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                serialized = str(result)

            logger.info(f"JS 执行完成: {expression[:50]}...")
            return {"result": result, "serialized": serialized}
        except Exception as e:
            return {"error": f"JS 执行失败: {e}"}

    async def _wait_for_selector(self, params: dict) -> dict:
        """等待元素出现。

        Params:
            selector: CSS 选择器
            state: 等待状态 (attached / detached / visible / hidden，默认 visible)
            timeout: 超时毫秒（默认 30000）
        """
        selector = params.get("selector", "")
        if not selector:
            return {"error": "缺少参数: selector"}

        try:
            await self._page.wait_for_selector(
                selector,
                state=params.get("state", "visible"),
                timeout=params.get("timeout", 30000),
            )
            return {"found": True, "selector": selector}
        except Exception as e:
            return {"error": f"等待超时: {e}"}

    async def _screenshot(self, params: dict) -> dict:
        """页面截图。

        Params:
            path: 保存路径（可选，不提供则返回 base64）
            full_page: 是否全页截图（默认 False）
            selector: 可选，只截指定元素
        """
        try:
            save_path = params.get("path")
            full_page = params.get("full_page", False)
            selector = params.get("selector")

            kwargs: dict[str, Any] = {"full_page": full_page, "type": "png"}

            if save_path:
                path = Path(save_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                kwargs["path"] = str(path)

            if selector:
                element = await self._page.query_selector(selector)
                if element:
                    screenshot_bytes = await element.screenshot(type="png")
                    if save_path:
                        Path(save_path).write_bytes(screenshot_bytes)
                else:
                    return {"error": f"未找到元素: {selector}"}
            else:
                screenshot_bytes = await self._page.screenshot(**kwargs)

            import base64

            b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            logger.info(f"截图完成: {len(screenshot_bytes)} bytes")
            return {
                "size": len(screenshot_bytes),
                "base64": b64[:100] + "..." if not save_path else None,
                "path": str(save_path) if save_path else None,
            }
        except Exception as e:
            return {"error": f"截图失败: {e}"}

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

    async def _snapshot(self, params: dict) -> dict:
        """获取页面快照（文本 + 链接 + 元信息）。

        一次性获取页面的关键信息，适合 Agent 快速了解页面状态。

        Params:
            max_text_length: 文本最大长度（默认 10000）
        """
        try:
            title = await self._page.title()
            url = self._page.url

            # 提取文本
            text = await self._page.inner_text("body")
            max_len = params.get("max_text_length", 10000)
            text_truncated = len(text) > max_len
            if text_truncated:
                text = text[:max_len]

            # 提取链接
            js_code = """
            () => {
                const anchors = document.querySelectorAll('a[href]');
                return Array.from(anchors).slice(0, 50).map(a => ({
                    text: a.textContent.trim().substring(0, 80),
                    href: a.href,
                })).filter(l => l.href && !l.href.startsWith('javascript:'));
            }
            """
            links = await self._page.evaluate(js_code)

            logger.info(f"页面快照: {title} ({len(text)} 字符, {len(links)} 链接)")
            return {
                "title": title,
                "url": url,
                "text": text,
                "text_truncated": text_truncated,
                "links": links,
                "link_count": len(links),
            }
        except Exception as e:
            return {"error": f"快照失败: {e}"}

    async def _search(self, params: dict) -> dict:
        """搜索引擎搜索。

        Params:
            query: 搜索关键词
            engine: 搜索引擎 (google / bing / baidu，默认 bing)
            max_results: 最多返回结果数（默认 10）
        """
        query = params.get("query", "")
        if not query:
            return {"error": "缺少参数: query"}

        engine = params.get("engine", "bing")
        max_results = params.get("max_results", 10)

        engine_urls = {
            "google": "https://www.google.com/search?q=",
            "bing": "https://www.bing.com/search?q=",
            "baidu": "https://www.baidu.com/s?wd=",
        }

        base_url = engine_urls.get(engine, engine_urls["bing"])
        search_url = base_url + query

        try:
            await self._page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            # 等待搜索结果加载
            await self._page.wait_for_timeout(1000)

            # 提取搜索结果
            js_code = """
            (maxResults) => {
                const results = [];
                // 通用搜索结果选择器
                const selectors = [
                    'div.g',           // Google
                    'li.b_algo',       // Bing
                    'div.result',      // Baidu
                    'div.c-container', // Baidu alternative
                ];

                for (const sel of selectors) {
                    const items = document.querySelectorAll(sel);
                    for (const item of items) {
                        if (results.length >= maxResults) break;
                        const titleEl = item.querySelector('h2 a, h3 a, a.tzg6eb, a[title]');
                        const snippetEl = item.querySelector('.VwiC3b, .b_caption p, .c-abstract, .content-right_8Zs40');

                        if (titleEl) {
                            results.push({
                                title: titleEl.textContent.trim().substring(0, 100),
                                url: titleEl.href,
                                snippet: snippetEl ? snippetEl.textContent.trim().substring(0, 200) : '',
                            });
                        }
                    }
                    if (results.length >= maxResults) break;
                }
                return results;
            }
            """
            results = await self._page.evaluate(js_code, max_results)

            logger.info(f"搜索完成: '{query}' ({engine}), {len(results)} 条结果")
            return {
                "query": query,
                "engine": engine,
                "results": results[:max_results],
                "count": len(results),
            }
        except Exception as e:
            return {"error": f"搜索失败: {e}"}
