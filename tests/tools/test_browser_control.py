"""BrowserControl 工具测试。

覆盖导航、页面交互、内容提取、搜索等核心功能。
所有 LLM/Playwright 交互均 mock。
"""

from __future__ import annotations

import pytest

from src.tools.browser_control import BrowserControl, PageSnapshot


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class FakePage:
    """模拟 Playwright Page 对象。"""

    def __init__(self) -> None:
        self.url = "https://example.com"
        self._title = "Example Domain"
        self._content = "<html><body><h1>Example</h1></body></html>"
        self._text = "Example\nMore information..."
        self._cookies: list[dict] = []
        self._eval_results: dict[str, object] = {}
        # keyboard mock
        self.keyboard = FakeKeyboard()

    async def title(self) -> str:
        return self._title

    @property
    def viewport_size(self) -> dict:
        return {"width": 1280, "height": 720}

    async def goto(self, url: str, **kwargs) -> None:
        self.url = url
        return None  # fake Response

    async def go_back(self, **kwargs) -> None:
        self.url = "https://example.com/previous"
        return None

    async def go_forward(self, **kwargs) -> None:
        self.url = "https://example.com/next"
        return None

    async def reload(self, **kwargs) -> None:
        return None

    async def click(self, selector: str, **kwargs) -> None:
        if "not-exist" in selector:
            raise Exception(f"Element not found: {selector}")

    async def fill(self, selector: str, value: str, **kwargs) -> None:
        if "not-exist" in selector:
            raise Exception(f"Element not found: {selector}")

    async def inner_text(self, selector: str = "") -> str:
        if selector == "body" or selector == "":
            return self._text
        return "text content"

    async def query_selector(self, selector: str):
        if "not-exist" in selector:
            return None
        return FakeElement("element text content")

    async def inner_html(self) -> str:
        return self._content

    async def evaluate(self, expression, arg=None):
        if callable(expression):
            return expression(arg)
        # Return the default eval result for any JS expression string
        return self._eval_results.get("__default_links", [])

    async def wait_for_selector(self, selector: str, **kwargs) -> None:
        if "never-appear" in selector:
            raise Exception("Timeout waiting for selector")

    async def screenshot(self, **kwargs) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    async def wait_for_timeout(self, ms: int) -> None:
        pass

    def get_by_text(self, text: str, exact: bool = False):
        return FakeLocator(text)


class FakeLocator:
    def __init__(self, text: str) -> None:
        self._text = text
        self._count = 1

    async def count(self) -> int:
        return self._count

    @property
    def first(self):
        return self

    async def click(self, **kwargs) -> None:
        if self._text == "not-exist":
            raise Exception("Element not found")


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self._page = page
        self._cookies: list[dict] = []

    async def cookies(self) -> list[dict]:
        return self._cookies

    async def add_cookies(self, cookies: list[dict]) -> None:
        self._cookies.extend(cookies)


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    async def new_context(self, **kwargs):
        return FakeContext(self._page)

    async def close(self) -> None:
        pass


class FakePlaywright:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    @property
    def chromium(self):
        return FakeLauncher(self._page)

    async def stop(self) -> None:
        pass


class FakeLauncher:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    async def launch(self, **kwargs):
        return FakeBrowser(self._page)


class FakeKeyboard:
    """模拟 Playwright Keyboard 对象。"""

    def __init__(self) -> None:
        self._typed: list[str] = []
        self._pressed: list[str] = []

    async def type(self, text: str, **kwargs) -> None:
        self._typed.append(text)

    async def press(self, key: str) -> None:
        self._pressed.append(key)


class FakeElement:
    """模拟 Playwright ElementHandle。"""

    def __init__(self, text: str = "element text") -> None:
        self._text = text

    async def inner_text(self) -> str:
        return self._text

    async def inner_html(self) -> str:
        return f"<span>{self._text}</span>"

    async def screenshot(self, **kwargs) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 50


def _make_initialized_browser() -> tuple[BrowserControl, FakePage]:
    """创建一个已初始化的 BrowserControl 和对应 FakePage。"""
    browser = BrowserControl()
    page = FakePage()
    browser._initialized = True
    browser._page = page
    browser._context = FakeContext(page)
    return browser, page


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

class TestInitialize:

    async def test_not_available_before_init(self):
        bc = BrowserControl()
        assert not bc.is_available

    async def test_not_initialized_returns_unavailable_error(self):
        bc = BrowserControl()
        # Mock initialize to fail
        bc._initialized = False
        result = await bc.execute("navigate", {"url": "https://example.com"})
        # After auto-init attempt, should return error since playwright not installed
        # (it will try to import playwright and fail in test env)
        assert "error" in result or "url" in result


# ---------------------------------------------------------------------------
# 导航
# ---------------------------------------------------------------------------

