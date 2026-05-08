"""决策判断器测试。"""

from src.core.decider import Decider
from src.core.models import DecisionPoint
from src.utils.config import AgentConfig


class TestDecider:
    """Decider 测试。"""

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

    def test_high_risk_always_asks(self) -> None:
        decider = self._make_decider()
        dp = DecisionPoint(context="删除文件", question="确认删除?", confidence=0.99)
        assert decider.should_ask_human(dp) is True

    def test_send_email_asks(self) -> None:
        decider = self._make_decider()
        dp = DecisionPoint(context="发送邮件给客户", question="发送?", confidence=0.95)
        assert decider.should_ask_human(dp) is True

    def test_evaluate_auto_decided(self) -> None:
        decider = self._make_decider()
        dp = decider.evaluate("读取文件", "读哪个?", 0.9)
        assert dp.auto_decided is True

    def test_evaluate_needs_human(self) -> None:
        decider = self._make_decider()
        dp = decider.evaluate("发布到线上", "确认?", 0.3)
        assert dp.auto_decided is False
