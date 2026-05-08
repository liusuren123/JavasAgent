"""ScreenAnalyzer 测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.perception.screen_analyzer import (
    AnalysisResult,
    LocateResult,
    ScreenAnalyzer,
)
from src.utils.config import PerceptionConfig


def _make_config(**overrides) -> PerceptionConfig:
    defaults = {
        "enabled": True,
        "provider": None,
        "describe_max_tokens": 512,
        "locate_max_tokens": 256,
        "analyze_max_tokens": 1024,
        "image_detail": "auto",
    }
    defaults.update(overrides)
    return PerceptionConfig(**defaults)


# 一个最小的 1x1 白色 PNG，用于测试
_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestDescribe:
    """测试 describe() 方法。"""

    @pytest.mark.asyncio
    async def test_describe_returns_text(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = "屏幕上显示了 VS Code 编辑器，正在编辑 Python 文件。"

        analyzer = ScreenAnalyzer(llm, _make_config())
        result = await analyzer.describe(_MINI_PNG)

        assert "VS Code" in result
        llm.chat_with_image.assert_called_once()
        call_kwargs = llm.chat_with_image.call_args.kwargs
        assert "描述" in call_kwargs.get("user_text", "") or call_kwargs.get("system_prompt", "")

    @pytest.mark.asyncio
    async def test_describe_strips_whitespace(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = "  描述内容  \n"

        analyzer = ScreenAnalyzer(llm, _make_config())
        result = await analyzer.describe(_MINI_PNG)
        assert result == "描述内容"

    @pytest.mark.asyncio
    async def test_describe_disabled(self) -> None:
        llm = AsyncMock()
        config = _make_config(enabled=False)
        analyzer = ScreenAnalyzer(llm, config)

        result = await analyzer.describe(_MINI_PNG)
        assert result == ""
        llm.chat_with_image.assert_not_called()

    @pytest.mark.asyncio
    async def test_describe_error_handling(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.side_effect = RuntimeError("API 超时")

        analyzer = ScreenAnalyzer(llm, _make_config())
        result = await analyzer.describe(_MINI_PNG)
        assert "失败" in result


class TestLocate:
    """测试 locate() 方法。"""

    @pytest.mark.asyncio
    async def test_locate_found(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = (
            '{"found": true, "x": 500, "y": 300, "description": "保存按钮"}'
        )

        analyzer = ScreenAnalyzer(llm, _make_config())
        result = await analyzer.locate(_MINI_PNG, "保存按钮")

        assert result.found is True
        assert result.x == 500
        assert result.y == 300
        assert "保存按钮" in result.description

    @pytest.mark.asyncio
    async def test_locate_not_found(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = (
            '{"found": false, "x": null, "y": null, "description": "未找到该元素"}'
        )

        analyzer = ScreenAnalyzer(llm, _make_config())
        result = await analyzer.locate(_MINI_PNG, "不存在的按钮")

        assert result.found is False
        assert result.x is None
        assert result.y is None

    @pytest.mark.asyncio
    async def test_locate_with_extra_text(self) -> None:
        """LLM 可能在 JSON 前后附加额外文本。"""
        llm = AsyncMock()
        llm.chat_with_image.return_value = (
            '根据截图分析，我找到了目标：\n'
            '{"found": true, "x": 100, "y": 200, "description": "关闭按钮"}\n'
            "该按钮位于右上角。"
        )

        analyzer = ScreenAnalyzer(llm, _make_config())
        result = await analyzer.locate(_MINI_PNG, "关闭按钮")

        assert result.found is True
        assert result.x == 100
        assert result.y == 200

    @pytest.mark.asyncio
    async def test_locate_disabled(self) -> None:
        llm = AsyncMock()
        config = _make_config(enabled=False)
        analyzer = ScreenAnalyzer(llm, config)

        result = await analyzer.locate(_MINI_PNG, "按钮")
        assert result.found is False
        assert "禁用" in result.description
        llm.chat_with_image.assert_not_called()

    @pytest.mark.asyncio
    async def test_locate_error_handling(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.side_effect = ConnectionError("网络错误")

        analyzer = ScreenAnalyzer(llm, _make_config())
        result = await analyzer.locate(_MINI_PNG, "按钮")
        assert result.found is False
        assert "失败" in result.description


class TestAnalyze:
    """测试 analyze() 方法。"""

    @pytest.mark.asyncio
    async def test_analyze_returns_result(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = (
            "屏幕上显示了 Chrome 浏览器。\n"
            "当前状态：浏览网页\n"
            "建议：\n"
            "1. 可以向下滚动查看更多内容\n"
            "2. 可以点击链接打开新页面"
        )

        analyzer = ScreenAnalyzer(llm, _make_config())
        result = await analyzer.analyze(_MINI_PNG)

        assert isinstance(result, AnalysisResult)
        assert "Chrome" in result.description
        assert len(result.suggestions) == 2

    @pytest.mark.asyncio
    async def test_analyze_disabled(self) -> None:
        llm = AsyncMock()
        config = _make_config(enabled=False)
        analyzer = ScreenAnalyzer(llm, config)

        result = await analyzer.analyze(_MINI_PNG)
        assert "禁用" in result.description
        llm.chat_with_image.assert_not_called()

    @pytest.mark.asyncio
    async def test_analyze_error_handling(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.side_effect = ValueError("参数错误")

        analyzer = ScreenAnalyzer(llm, _make_config())
        result = await analyzer.analyze(_MINI_PNG)
        assert "失败" in result.description


class TestParseLocateResponse:
    """测试 _parse_locate_response 静态方法。"""

    def test_parse_valid_json(self) -> None:
        raw = '{"found": true, "x": 100, "y": 200, "description": "按钮"}'
        result = ScreenAnalyzer._parse_locate_response(raw)
        assert result.found is True
        assert result.x == 100
        assert result.y == 200

    def test_parse_float_coordinates(self) -> None:
        raw = '{"found": true, "x": 100.5, "y": 200.7, "description": "图标"}'
        result = ScreenAnalyzer._parse_locate_response(raw)
        assert result.found is True
        assert result.x == 100
        assert result.y == 200

    def test_parse_not_found(self) -> None:
        raw = '{"found": false, "x": null, "y": null, "description": "不存在"}'
        result = ScreenAnalyzer._parse_locate_response(raw)
        assert result.found is False
        assert result.x is None

    def test_parse_no_json(self) -> None:
        raw = "这是一个按钮在屏幕右上角。"
        result = ScreenAnalyzer._parse_locate_response(raw)
        assert result.found is False
        assert "无法解析" in result.description

    def test_parse_invalid_json(self) -> None:
        raw = "{invalid json content"
        result = ScreenAnalyzer._parse_locate_response(raw)
        assert result.found is False

    def test_parse_found_but_missing_coords(self) -> None:
        raw = '{"found": true, "description": "找到了但没坐标"}'
        result = ScreenAnalyzer._parse_locate_response(raw)
        assert result.found is False

    def test_parse_json_embedded_in_text(self) -> None:
        raw = "分析结果如下：\n{'found': true, 'x': 42, 'y': 99, 'description': 'test'}\n完毕"
        # 单引号 JSON 是非法的，需要标准双引号
        raw_fixed = '分析结果如下：\n{"found": true, "x": 42, "y": 99, "description": "test"}\n完毕'
        result = ScreenAnalyzer._parse_locate_response(raw_fixed)
        assert result.found is True
        assert result.x == 42


class TestParseAnalyzeResponse:
    """测试 _parse_analyze_response 静态方法。"""

    def test_parse_basic_response(self) -> None:
        raw = "屏幕上显示了文件管理器。"
        result = ScreenAnalyzer._parse_analyze_response(raw)
        assert "文件管理器" in result.description

    def test_parse_with_scene(self) -> None:
        raw = "当前场景：桌面环境\n\n屏幕上显示了各种图标。"
        result = ScreenAnalyzer._parse_analyze_response(raw)
        assert result.scene == "桌面环境"

    def test_parse_with_suggestions(self) -> None:
        raw = (
            "屏幕内容分析：浏览器页面\n"
            "建议：\n"
            "1. 点击搜索栏\n"
            "2. 滚动到页面底部\n"
            "3. 关闭当前标签页"
        )
        result = ScreenAnalyzer._parse_analyze_response(raw)
        assert len(result.suggestions) == 3
        assert "点击搜索栏" in result.suggestions[0]

    @pytest.mark.parametrize(
        "bullet",
        ["- 第一项\n- 第二项", "* 第一项\n* 第二项", "• 第一项\n• 第二项"],
    )
    def test_parse_bullet_suggestions(self, bullet: str) -> None:
        raw = f"建议：\n{bullet}"
        result = ScreenAnalyzer._parse_analyze_response(raw)
        assert len(result.suggestions) == 2

    def test_parse_no_suggestions(self) -> None:
        raw = "只有描述，没有建议。"
        result = ScreenAnalyzer._parse_analyze_response(raw)
        assert result.suggestions == []


class TestConfigPassthrough:
    """测试配置项正确传递到 LLM 调用。"""

    @pytest.mark.asyncio
    async def test_custom_provider(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = "描述"
        config = _make_config(provider="openai")

        analyzer = ScreenAnalyzer(llm, config)
        await analyzer.describe(_MINI_PNG)

        call_kwargs = llm.chat_with_image.call_args.kwargs
        assert call_kwargs.get("provider") == "openai"

    @pytest.mark.asyncio
    async def test_custom_max_tokens(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = "描述"
        config = _make_config(describe_max_tokens=2048)

        analyzer = ScreenAnalyzer(llm, config)
        await analyzer.describe(_MINI_PNG)

        call_kwargs = llm.chat_with_image.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 2048

    @pytest.mark.asyncio
    async def test_custom_detail(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = "描述"
        config = _make_config(image_detail="high")

        analyzer = ScreenAnalyzer(llm, config)
        await analyzer.describe(_MINI_PNG)

        call_kwargs = llm.chat_with_image.call_args.kwargs
        assert call_kwargs.get("detail") == "high"