class TestNavigate:

    async def test_navigate_success(self):
        bc, page = _make_initialized_browser()
        result = await bc._navigate({"url": "https://example.com"})
        assert "url" in result
        assert result["url"] == "https://example.com"

    async def test_navigate_auto_prepends_https(self):
        bc, page = _make_initialized_browser()
        result = await bc._navigate({"url": "example.com"})
        assert result["url"] == "https://example.com"

    async def test_navigate_missing_url(self):
        bc, _ = _make_initialized_browser()
        result = await bc._navigate({})
        assert "error" in result

    async def test_navigate_http_preserved(self):
        bc, page = _make_initialized_browser()
        result = await bc._navigate({"url": "http://localhost:3000"})
        assert result["url"] == "http://localhost:3000"


class TestGoBack:

    async def test_go_back(self):
        bc, _ = _make_initialized_browser()
        result = await bc._go_back({})
        assert "url" in result

    async def test_go_forward(self):
        bc, _ = _make_initialized_browser()
        result = await bc._go_forward({})
        assert "url" in result

    async def test_reload(self):
        bc, _ = _make_initialized_browser()
        result = await bc._reload({})
        assert "url" in result


# ---------------------------------------------------------------------------
# 页面交互
# ---------------------------------------------------------------------------

class TestClick:

    async def test_click_success(self):
        bc, _ = _make_initialized_browser()
        result = await bc._click({"selector": "button#submit"})
        assert result["clicked"] == "button#submit"

    async def test_click_missing_selector(self):
        bc, _ = _make_initialized_browser()
        result = await bc._click({})
        assert "error" in result

    async def test_click_element_not_found(self):
        bc, _ = _make_initialized_browser()
        result = await bc._click({"selector": "not-exist"})
        assert "error" in result


class TestClickText:

    async def test_click_text_success(self):
        bc, _ = _make_initialized_browser()
        result = await bc._click_text({"text": "Submit"})
        assert result["clicked_text"] == "Submit"

    async def test_click_text_missing_text(self):
        bc, _ = _make_initialized_browser()
        result = await bc._click_text({})
        assert "error" in result

    async def test_click_text_not_found(self):
        bc, _ = _make_initialized_browser()
        # Override locator count to 0
        page = bc._page
        bc._page.get_by_text = lambda text, exact=False: FakeLocator("not-exist")
        # FakeLocator with text "not-exist" will raise on click
        loc = FakeLocator("not-exist")
        loc._count = 0
        bc._page.get_by_text = lambda text, exact=False: loc
        result = await bc._click_text({"text": "not-exist"})
        assert "error" in result


class TestFill:

    async def test_fill_success(self):
        bc, _ = _make_initialized_browser()
        result = await bc._fill({"selector": "input#name", "value": "test"})
        assert result["filled"] == "input#name"

    async def test_fill_missing_selector(self):
        bc, _ = _make_initialized_browser()
        result = await bc._fill({})
        assert "error" in result

    async def test_fill_not_found(self):
        bc, _ = _make_initialized_browser()
        result = await bc._fill({"selector": "not-exist", "value": "test"})
        assert "error" in result


class TestTypeText:

    async def test_type_text_success(self):
        bc, _ = _make_initialized_browser()
        result = await bc._type_text({"text": "hello"})
        assert result["typed"] == "hello"

    async def test_type_text_missing(self):
        bc, _ = _make_initialized_browser()
        result = await bc._type_text({})
        assert "error" in result


class TestPressKey:

    async def test_press_key_success(self):
        bc, _ = _make_initialized_browser()
        result = await bc._press_key({"key": "Enter"})
        assert result["pressed"] == "Enter"

    async def test_press_key_missing(self):
        bc, _ = _make_initialized_browser()
        result = await bc._press_key({})
        assert "error" in result


# ---------------------------------------------------------------------------
# 内容提取
# ---------------------------------------------------------------------------

class TestExtractText:

    async def test_extract_text(self):
        bc, _ = _make_initialized_browser()
        result = await bc._extract_text({})
        assert "text" in result
        assert result["length"] > 0

    async def test_extract_text_with_selector(self):
        bc, _ = _make_initialized_browser()
        result = await bc._extract_text({"selector": "h1"})
        assert "text" in result

    async def test_extract_text_selector_not_found(self):
        bc, _ = _make_initialized_browser()
        result = await bc._extract_text({"selector": "not-exist"})
        assert "error" in result


