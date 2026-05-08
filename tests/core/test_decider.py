"""决策判断器测试。"""

from __future__ import annotations

import pytest

from src.core.decider import Decider
from src.core.models import DecisionPoint
from src.utils.config import AgentConfig


class TestShouldAskHuman:
    """测试 should_ask_human() 的阈值判断和关键词检测。"""

    def _make_decider(self, threshold: float = 0.6) -> Decider:
        config = AgentConfig(ask_human_threshold=threshold)
        return Decider(config)

    def test_low_confidence_asks_human(self) -> None:
        decider = self._make_decider()
        dp = DecisionPoint(context="普通操作", question="做什么?", confidence=0.3)
        assert decider.should_ask_human(dp) is True

    def test_high_confidence_auto(self) -> None:
        decider = self._make_decider()
        dp = DecisionPoint(context="普通操作", question="做什么?", confidence=0.9)
        assert decider.should_ask_human(dp) is False

    # --- 边界值测试 ---

    def test_confidence_zero_asks(self) -> None:
        decider = self._make_decider()
        dp = DecisionPoint(context="操作", question="?", confidence=0.0)
        assert decider.should_ask_human(dp) is True

    def test_confidence_one_auto(self) -> None:
        decider = self._make_decider()
        dp = DecisionPoint(context="安全操作", question="?", confidence=1.0)
        assert decider.should_ask_human(dp) is False

    def test_exactly_at_threshold_auto(self) -> None:
        """confidence 等于阈值时不触发询问（只有 < 才问）。"""
        decider = self._make_decider(threshold=0.6)
        dp = DecisionPoint(context="安全操作", question="?", confidence=0.6)
        assert decider.should_ask_human(dp) is False

    def test_just_below_threshold_asks(self) -> None:
        decider = self._make_decider(threshold=0.6)
        dp = DecisionPoint(context="安全操作", question="?", confidence=0.59)
        assert decider.should_ask_human(dp) is True

    def test_custom_threshold(self) -> None:
        decider = self._make_decider(threshold=0.9)
        dp = DecisionPoint(context="安全操作", question="?", confidence=0.85)
        assert decider.should_ask_human(dp) is True

    # --- 高风险关键词测试 ---

    @pytest.mark.parametrize("keyword", [
        "删除", "发送", "邮件", "发布", "提交到远程",
        "格式化", "清空", "drop", "delete", "send", "publish",
    ])
    def test_high_risk_keyword_asks(self, keyword: str) -> None:
        decider = self._make_decider()
        dp = DecisionPoint(context=f"正在{keyword}数据", question="确认?", confidence=0.99)
        assert decider.should_ask_human(dp) is True

    def test_high_risk_keyword_case_insensitive(self) -> None:
        """关键词检测应忽略大小写。"""
        decider = self._make_decider()
        dp = DecisionPoint(context="DELETE FROM table", question="?", confidence=1.0)
        assert decider.should_ask_human(dp) is True

    def test_safe_context_auto(self) -> None:
        decider = self._make_decider()
        dp = DecisionPoint(context="读取配置文件", question="继续?", confidence=0.9)
        assert decider.should_ask_human(dp) is False

    def test_empty_context_high_confidence(self) -> None:
        decider = self._make_decider()
        dp = DecisionPoint(context="", question="?", confidence=0.8)
        assert decider.should_ask_human(dp) is False

    def test_empty_context_low_confidence(self) -> None:
        decider = self._make_decider()
        dp = DecisionPoint(context="", question="?", confidence=0.1)
        assert decider.should_ask_human(dp) is True


class TestEvaluate:
    """测试 evaluate() 方法。"""

    def _make_decider(self, threshold: float = 0.6) -> Decider:
        config = AgentConfig(ask_human_threshold=threshold)
        return Decider(config)

    def test_evaluate_auto_decided(self) -> None:
        decider = self._make_decider()
        dp = decider.evaluate("读取文件", "读哪个?", 0.9)
        assert dp.auto_decided is True
        assert isinstance(dp, DecisionPoint)

    def test_evaluate_needs_human(self) -> None:
        decider = self._make_decider()
        dp = decider.evaluate("发布到线上", "确认?", 0.3)
        assert dp.auto_decided is False

    def test_evaluate_with_options(self) -> None:
        decider = self._make_decider()
        dp = decider.evaluate("选择方案", "选哪个?", 0.5, options=["A", "B"])
        assert dp.options == ["A", "B"]
        assert dp.auto_decided is False

    def test_evaluate_default_options_empty(self) -> None:
        decider = self._make_decider()
        dp = decider.evaluate("安全", "?", 0.9)
        assert dp.options == []

    def test_evaluate_preserves_fields(self) -> None:
        decider = self._make_decider()
        dp = decider.evaluate("上下文", "问题?", 0.75, options=["X"])
        assert dp.context == "上下文"
        assert dp.question == "问题?"
        assert dp.confidence == 0.75

    def test_evaluate_zero_confidence(self) -> None:
        decider = self._make_decider()
        dp = decider.evaluate("操作", "?", 0.0)
        assert dp.auto_decided is False

    def test_evaluate_one_confidence_safe(self) -> None:
        decider = self._make_decider()
        dp = decider.evaluate("安全操作", "?", 1.0)
        assert dp.auto_decided is True

    def test_evaluate_one_confidence_dangerous(self) -> None:
        """即使 confidence=1.0，高风险操作仍需人类确认。"""
        decider = self._make_decider()
        dp = decider.evaluate("删除所有数据", "确认?", 1.0)
        assert dp.auto_decided is False
