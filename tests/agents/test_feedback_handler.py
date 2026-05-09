"""feedback_handler 模块测试。"""

from __future__ import annotations

import pytest

from src.agents.feedback_handler import (
    CANCEL_KEYWORDS,
    CONFIRM_KEYWORDS,
    PendingAction,
    classify_feedback,
)


class TestPendingActionEnum:
    """测试 PendingAction 枚举值。"""

    def test_enum_values(self) -> None:
        assert PendingAction.CONFIRM == "confirm"
        assert PendingAction.CANCEL == "cancel"
        assert PendingAction.REPLAN == "replan"
        assert PendingAction.RETRY == "retry"
        assert PendingAction.NONE == "none"

    def test_enum_is_string(self) -> None:
        """PendingAction 继承 str, Enum，可用于字符串比较。"""
        assert isinstance(PendingAction.CONFIRM, str)
        assert PendingAction.CONFIRM == "confirm"

    def test_enum_members_count(self) -> None:
        assert len(PendingAction) == 5


class TestClassifyFeedbackConfirm:
    """测试确认关键词分类。"""

    @pytest.mark.parametrize("keyword", ["确认", "确定", "是的", "好的", "可以", "执行吧"])
    def test_chinese_confirm_keywords(self, keyword: str) -> None:
        assert classify_feedback(keyword) == PendingAction.CONFIRM

    @pytest.mark.parametrize("keyword", ["yes", "ok", "sure", "go", "do it", "y"])
    def test_english_confirm_keywords(self, keyword: str) -> None:
        assert classify_feedback(keyword) == PendingAction.CONFIRM

    def test_case_insensitive(self) -> None:
        assert classify_feedback("YES") == PendingAction.CONFIRM
        assert classify_feedback("Ok") == PendingAction.CONFIRM
        assert classify_feedback("Y") == PendingAction.CONFIRM

    def test_whitespace_stripped(self) -> None:
        assert classify_feedback("  确认  ") == PendingAction.CONFIRM
        assert classify_feedback(" yes ") == PendingAction.CONFIRM


class TestClassifyFeedbackCancel:
    """测试取消关键词分类。"""

    @pytest.mark.parametrize("keyword", ["取消", "算了", "不要了", "停", "放弃"])
    def test_chinese_cancel_keywords(self, keyword: str) -> None:
        assert classify_feedback(keyword) == PendingAction.CANCEL

    @pytest.mark.parametrize("keyword", ["cancel", "no", "stop", "abort", "n"])
    def test_english_cancel_keywords(self, keyword: str) -> None:
        assert classify_feedback(keyword) == PendingAction.CANCEL

    def test_case_insensitive(self) -> None:
        assert classify_feedback("CANCEL") == PendingAction.CANCEL
        assert classify_feedback("No") == PendingAction.CANCEL


class TestClassifyFeedbackRetry:
    """测试重试关键词分类。"""

    @pytest.mark.parametrize("keyword", ["重试", "retry", "again", "redo"])
    def test_retry_keywords(self, keyword: str) -> None:
        assert classify_feedback(keyword) == PendingAction.RETRY

    def test_case_insensitive(self) -> None:
        assert classify_feedback("RETRY") == PendingAction.RETRY
        assert classify_feedback("Again") == PendingAction.RETRY


class TestClassifyFeedbackReplan:
    """测试重新规划关键词分类。"""

    @pytest.mark.parametrize("keyword", ["重新", "换", "调整", "replan", "change", "adjust"])
    def test_replan_keywords(self, keyword: str) -> None:
        assert classify_feedback(keyword) == PendingAction.REPLAN

    def test_case_insensitive(self) -> None:
        assert classify_feedback("REPLAN") == PendingAction.REPLAN
        assert classify_feedback("Change") == PendingAction.REPLAN


class TestClassifyFeedbackNone:
    """测试不匹配的输入。"""

    def test_normal_text(self) -> None:
        assert classify_feedback("帮我写个函数") == PendingAction.NONE
        assert classify_feedback("今天天气怎么样") == PendingAction.NONE

    def test_empty_string(self) -> None:
        assert classify_feedback("") == PendingAction.NONE

    def test_random_text(self) -> None:
        assert classify_feedback("hello world") == PendingAction.NONE
        assert classify_feedback("12345") == PendingAction.NONE

    def test_partial_match_not_in_set(self) -> None:
        """关键词需要完全匹配（confirm/cancel）或包含（retry/replan），但随机文本不匹配。"""
        assert classify_feedback("确认吗") == PendingAction.NONE  # "确认吗" 不在 frozenset 中
        assert classify_feedback("取消掉") == PendingAction.NONE  # "取消掉" 不在 frozenset 中


class TestClassifyFeedbackCustomKeywords:
    """测试自定义关键词集合。"""

    def test_custom_confirm_keywords(self) -> None:
        custom = frozenset({"oui", "ja", "はい"})
        assert classify_feedback("oui", confirm_keywords=custom) == PendingAction.CONFIRM
        assert classify_feedback("ja", confirm_keywords=custom) == PendingAction.CONFIRM
        # "yes" 不在自定义集合中，不应匹配
        assert classify_feedback("yes", confirm_keywords=custom) == PendingAction.NONE

    def test_custom_cancel_keywords(self) -> None:
        custom = frozenset({"non", "nein", "いいえ"})
        assert classify_feedback("non", cancel_keywords=custom) == PendingAction.CANCEL
        assert classify_feedback("nein", cancel_keywords=custom) == PendingAction.CANCEL
        # "cancel" 不在自定义集合中
        assert classify_feedback("cancel", cancel_keywords=custom) == PendingAction.NONE
