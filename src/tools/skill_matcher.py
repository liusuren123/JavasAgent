"""技能匹配引擎。

根据任务描述计算技能相关度分数，返回按分数排序的匹配列表。
"""

from __future__ import annotations

import re

from src.memory.skill_models import SkillDefinition
from src.tools.skill_executor_models import SkillMatch


class SkillMatcher:
    """技能匹配器。

    根据任务描述文本与技能的名称、描述、标签进行多维度匹配，
    计算相关度分数并生成匹配原因说明。

    Usage::

        matcher = SkillMatcher()
        matches = await matcher.match(task_description="截取屏幕", candidates=[skill1, skill2])
        best = matches[0]  # SkillMatch(skill_name=..., relevance_score=..., match_reason=...)
    """

    def match(
        self,
        task_description: str,
        candidates: list[SkillDefinition],
    ) -> list[SkillMatch]:
        """根据任务描述匹配最合适的技能。

        对每个候选技能计算相关度分数，过滤零分项后按分数降序排列。

        Args:
            task_description: 任务描述文本。
            candidates: 候选技能列表。

        Returns:
            按相关度降序排列的匹配列表。
        """
        if not candidates:
            return []

        desc_lower = task_description.lower()
        desc_terms = set(re.findall(r"\w+", desc_lower))

        matches: list[SkillMatch] = []
        for skill in candidates:
            score = self.compute_match_score(skill, desc_lower, desc_terms)
            reason = self.compute_match_reason(skill, desc_lower, desc_terms)

            # 归一化到 0.0-1.0
            normalized = min(1.0, score / 10.0)

            if normalized > 0.0:
                matches.append(
                    SkillMatch(
                        skill_name=skill.name,
                        relevance_score=round(normalized, 4),
                        match_reason=reason,
                    )
                )

        matches.sort(key=lambda m: m.relevance_score, reverse=True)
        return matches

    def compute_match_score(
        self,
        skill: SkillDefinition,
        desc_lower: str,
        desc_terms: set[str],
    ) -> float:
        """计算技能与任务描述的匹配分数。

        匹配维度包括：
        - 精确名称匹配（10 分）
        - 名称包含（6 分）
        - 描述包含（3 分）
        - 标签匹配（5 / 2 分）
        - 词汇级别重叠（1.5 / 0.8 分 per term）

        Args:
            skill: 技能定义。
            desc_lower: 小写的任务描述。
            desc_terms: 任务描述的词汇集合。

        Returns:
            原始匹配分数。
        """
        score = 0.0
        name_lower = skill.name.lower()
        description_lower = skill.description.lower()

        # 精确名称匹配
        if desc_lower == name_lower:
            score += 10.0
        elif desc_lower in name_lower or name_lower in desc_lower:
            score += 6.0

        # 描述匹配
        if desc_lower in description_lower:
            score += 3.0

        # 标签匹配
        for tag in skill.tags:
            tag_lower = tag.lower()
            if desc_lower == tag_lower:
                score += 5.0
            elif desc_lower in tag_lower or tag_lower in desc_lower:
                score += 2.0

        # triggers 匹配（YAML 技能触发关键词）
        for trigger in getattr(skill, "triggers", []):
            trigger_lower = trigger.lower()
            if desc_lower == trigger_lower or trigger_lower in desc_lower:
                score += 7.0  # triggers 权重较高
            elif desc_lower in trigger_lower:
                score += 3.0

        # 词汇级别匹配
        name_terms = set(re.findall(r"\w+", name_lower))
        desc_skill_terms = set(re.findall(r"\w+", description_lower))

        name_overlap = len(desc_terms & name_terms)
        desc_overlap = len(desc_terms & desc_skill_terms)
        score += name_overlap * 1.5 + desc_overlap * 0.8

        return score

    def compute_match_reason(
        self,
        skill: SkillDefinition,
        desc_lower: str,
        desc_terms: set[str],
    ) -> str:
        """生成匹配原因说明。

        Args:
            skill: 技能定义。
            desc_lower: 小写的任务描述。
            desc_terms: 任务描述的词汇集合。

        Returns:
            匹配原因字符串。
        """
        reasons: list[str] = []
        name_lower = skill.name.lower()

        if desc_lower in name_lower or name_lower in desc_lower:
            reasons.append("名称匹配")
        if desc_lower in skill.description.lower():
            reasons.append("描述匹配")

        matched_tags = [
            tag for tag in skill.tags
            if desc_lower in tag.lower() or tag.lower() in desc_lower
        ]
        if matched_tags:
            reasons.append(f"标签匹配: {', '.join(matched_tags[:3])}")

        name_terms = set(re.findall(r"\w+", name_lower))
        overlap = desc_terms & name_terms
        if overlap:
            reasons.append(f"关键词命中: {', '.join(list(overlap)[:5])}")

        return "; ".join(reasons) if reasons else "语义关联"
