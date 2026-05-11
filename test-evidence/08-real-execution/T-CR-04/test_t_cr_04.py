"""T-CR-04: Decider 决策 — 实操测试。

验证 Decider.evaluate() 返回正确的 auto_decided 决策。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.core.decider import Decider
from src.core.models import DecisionPoint
from src.utils.config import AgentConfig


@pytest.fixture
def decider():
    config = AgentConfig(ask_human_threshold=0.6)
    return Decider(config=config)


def test_high_confidence_safe_action(decider):
    """高置信度 + 安全操作 → 自主决策。"""
    dp = decider.evaluate(
        context="打开文件读取内容",
        question="是否继续读取?",
        confidence=0.9,
    )
    assert dp.auto_decided is True
    print(f"[OK] 高置信+安全: auto_decided=True")


def test_low_confidence(decider):
    """低置信度 → 需要询问人类。"""
    dp = decider.evaluate(
        context="不确定用户意图",
        question="你想做什么?",
        confidence=0.3,
    )
    assert dp.auto_decided is False
    print(f"[OK] 低置信度: auto_decided=False")


def test_high_confidence_delete_keyword(decider):
    """高置信度 + 删除关键词 → 需要询问人类。"""
    dp = decider.evaluate(
        context="删除临时文件",
        question="是否删除?",
        confidence=0.95,
    )
    assert dp.auto_decided is False
    print(f"[OK] 高置信+删除: auto_decided=False")


def test_high_confidence_send_email(decider):
    """高置信度 + 发送邮件关键词 → 需要询问人类。"""
    dp = decider.evaluate(
        context="发送邮件给团队",
        question="确认发送?",
        confidence=0.85,
    )
    assert dp.auto_decided is False
    print(f"[OK] 高置信+邮件: auto_decided=False")


def test_high_confidence_publish(decider):
    """高置信度 + 发布关键词 → 需要询问人类。"""
    dp = decider.evaluate(
        context="publish the article",
        question="确认发布?",
        confidence=0.8,
    )
    assert dp.auto_decided is False
    print(f"[OK] 高置信+publish: auto_decided=False")


def test_evaluate_returns_decision_point(decider):
    """evaluate() 应返回 DecisionPoint 实例。"""
    dp = decider.evaluate(
        context="普通操作",
        question="继续?",
        confidence=0.8,
        options=["yes", "no"],
    )
    assert isinstance(dp, DecisionPoint)
    assert dp.context == "普通操作"
    assert dp.question == "继续?"
    assert dp.confidence == 0.8
    assert dp.options == ["yes", "no"]
    print(f"[OK] DecisionPoint 字段完整")


def test_exact_threshold_boundary(decider):
    """confidence 刚好等于阈值 → 不需要询问（阈值判断用 <）。"""
    dp = decider.evaluate(
        context="普通操作",
        question="继续?",
        confidence=0.6,  # 等于阈值
    )
    # confidence < threshold 才询问，等于不询问
    assert dp.auto_decided is True
    print(f"[OK] 阈值边界(0.6==0.6): auto_decided=True")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
