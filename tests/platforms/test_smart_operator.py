"""SmartOperator 测试 — 基于 UI 检测的拟人化操作。

测试策略：
- 所有 HybridDetector / HumanHand 交互全部 mock
- 验证 SmartOperator 正确地"组合"了检测 + 操作
- 验证各 API 的入参、返回值、边界情况
- 验证不暴露原始坐标给调用者
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.perception.ui_detector import UIElement
from src.platforms.smart_operator import SmartOperator, SmartOperatorConfig


# ---------------------------------------------------------------------------
# 测试 fixtures
# ---------------------------------------------------------------------------


def _make_element(
    text: str = "",
    etype: str = "ButtonControl",
    bbox: tuple[int, int, int, int] = (100, 100, 200, 150),
    confidence: float = 1.0,
    source: str = "uia",
    clickable: bool = True,
    actionable: bool = False,
    element_id: str = "",
) -> UIElement:
    """快速构造 UIElement 用于测试。"""
    return UIElement(
        bbox=bbox,
        type=etype,
        text=text,
        confidence=confidence,
        source=source,
        clickable=clickable,
        actionable=actionable,
        element_id=element_id,
    )


@pytest.fixture
def mock_detector():
    """创建 mock HybridDetector。"""
    detector = MagicMock()
    detector.find = MagicMock(return_value=[])
    detector.detect = MagicMock(return_value=[])
    return detector


@pytest.fixture
def mock_hand():
    """创建 mock HumanHand。

    所有的 async 方法使用 AsyncMock。
    """
    hand = MagicMock()
    hand.human_click = AsyncMock()
    hand.human_move_to = AsyncMock()
    hand.human_type = AsyncMock()
    hand.human_paste = AsyncMock()
    hand.human_press_key = AsyncMock()
    hand.human_hotkey = AsyncMock()
    hand.human_double_click = AsyncMock()
    hand.human_right_click = AsyncMock()
    hand.human_drag = AsyncMock()
    hand.human_scroll = AsyncMock()
    return hand


@pytest.fixture
def operator(mock_detector, mock_hand):
    """创建使用 mock 依赖的 SmartOperator。"""
    return SmartOperator(
        detector=mock_detector,
        hand=mock_hand,
    )


def run(coro):
    """在同步测试中运行协程。"""
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# click_element 测试
# ===========================================================================


class TestClickElement:
    """click_element(name_or_text) 测试。"""

    def test_click_by_text(self, operator, mock_detector, mock_hand):
        """通过文本定位并点击元素。"""
        elem = _make_element(text="保存", etype="ButtonControl")
        mock_detector.find.return_value = [elem]

        result = run(operator.click_element("保存"))

        mock_detector.find.assert_called_once_with("保存", window_title=None)
        mock_hand.human_click.assert_called_once()
        # 验证点击了元素中心
        click_args = mock_hand.human_click.call_args
        assert click_args[0][0] == 150  # center x
        assert click_args[0][1] == 125  # center y
        assert result is True

    def test_click_by_type_keyword(self, operator, mock_detector, mock_hand):
        """通过类型关键词定位元素。"""
        elem = _make_element(text="提交", etype="ButtonControl")
        mock_detector.find.return_value = [elem]

        result = run(operator.click_element("按钮"))
        # HybridDetector.find 被调用，参数为"按钮"
        mock_detector.find.assert_called_once_with("按钮", window_title=None)
        assert result is True

    def test_click_no_match(self, operator, mock_detector, mock_hand):
        """找不到匹配元素时返回 False，不执行点击。"""
        mock_detector.find.return_value = []

        result = run(operator.click_element("不存在的按钮"))

        mock_hand.human_click.assert_not_called()
        assert result is False

    def test_click_multiple_matches_picks_best(self, operator, mock_detector, mock_hand):
        """多个匹配时选择置信度最高的。"""
        elem_low = _make_element(
            text="确定", confidence=0.5,
            bbox=(100, 100, 200, 150),
        )
        elem_high = _make_element(
            text="确定", confidence=0.95,
            bbox=(300, 300, 400, 350),
        )
        # find 返回时已按置信度排序
        mock_detector.find.return_value = [elem_high, elem_low]

        result = run(operator.click_element("确定"))

        # 应点击高置信度元素
        click_args = mock_hand.human_click.call_args[0]
        assert click_args[0] == 350  # high confidence center x
        assert click_args[1] == 325  # high confidence center y
        assert result is True

    def test_click_returns_bool_not_coords(self, operator, mock_detector, mock_hand):
        """返回值是 bool，不暴露坐标。"""
        elem = _make_element(text="搜索", bbox=(10, 20, 110, 60))
        mock_detector.find.return_value = [elem]

        result = run(operator.click_element("搜索"))
        assert isinstance(result, bool)
        assert result is True

    def test_click_with_window_title(self, operator, mock_detector, mock_hand):
        """传入 window_title 时传递给 detector。"""
        elem = _make_element(text="打开")
        mock_detector.find.return_value = [elem]

        result = run(operator.click_element("打开", window_title="记事本"))

        mock_detector.find.assert_called_once_with("打开", window_title="记事本")


# ===========================================================================
# type_in_field 测试
# ===========================================================================


class TestTypeInField:
    """type_in_field(label, text) 测试。"""

    def test_type_into_edit_field(self, operator, mock_detector, mock_hand):
        """找到输入框并输入文字。"""
        elem = _make_element(
            text="搜索", etype="EditControl",
            bbox=(50, 50, 300, 80),
            actionable=True,
        )
        mock_detector.find.return_value = [elem]

        result = run(operator.type_in_field("搜索", "hello world"))

        # 应该点击输入框（聚焦）
        mock_hand.human_click.assert_called_once()
        # 应该输入文字
        mock_hand.human_type.assert_called_once_with("hello world")
        assert result is True

    def test_type_into_document_field(self, operator, mock_detector, mock_hand):
        """Document 控件也可输入。"""
        elem = _make_element(
            text="内容", etype="DocumentControl",
            bbox=(50, 50, 500, 400),
            actionable=True,
        )
        mock_detector.find.return_value = [elem]

        result = run(operator.type_in_field("内容", "测试文本"))

        mock_hand.human_click.assert_called_once()
        mock_hand.human_type.assert_called_once_with("测试文本")
        assert result is True

    def test_type_no_field_found(self, operator, mock_detector, mock_hand):
        """找不到输入框时返回 False。"""
        mock_detector.find.return_value = []

        result = run(operator.type_in_field("不存在的框", "文本"))

        mock_hand.human_click.assert_not_called()
        mock_hand.human_type.assert_not_called()
        assert result is False

    def test_type_with_paste_mode(self, operator, mock_detector, mock_hand):
        """use_paste=True 时使用剪贴板粘贴而非逐字输入。"""
        elem = _make_element(
            text="地址栏", etype="EditControl",
            bbox=(10, 10, 400, 40),
            actionable=True,
        )
        mock_detector.find.return_value = [elem]

        result = run(operator.type_in_field("地址栏", "https://example.com", use_paste=True))

        mock_hand.human_click.assert_called_once()
        mock_hand.human_paste.assert_called_once_with("https://example.com")
        mock_hand.human_type.assert_not_called()
        assert result is True

    def test_type_clears_field_first(self, operator, mock_detector, mock_hand):
        """输入前先清空已有内容（Ctrl+A → Delete）。"""
        elem = _make_element(
            text="用户名", etype="EditControl",
            bbox=(10, 10, 200, 40),
            actionable=True,
        )
        mock_detector.find.return_value = [elem]

        result = run(operator.type_in_field("用户名", "alice", clear_first=True))

        # 应调用 hotkey("ctrl", "a") 和 press_key("delete")
        hotkey_calls = mock_hand.human_hotkey.call_args_list
        press_calls = mock_hand.human_press_key.call_args_list

        assert any(
            c[0] == ("ctrl", "a") for c in hotkey_calls
        ), "应调用 Ctrl+A 全选"
        assert any(
            c[0][0] == "delete" for c in press_calls
        ), "应调用 Delete 清空"

        mock_hand.human_type.assert_called_once_with("alice")
        assert result is True

    def test_type_returns_bool_not_coords(self, operator, mock_detector, mock_hand):
        """返回值是 bool，不暴露坐标。"""
        elem = _make_element(text="搜索", etype="EditControl", actionable=True)
        mock_detector.find.return_value = [elem]

        result = run(operator.type_in_field("搜索", "test"))
        assert isinstance(result, bool)


# ===========================================================================
# press_button 测试
# ===========================================================================


class TestPressButton:
    """press_button(label) 测试。"""

    def test_press_by_label(self, operator, mock_detector, mock_hand):
        """通过按钮文本找到并点击。"""
        elem = _make_element(text="确定", etype="ButtonControl", clickable=True)
        mock_detector.find.return_value = [elem]

        result = run(operator.press_button("确定"))

        mock_hand.human_click.assert_called_once()
        assert result is True

    def test_press_no_match(self, operator, mock_detector, mock_hand):
        """找不到按钮时返回 False。"""
        mock_detector.find.return_value = []

        result = run(operator.press_button("不存在的按钮"))

        mock_hand.human_click.assert_not_called()
        assert result is False

    def test_press_returns_bool(self, operator, mock_detector, mock_hand):
        """返回值是 bool。"""
        elem = _make_element(text="取消", etype="ButtonControl", clickable=True)
        mock_detector.find.return_value = [elem]

        result = run(operator.press_button("取消"))
        assert isinstance(result, bool)

    def test_press_prefers_clickable(self, operator, mock_detector, mock_hand):
        """优先选择 clickable=True 的元素。"""
        elem_text = _make_element(
            text="保存", etype="TextControl",
            confidence=0.9, clickable=False,
            bbox=(100, 100, 200, 130),
        )
        elem_btn = _make_element(
            text="保存", etype="ButtonControl",
            confidence=0.8, clickable=True,
            bbox=(100, 200, 200, 230),
        )
        # find 返回时文本在前（置信度更高）
        mock_detector.find.return_value = [elem_text, elem_btn]

        result = run(operator.press_button("保存"))

        # 应点击按钮元素（第二个）
        click_args = mock_hand.human_click.call_args[0]
        assert click_args[1] == 215  # button center y
        assert result is True


# ===========================================================================
# 通用行为测试
# ===========================================================================


class TestSmartOperatorGeneral:
    """SmartOperator 通用行为测试。"""

    def test_config_defaults(self):
        """默认配置合理。"""
        config = SmartOperatorConfig()
        assert config.click_timeout > 0
        assert config.type_delay > 0

    def test_custom_config(self, mock_detector, mock_hand):
        """自定义配置生效。"""
        config = SmartOperatorConfig(click_timeout=10.0, type_delay=0.5)
        op = SmartOperator(detector=mock_detector, hand=mock_hand, config=config)
        assert op._config.click_timeout == 10.0
        assert op._config.type_delay == 0.5

    def test_api_signature_no_coords(self, operator, mock_detector, mock_hand):
        """所有公开 API 的入参不包含坐标参数。"""
        import inspect

        public_methods = [
            "click_element",
            "type_in_field",
            "press_button",
        ]
        for method_name in public_methods:
            method = getattr(operator, method_name)
            sig = inspect.signature(method)
            # 参数名不应包含 x, y, coord, position 等坐标相关词
            for param_name in sig.parameters:
                assert param_name.lower() not in ("x", "y", "coord", "position"), \
                    f"{method_name} 不应暴露坐标参数 '{param_name}'"

    def test_click_element_double_click(self, operator, mock_detector, mock_hand):
        """click_element 支持 double_click 选项。"""
        elem = _make_element(text="文件夹", etype="ListItemControl")
        mock_detector.find.return_value = [elem]

        result = run(operator.click_element("文件夹", double_click=True))

        mock_hand.human_double_click.assert_called_once()
        assert result is True

    def test_click_element_right_click(self, operator, mock_detector, mock_hand):
        """click_element 支持 right_click 选项。"""
        elem = _make_element(text="文件", etype="ListItemControl")
        mock_detector.find.return_value = [elem]

        result = run(operator.click_element("文件", right_click=True))

        mock_hand.human_right_click.assert_called_once()
        assert result is True

    def test_detector_exception_handled(self, operator, mock_detector, mock_hand):
        """HybridDetector 抛异常时安全返回 False。"""
        mock_detector.find.side_effect = RuntimeError("UIA 服务不可用")

        result = run(operator.click_element("测试"))

        assert result is False
        mock_hand.human_click.assert_not_called()

    def test_hand_exception_handled(self, operator, mock_detector, mock_hand):
        """HumanHand 抛异常时安全返回 False。"""
        elem = _make_element(text="按钮")
        mock_detector.find.return_value = [elem]
        mock_hand.human_click.side_effect = RuntimeError("操作失败")

        result = run(operator.click_element("按钮"))

        assert result is False
