# -*- coding: utf-8 -*-
"""技能检索与匹配器。

将用户指令文本与技能库中的技能描述进行匹配，支持：
- 关键词重叠匹配（trigger / tag / description / name）
- 语义相似度（基于字符级 Jaccard）
- 返回 Top N + 置信度分数

技能库从 SkillDefinition 列表或 YAML 目录加载。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from src.memory.skill_models import SkillDefinition


# ======================================================================
# 匹配结果
# ======================================================================


@dataclass
class MatchResult:
    """单条匹配结果。

    Attributes:
        skill: 匹配到的技能定义。
        confidence: 置信度分数 [0, 1]。
        matched_keywords: 匹配到的关键词列表。
    """

    skill: SkillDefinition
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)


# ======================================================================
# 文本工具
# ======================================================================


def _tokenize(text: str) -> set[str]:
    """将文本拆分为 token 集合（中文逐字 + 英文按词）。

    Args:
        text: 输入文本。

    Returns:
        token 集合。
    """
    if not text:
        return set()

    tokens: set[str] = set()

    # 英文单词
    en_words = re.findall(r"[a-zA-Z]{2,}", text.lower())
    tokens.update(en_words)

    # 中文 bigram（相邻两字）
    cn_chars = re.findall(r"[\u4e00-\u9fff]", text)
    for i in range(len(cn_chars) - 1):
        tokens.add(cn_chars[i] + cn_chars[i + 1])

    # 中文单字
    tokens.update(cn_chars)

    # 整体小写
    tokens.add(text.lower().strip())

    return tokens


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """计算 Jaccard 相似度。

    Args:
        set_a: 集合 A。
        set_b: 集合 B。

    Returns:
        Jaccard 相似度 [0, 1]。
    """
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


# ======================================================================
# 技能匹配器
# ======================================================================


class SkillMatcher:
    """技能检索匹配器。

    从技能库中检索与用户指令最匹配的技能。

    用法:
        matcher = SkillMatcher(skills=[...])
        results = matcher.match("打开浏览器")
        # results: [MatchResult(...), ...]
    """

    # 各字段权重
    _WEIGHTS: dict[str, float] = {
        "trigger": 0.40,  # 触发词匹配权重最高
        "name": 0.25,     # 名称匹配
        "tag": 0.20,      # 标签匹配
        "description": 0.15,  # 描述匹配
    }

    def __init__(
        self,
        skills: list[SkillDefinition] | None = None,
        yaml_dirs: list[str] | None = None,
    ) -> None:
        """初始化匹配器。

        Args:
            skills: 技能定义列表。
            yaml_dirs: YAML 技能文件目录列表。
        """
        self._skills: list[SkillDefinition] = []
        if skills:
            self._skills.extend(skills)
        if yaml_dirs:
            self._load_from_yaml_dirs(yaml_dirs)

    @property
    def skills(self) -> list[SkillDefinition]:
        """当前加载的技能列表。"""
        return self._skills

    def add_skill(self, skill: SkillDefinition) -> None:
        """添加单个技能。

        Args:
            skill: 技能定义。
        """
        self._skills.append(skill)

    def match(
        self,
        query: str,
        top_k: int = 3,
        min_confidence: float = 0.1,
    ) -> list[MatchResult]:
        """匹配用户指令。

        Args:
            query: 用户指令文本。
            top_k: 返回 Top K 个结果。
            min_confidence: 最低置信度阈值。

        Returns:
            按置信度降序排列的匹配结果列表。
        """
        if not query or not query.strip():
            return []

        if not self._skills:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, SkillDefinition, list[str]]] = []

        for skill in self._skills:
            score, keywords = self._score_skill(query, query_tokens, skill)
            if score >= min_confidence:
                scored.append((score, skill, keywords))

        # 按分数降序
        scored.sort(key=lambda x: x[0], reverse=True)

        # 截取 Top K
        results: list[MatchResult] = []
        for score, skill, keywords in scored[:top_k]:
            results.append(MatchResult(
                skill=skill,
                confidence=round(min(score, 1.0), 4),
                matched_keywords=keywords,
            ))

        return results

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _score_skill(
        self,
        query: str,
        query_tokens: set[str],
        skill: SkillDefinition,
    ) -> tuple[float, list[str]]:
        """计算单个技能的综合匹配分数。

        Args:
            query: 原始查询文本。
            query_tokens: 查询 token 集合。
            skill: 技能定义。

        Returns:
            (分数, 匹配的关键词列表)。
        """
        total_score = 0.0
        all_keywords: list[str] = []

        # 1. 触发词匹配（直接包含）
        trigger_score, trigger_kw = self._match_trigger(query, skill.triggers)
        total_score += trigger_score * self._WEIGHTS["trigger"]
        all_keywords.extend(trigger_kw)

        # 如果触发词精确命中（score=1.0），直接给高分，避免其他字段稀释
        if trigger_score >= 1.0:
            return 1.0, trigger_kw

        # 2. 名称匹配（token Jaccard）
        name_score, name_kw = self._match_field_tokens(query_tokens, skill.name)
        total_score += name_score * self._WEIGHTS["name"]
        all_keywords.extend(name_kw)

        # 3. 标签匹配（直接包含）
        tag_score, tag_kw = self._match_trigger(query, skill.tags)
        total_score += tag_score * self._WEIGHTS["tag"]
        all_keywords.extend(tag_kw)

        # 4. 描述匹配（token Jaccard）
        desc_score, desc_kw = self._match_field_tokens(query_tokens, skill.description)
        total_score += desc_score * self._WEIGHTS["description"]
        all_keywords.extend(desc_kw)

        return total_score, all_keywords

    @staticmethod
    def _match_trigger(query: str, triggers: list[str]) -> tuple[float, list[str]]:
        """触发词精确包含匹配。

        如果查询文本包含某个触发词，给高分。多个命中叠加（上限 1.0）。

        Args:
            query: 查询文本。
            triggers: 触发词列表。

        Returns:
            (分数, 命中的触发词列表)。
        """
        if not triggers:
            return 0.0, []

        hits: list[str] = []
        for trigger in triggers:
            if trigger and trigger in query:
                hits.append(trigger)

        if not hits:
            return 0.0, []

        # 命中率 + 加成：命中越多分数越高，上限 1.0
        ratio = len(hits) / len(triggers)

        # 如果查询完全等于某个触发词，直接满分
        for trigger in triggers:
            if query.strip() == trigger:
                return 1.0, [trigger]

        # 查询包含触发词：基础 0.7 起
        score = min(0.7 + ratio * 0.3, 1.0)
        return score, hits

    @staticmethod
    def _match_field_tokens(
        query_tokens: set[str],
        field_text: str,
    ) -> tuple[float, list[str]]:
        """字段 token 级 Jaccard 匹配。

        Args:
            query_tokens: 查询 token 集合。
            field_text: 字段文本。

        Returns:
            (Jaccard 相似度, 交集 token 列表)。
        """
        if not field_text:
            return 0.0, []

        field_tokens = _tokenize(field_text)
        if not field_tokens:
            return 0.0, []

        intersection = query_tokens & field_tokens
        if not intersection:
            return 0.0, []

        score = _jaccard_similarity(query_tokens, field_tokens)
        return score, list(intersection)

    # ------------------------------------------------------------------
    # YAML 加载
    # ------------------------------------------------------------------

    def _load_from_yaml_dirs(self, dirs: list[str]) -> None:
        """从 YAML 目录批量加载技能。

        Args:
            dirs: 目录路径列表。
        """
        try:
            from src.skills.skill_loader import SkillLoader
        except ImportError:
            logger.warning("SkillLoader 不可用，跳过 YAML 加载")
            return

        loader = SkillLoader(skills_dirs=dirs)
        skills = loader.load_all()
        self._skills.extend(skills)
        logger.debug("从 YAML 加载 {} 个技能", len(skills))