class TestExtractLinks:

    async def test_extract_links(self):
        bc, page = _make_initialized_browser()
        page._eval_results["__default_links"] = [
            {"text": "Link1", "href": "https://example.com/1"},
            {"text": "Link2", "href": "https://example.com/2"},
        ]
        result = await bc._extract_links({})
        assert "links" in result

    async def test_extract_links_with_base_url_filter(self):
        bc, page = _make_initialized_browser()
        page._eval_results["__default_links"] = [
            {"text": "Internal", "href": "https://example.com/1"},
            {"text": "External", "href": "https://other.com/1"},
        ]
        result = await bc._extract_links({"base_url": "example.com"})
        assert result["count"] == 1


class TestExtractHtml:

    async def test_extract_html(self):
        bc, _ = _make_initialized_browser()
        result = await bc._extract_html({"selector": "body"})
        assert "html" in result

    async def test_extract_html_not_found(self):
        bc, _ = _make_initialized_browser()
        result = await bc._extract_html({"selector": "not-exist"})
        assert "error" in result


# ---------------------------------------------------------------------------
# 高级功能
# ---------------------------------------------------------------------------

class TestEvaluateJs:

    async def test_evaluate_js_success(self):
        bc, page = _make_initialized_browser()
        page._eval_results["1+1"] = 2
        result = await bc._evaluate_js({"expression": "1+1"})
        assert "result" in result

    async def test_evaluate_js_missing_expression(self):
        bc, _ = _make_initialized_browser()
        result = await bc._evaluate_js({})
        assert "error" in result


class TestWaitForSelector:

    async def test_wait_for_selector(self):
        bc, _ = _make_initialized_browser()
        result = await bc._wait_for_selector({"selector": "div.content"})
        assert result["found"] is True

    async def test_wait_for_selector_timeout(self):
        bc, _ = _make_initialized_browser()
        result = await bc._wait_for_selector({"selector": "never-appear"})
        assert "error" in result

    async def test_wait_for_selector_missing(self):
        bc, _ = _make_initialized_browser()
        result = await bc._wait_for_selector({})
        assert "error" in result


class TestScreenshot:

    async def test_screenshot(self):
        bc, _ = _make_initialized_browser()
        result = await bc._screenshot({})
        assert "size" in result
        assert result["size"] > 0


class TestCookies:

    async def test_get_cookies(self):
        bc, _ = _make_initialized_browser()
        result = await bc._get_cookies({})
        assert "cookies" in result
        assert "count" in result

    async def test_set_cookies(self):
        bc, _ = _make_initialized_browser()
        cookies = [{"name": "session", "value": "abc", "url": "https://example.com"}]
        result = await bc._set_cookies({"cookies": cookies})
        assert result["set"] == 1

    async def test_set_cookies_missing(self):
        bc, _ = _make_initialized_browser()
        result = await bc._set_cookies({})
        assert "error" in result


class TestGetPageInfo:

    async def test_get_page_info(self):
        bc, _ = _make_initialized_browser()
        result = await bc._get_page_info({})
        assert "url" in result
        assert "title" in result


class TestSnapshot:

    async def test_snapshot(self):
        bc, page = _make_initialized_browser()
        page._eval_results["__default_links"] = []
        result = await bc._snapshot({})
        assert "title" in result
        assert "url" in result
        assert "text" in result

    async def test_snapshot_truncation(self):
        bc, page = _make_initialized_browser()
        page._text = "x" * 20000
        page._eval_results["__default_links"] = []
        result = await bc._snapshot({"max_text_length": 1000})
        assert result["text_truncated"] is True


class TestSearch:

    async def test_search(self):
        bc, page = _make_initialized_browser()
        page._eval_results["__default_links"] = [
            {"title": "Result 1", "url": "https://example.com", "snippet": "test"},
        ]
        result = await bc._search({"query": "test query"})
        assert "results" in result
        assert result["query"] == "test query"

    async def test_search_missing_query(self):
        bc, _ = _make_initialized_browser()
        result = await bc._search({})
        assert "error" in result


# ---------------------------------------------------------------------------
# Execute dispatch
# ---------------------------------------------------------------------------

class TestExecuteDispatch:

    async def test_unknown_action(self):
        bc, _ = _make_initialized_browser()
        result = await bc.execute("nonexistent_action", {})
        assert "error" in result
        assert "未知操作" in result["error"]

    async def test_close(self):
        bc, _ = _make_initialized_browser()
        await bc.close()
        assert not bc.is_available


# ---------------------------------------------------------------------------
# PageSnapshot
# ---------------------------------------------------------------------------

class TestPageSnapshot:

    def test_default_values(self):
        snap = PageSnapshot(title="Test", url="https://example.com", text_content="hello")
        assert snap.title == "Test"
        assert snap.links == []
        assert snap.status_code == 200

    def test_custom_values(self):
        links = [{"text": "Link", "href": "https://example.com"}]
        snap = PageSnapshot(
            title="Test",
            url="https://example.com",
            text_content="hello",
            links=links,
            status_code=404,
        )
        assert snap.links == links
        assert snap.status_code == 404
