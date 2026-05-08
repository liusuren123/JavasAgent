"""决策判断器。

判断当前决策点是需要询问人类还是自主决定。
"""

from __future__ import annotations

from loguru import logger

from src.core.models import DecisionPoint
from src.utils.config import AgentConfig


class Decider:
    """决策判断器。

    根据 confidence 阈值决定是自主执行还是询问人类。
    """

    def __init__(self, config: AgentConfig) -> None:
        self._threshold = config.ask_human_threshold

    def should_ask_human(self, decision: DecisionPoint) -> bool:
        """判断是否需要询问人类。

        规则：
        - confidence 低于阈值 → 问人
        - 涉及破坏性操作 → 问人
        - 涉及外部发送（邮件、消息）→ 问人
        """
        if decision.confidence < self._threshold:
            logger.info(
                f"决策置信度 {decision.confidence:.2f} < 阈值 {self._threshold}，需要询问人类"
            )
            return True

        # 检查是否涉及高风险关键词
        high_risk_keywords = [
            "删除", "发送", "邮件", "发布", "提交到远程",
            "格式化", "清空", "drop", "delete", "send", "publish",
        ]
        context_lower = decision.context.lower()
        if any(kw in context_lower for kw in high_risk_keywords):
            logger.info(f"检测到高风险操作，需要询问人类: {decision.context[:50]}")
            return True

        return False

    def evaluate(
        self,
        context: str,
        question: str,
        confidence: float,
        options: list[str] | None = None,
    ) -> DecisionPoint:
        """创建并评估一个决策点。

        Returns:
            评估后的决策点，auto_decided 字段指示是否已自动决策
        """
        decision = DecisionPoint(
            context=context,
            question=question,
            confidence=confidence,
            options=options or [],
        )

        if not self.should_ask_human(decision):
            decision.auto_decided = True
            logger.debug(f"自主决策: {question[:50]}")
        else:
            logger.info(f"需要人类决策: {question}")

        return decision
