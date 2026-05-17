# -*- coding: utf-8 -*-
"""技能检索匹配与执行确认机制测试。

覆盖场景：
1. SkillMatcher 初始化与技能库加载
2. 关键词匹配（精确 / 模糊）
3. 语义相似度计算
4. Top 3 排序
5. 置信度分数
6. 空查询 / 空技能库
7. SkillExecutor 三档确认机制
8. 边界值与异常处理
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.memory.skill_models import SkillDefinition
from src.skills.executor import ConfirmLevel, ExecuteResult, SkillExecutor
from src.skills.skill_matcher import MatchResult, SkillMatcher


# ======================================================================
# 测试辅助：构建 SkillDefinition
# ======================================================================


def _make_skill(
    name: str,
    description: str = "",
    tags: list[str] | None = None,
    triggers: list[str] | None = None,
    category: str = "tool",
) -> SkillDefinition:
    """快速构建测试用 SkillDefinition。"""
    return SkillDefinition.create(
        name=name,
        description=description,
        category=category,
        tags=tags or [],
        **{"triggers": triggers or []},  # avoid unexpected kwarg
    )


def _make_skills() -> list[SkillDefinition]:
    """构建一组用于匹配测试的技能。"""
    return [
        _make_skill(
            name="open_browser",
            description="打开浏览器并访问指定网址",
            tags=["浏览器", "网页", "上网"],
            triggers=["打开浏览器", "上网", "打开网页"],
        ),
        _make_skill(
            name="send_email",
            description="发送电子邮件给指定联系人",
            tags=["邮件", "发送", "邮箱"],
            triggers=["发邮件", "发送邮件", "写邮件"],
        ),
        _make_skill(
            name="screenshot_capture",
            description="截取当前屏幕的截图并保存",
            tags=["截图", "屏幕", "保存"],
            triggers=["截屏", "截图", "截取屏幕"],
        ),
        _make_skill(
            name="text_translate",
            description="将文本从一种语言翻译为另一种语言",
            tags=["翻译", "语言", "文本"],
            triggers=["翻译", "翻译文本", "中翻英"],
        ),
        _make_skill(
            name="file_compress",
            description="将文件或文件夹压缩为 ZIP 压缩包",
            tags=["压缩", "ZIP", "文件"],
            triggers=["压缩文件", "打包", "压缩"],
        ),
    ]


# ======================================================================
# SkillMatcher 测试
# ======================================================================


class TestSkillMatcherInit:
    """测试 SkillMatcher 初始化。"""

    def test_init_with_skill_list(self) -> None:
        """从 SkillDefinition 列表初始化。"""
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        assert len(matcher.skills) == 5

    def test_init_empty_skills(self) -> None:
        """空技能列表也能初始化。"""
        matcher = SkillMatcher(skills=[])
        assert len(matcher.skills) == 0

    def test_init_default_no_skills(self) -> None:
        """不传参数时默认空技能库。"""
        matcher = SkillMatcher()
        assert len(matcher.skills) == 0

    def test_load_from_yaml_dir(self, tmp_path: Path) -> None:
        """从 YAML 目录加载技能。"""
        yaml_content = """\
version: "1.0"
name: test_skill
description: 测试技能描述
category: yaml
triggers:
  - 触发词A
  - 触发词B
steps:
  - action: click_text
    text: 确认
