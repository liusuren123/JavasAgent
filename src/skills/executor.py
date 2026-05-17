# -*- coding: utf-8 -*-
"""技能执行确认机制。

根据匹配置信度决定执行策略：
- 置信度 > 0.8 → 自动执行（AUTO_EXECUTE）
- 置信度 0.5 ~ 0.8 → 返回匹配结果，等待用户确认（NEED_CONFIRM）
- 置信度 < 0.5 → 无匹配，建议走普通规划流程（NO_MATCH）
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from src.skills.skill_matcher import MatchResult, SkillMatcher


# ======================================================================
# 确认等级
# ======================================================================


class ConfirmLevel(str, Enum):
    """技能执行确认等级。"""

    AUTO_EXECUTE = "auto_execute"    # 自动执行
    NEED_CONFIRM = "need_confirm"    # 需要用户确认
    NO_MATCH = "no_match"            # 无匹配


# ======================================================================
# 执行结果
# ======================================================================


@dataclass
class ExecuteResult:
    """技能执行评估结果。

    Attributes:
        level: 确认等级。
        matches: 匹配结果列表。
        message: 给用户的消息。
        suggestion: 建议操作。
    """

    level: ConfirmLevel
    matches: list[MatchResult] = field(default_factory=list)
    message: str = ""
    suggestion: str = ""

    @property
    def best_match(self) -> MatchResult | None:
        """最佳匹配（置信度最高的那个）。"""
        if self.matches:
            return self.matches[0]
        return None

    @property
    def best_confidence(self) -> float:
        """最高置信度。"""
        if self.matches:
            return self.matches[0].confidence
        return 0.0


# ======================================================================
# 技能执行器
# ======================================================================


class SkillExecutor:
    """技能执行确认器。

    根据匹配结果和置信度，决定下一步执行策略。

    用法:
        executor = SkillExecutor(matcher=matcher)
        result = executor.evaluate("打开浏览器")
        if result.level == ConfirmLevel.AUTO_EXECUTE:
            # 直接执行
            ...
        elif result.level == ConfirmLevel.NEED_CONFIRM:
            # 等待用户确认
            ...
    """

    # 阈值常量
    THRESHOLD_AUTO: float = 0.8     # > 此值自动执行
    THRESHOLD_CONFIRM: float = 0.5  # >= 此值需确认

    def __init__(
        self,
        matcher: SkillMatcher | None = None,
        threshold_auto: float = 0.8,
        threshold_confirm: float = 0.5,
    ) -> None:
        """初始化执行器。

        Args:
            matcher: 技能匹配器实例。
            threshold_auto: 自动执行阈值（默认 0.8）。
            threshold_confirm: 需确认阈值（默认 0.5）。
        """
        self._matcher = matcher or SkillMatcher()
        self._threshold_auto = threshold_auto
        self._threshold_confirm = threshold_confirm

    @property
    def matcher(self) -> SkillMatcher:
        """底层匹配器。"""
        return self._matcher

    def evaluate(
        self,
        query: str,
        top_k: int = 3,
    ) -> ExecuteResult:
        """评估用户指令并返回执行策略。

        Args:
            query: 用户指令文本。
            top_k: 匹配 Top K。

        Returns:
            ExecuteResult 包含确认等级、匹配结果和建议。
        """
        # 空查询
        if not query or not query.strip():
            return ExecuteResult(
                level=ConfirmLevel.NO_MATCH,
                message="查询为空",
                suggestion="请提供具体的操作指令",
            )

        # 执行匹配
        matches = self._matcher.match(query, top_k=top_k)

        if not matches:
            return ExecuteResult(
                level=ConfirmLevel.NO_MATCH,
                message=f"未找到与「{query}」匹配的技能",
                suggestion="建议走普通规划流程完成任务",
            )

        best = matches[0]
        confidence = best.confidence

        # 判断确认等级
        if confidence >= self._threshold_auto:
            return self._build_auto_execute(matches, query)
        elif confidence >= self._threshold_confirm:
            return self._build_need_confirm(matches, query)
        else:
            return self._build_no_match(matches, query)

    # ------------------------------------------------------------------
    # 构建各等级结果
    # ------------------------------------------------------------------

    @staticmethod
    def _build_auto_execute(matches: list[MatchResult], query: str) -> ExecuteResult:
        """构建自动执行结果。"""
        best = matches[0]
        skill = best.skill
        msg = f"已匹配技能「{skill.name}」（置信度 {best.confidence:.1%}），准备自动执行"
        logger.info("自动执行: skill={} confidence={:.4f}", skill.name, best.confidence)
        return ExecuteResult(
            level=ConfirmLevel.AUTO_EXECUTE,
            matches=matches,
            message=msg,
            suggestion=f"直接执行技能 {skill.name}",
        )

    @staticmethod
    def _build_need_confirm(matches: list[MatchResult], query: str) -> ExecuteResult:
        """构建需要确认结果。"""
        best = matches[0]
        skill = best.skill
        candidates = "、".join(f"「{m.skill.name}」({m.confidence:.1%})" for m in matches[:3])
        msg = f"找到可能的匹配：{candidates}，请确认是否执行"
        logger.info("需确认: skill={} confidence={:.4f}", skill.name, best.confidence)
        return ExecuteResult(
            level=ConfirmLevel.NEED_CONFIRM,
            matches=matches,
            message=msg,
            suggestion="请确认后执行",
        )

    @staticmethod
    def _build_no_match(matches: list[MatchResult], query: str) -> ExecuteResult:
        """构建无匹配结果。"""
        best = matches[0] if matches else None
        if best:
            msg = f"匹配度较低（最高 {best.confidence:.1%}），无法确定对应技能"
        else:
            msg = f"未找到与「{query}」匹配的技能"
        logger.info("无匹配: query={}", query[:50])
        return ExecuteResult(
            level=ConfirmLevel.NO_MATCH,
            matches=matches,
            message=msg,
            suggestion="建议走普通规划流程完成任务",
        )
