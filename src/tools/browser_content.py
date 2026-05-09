"""浏览器内容提取模块。

提供 BrowserControl 的内容提取相关方法：文本、链接、HTML、快照、搜索。
从 browser_control.py 拆分而来，通过混入（Mixin）方式组合到 BrowserControl。
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger


class BrowserContentMixin:
    """浏览器内容提取混入类。

    要求宿主类具有以下属性：
        _page: Playwright Page 对象
    """

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