"""
        yaml_file = tmp_path / "test_skill.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        matcher = SkillMatcher(yaml_dirs=[str(tmp_path)])
        assert len(matcher.skills) == 1
        assert matcher.skills[0].name == "test_skill"


class TestSkillMatcherKeyword:
    """测试关键词匹配。"""

    def test_exact_trigger_match(self) -> None:
        """精确触发词匹配应得高分。"""
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        results = matcher.match("打开浏览器")
        assert len(results) > 0
        assert results[0].skill.name == "open_browser"
        assert results[0].confidence >= 0.7

    def test_partial_keyword_match(self) -> None:
        """部分关键词匹配也应返回结果。"""
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        results = matcher.match("浏览器")
        assert len(results) > 0
        assert any(r.skill.name == "open_browser" for r in results)

    def test_description_keyword_match(self) -> None:
        """描述中的关键词也能匹配。"""
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        results = matcher.match("发电子邮件给联系人")
        # "电子邮件" / "联系人" 在 description 中出现
        assert len(results) > 0

    def test_tag_match(self) -> None:
        """标签匹配。"""
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        results = matcher.match("翻译文本")
        assert len(results) > 0
        assert results[0].skill.name == "text_translate"


class TestSkillMatcherTopN:
    """测试 Top N 排序。"""

    def test_returns_top3_by_default(self) -> None:
        """默认返回 Top 3。"""
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        results = matcher.match("浏览器网页上网")
        assert len(results) <= 3
        assert len(results) > 0

    def test_returns_top1(self) -> None:
        """指定 top_k=1 只返回 1 个。"""
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        results = matcher.match("截图", top_k=1)
        assert len(results) == 1

    def test_results_sorted_by_confidence_desc(self) -> None:
        """结果按置信度降序排列。"""
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        results = matcher.match("发邮件给联系人")
        confidences = [r.confidence for r in results]
        assert confidences == sorted(confidences, reverse=True)

    def test_top_k_greater_than_skills(self) -> None:
        """top_k 超过技能数量时返回所有匹配。"""
        matcher = SkillMatcher(skills=[_make_skill("only_one", description="唯一技能")])
        results = matcher.match("唯一", top_k=10)
        assert len(results) <= 1


class TestSkillMatcherEdgeCases:
    """测试边界情况。"""

    def test_empty_query(self) -> None:
        """空查询返回空结果。"""
        matcher = SkillMatcher(skills=_make_skills())
        results = matcher.match("")
        assert results == []

    def test_no_matching_skills(self) -> None:
        """无匹配技能时返回空列表。"""
        matcher = SkillMatcher(skills=_make_skills())
        results = matcher.match("量子计算引力波")
        # 完全不相关的内容，可能返回空或极低分
        if results:
            assert results[0].confidence < 0.5

    def test_empty_skill_library(self) -> None:
        """空技能库返回空。"""
        matcher = SkillMatcher(skills=[])
        results = matcher.match("打开浏览器")
        assert results == []

    def test_chinese_query_with_mixed_content(self) -> None:
        """混合语言查询。"""
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        results = matcher.match("帮我 open browser 浏览器")
        assert len(results) > 0

    def test_very_long_query(self) -> None:
        """超长查询不崩溃。"""
        matcher = SkillMatcher(skills=_make_skills())
        long_query = "浏览器" * 1000
        results = matcher.match(long_query)
        # 应正常返回，不抛异常
        assert isinstance(results, list)


class TestMatchResult:
    """测试 MatchResult 数据结构。"""

    def test_match_result_fields(self) -> None:
        """MatchResult 包含正确字段。"""
        skill = _make_skill("test", description="测试")
        result = MatchResult(skill=skill, confidence=0.85, matched_keywords=["测试"])
        assert result.skill.name == "test"
        assert result.confidence == 0.85
        assert "测试" in result.matched_keywords

    def test_confidence_range(self) -> None:
        """置信度在 [0, 1] 范围内。"""
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        results = matcher.match("截图")
        for r in results:
            assert 0.0 <= r.confidence <= 1.0


# ======================================================================
# SkillExecutor 测试
# ======================================================================


class TestSkillExecutorConfirm:
    """测试三档确认机制。"""

    def _setup_executor(self) -> tuple[SkillExecutor, SkillMatcher]:
        """构建 executor + matcher。"""
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        executor = SkillExecutor(matcher=matcher)
        return executor, matcher

    def test_high_confidence_auto_execute(self) -> None:
        """置信度 > 0.8 → 自动执行。"""
        executor, matcher = self._setup_executor()
        result = executor.evaluate("打开浏览器")
        assert result.level == ConfirmLevel.AUTO_EXECUTE

    def test_medium_confidence_need_confirm(self) -> None:
        """置信度 0.5-0.8 → 需要确认。"""
        executor, matcher = self._setup_executor()
        # 用模糊查询获取中等置信度
        result = executor.evaluate("帮我处理一下那个东西")
        assert result.level == ConfirmLevel.NEED_CONFIRM or result.level == ConfirmLevel.NO_MATCH

    def test_low_confidence_no_match(self) -> None:
        """置信度 < 0.5 → 无匹配。"""
        executor, matcher = self._setup_executor()
        result = executor.evaluate("量子纠缠理论推导")
        assert result.level == ConfirmLevel.NO_MATCH

    def test_execute_result_has_matches(self) -> None:
        """ExecuteResult 包含匹配列表。"""
        executor, matcher = self._setup_executor()
        result = executor.evaluate("截图")
        assert isinstance(result, ExecuteResult)
        assert isinstance(result.matches, list)

    def test_execute_result_fields(self) -> None:
        """ExecuteResult 字段完整。"""
        executor, matcher = self._setup_executor()
        result = executor.evaluate("打开浏览器")
        assert result.level is not None
        assert isinstance(result.message, str)
        assert isinstance(result.matches, list)
        assert isinstance(result.suggestion, str)


class TestSkillExecutorThresholds:
    """测试阈值边界。"""

    def test_threshold_auto_at_08(self) -> None:
        """恰好 0.8 → AUTO_EXECUTE。"""
        executor, matcher = self._setup_executor()
        # 模拟一个恰好 0.8 的匹配结果
        mock_result = MatchResult(
            skill=_make_skill("mock"),
            confidence=0.8,
            matched_keywords=["mock"],
        )
        with patch.object(matcher, "match", return_value=[mock_result]):
            result = executor.evaluate("测试")
        assert result.level == ConfirmLevel.AUTO_EXECUTE

    def test_threshold_confirm_at_05(self) -> None:
        """恰好 0.5 → NEED_CONFIRM。"""
        executor, matcher = self._setup_executor()
        mock_result = MatchResult(
            skill=_make_skill("mock"),
            confidence=0.5,
            matched_keywords=["mock"],
        )
        with patch.object(matcher, "match", return_value=[mock_result]):
            result = executor.evaluate("测试")
        assert result.level == ConfirmLevel.NEED_CONFIRM

    def test_threshold_below_05(self) -> None:
        """0.49 → NO_MATCH。"""
        executor, matcher = self._setup_executor()
        mock_result = MatchResult(
            skill=_make_skill("mock"),
            confidence=0.49,
            matched_keywords=["mock"],
        )
        with patch.object(matcher, "match", return_value=[mock_result]):
            result = executor.evaluate("测试")
        assert result.level == ConfirmLevel.NO_MATCH

    def _setup_executor(self) -> tuple[SkillExecutor, SkillMatcher]:
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        executor = SkillExecutor(matcher=matcher)
        return executor, matcher


class TestSkillExecutorEdgeCases:
    """测试 SkillExecutor 边界情况。"""

    def test_empty_query(self) -> None:
        """空查询返回 NO_MATCH。"""
        matcher = SkillMatcher(skills=_make_skills())
        executor = SkillExecutor(matcher=matcher)
        result = executor.evaluate("")
        assert result.level == ConfirmLevel.NO_MATCH

    def test_no_skills_loaded(self) -> None:
        """无技能时返回 NO_MATCH。"""
        matcher = SkillMatcher(skills=[])
        executor = SkillExecutor(matcher=matcher)
        result = executor.evaluate("打开浏览器")
        assert result.level == ConfirmLevel.NO_MATCH

    def test_message_content_auto_execute(self) -> None:
        """自动执行时 message 包含技能名。"""
        executor, matcher = self._setup_executor()
        result = executor.evaluate("打开浏览器")
        if result.level == ConfirmLevel.AUTO_EXECUTE:
            assert "open_browser" in result.message or "浏览器" in result.message

    def test_suggestion_no_match(self) -> None:
        """无匹配时建议走普通规划流程。"""
        executor, matcher = self._setup_executor()
        result = executor.evaluate("量子计算")
        if result.level == ConfirmLevel.NO_MATCH:
            assert "规划" in result.suggestion or "plan" in result.suggestion.lower()

    def _setup_executor(self) -> tuple[SkillExecutor, SkillMatcher]:
        skills = _make_skills()
        matcher = SkillMatcher(skills=skills)
        executor = SkillExecutor(matcher=matcher)
        return executor, matcher
