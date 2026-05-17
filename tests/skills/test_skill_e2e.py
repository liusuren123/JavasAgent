# -*- coding: utf-8 -*-
"""技能端到端验证测试。

覆盖完整链路：加载技能 → 匹配指令 → 确认执行 → 结果评分。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.skills.skill_loader import SkillLoader
from src.skills.skill_matcher import SkillMatcher, MatchResult
from src.skills.executor import SkillExecutor, ConfirmLevel
from src.skills.result_tracker import (
    ResultTracker,
    ResultRating,
    SkillResult,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def skills_dir() -> Path:
    """项目 skills 目录。"""
    return Path(__file__).resolve().parent.parent.parent / "skills"


@pytest.fixture
def loaded_skills(skills_dir: Path) -> list:
    """从 skills/ 加载全部技能。"""
    loader = SkillLoader(skills_dirs=[str(skills_dir)])
    return loader.load_all()


@pytest.fixture
def matcher(loaded_skills: list) -> SkillMatcher:
    """已加载技能的匹配器。"""
    return SkillMatcher(skills=loaded_skills)


@pytest.fixture
def executor(matcher: SkillMatcher) -> SkillExecutor:
    """技能执行器。"""
    return SkillExecutor(matcher=matcher)


@pytest.fixture
def tmp_tracker(tmp_path: Path) -> ResultTracker:
    """使用临时文件的追踪器。"""
    return ResultTracker(storage_path=tmp_path / "test_results.jsonl")


# ======================================================================
# 1. 加载技能测试
# ======================================================================


class TestSkillLoading:
    """验证 YAML 技能文件能正确加载。"""

    def test_load_all_skills(self, loaded_skills: list) -> None:
        """至少能加载 10 个技能。"""
        assert len(loaded_skills) >= 10, f"期望 >= 10 个技能，实际 {len(loaded_skills)}"

    def test_new_skills_exist(self, loaded_skills: list) -> None:
        """新增的 5 个技能全部加载成功。"""
        names = {s.name for s in loaded_skills}
        expected = {
            "复制文件",
            "关闭当前窗口",
            "浏览器搜索信息",
            "记事本编辑文本",
            "文件管理器操作",
        }
        for name in expected:
            assert name in names, f"技能「{name}」未加载"

    def test_skills_have_steps(self, loaded_skills: list) -> None:
        """所有技能都有非空步骤。"""
        for skill in loaded_skills:
            assert len(skill.steps) > 0, f"技能「{skill.name}」没有步骤"

    def test_skills_have_triggers(self, loaded_skills: list) -> None:
        """所有技能都有触发词。"""
        for skill in loaded_skills:
            assert len(skill.triggers) > 0, f"技能「{skill.name}」没有触发词"


# ======================================================================
# 2. 指令匹配测试
# ======================================================================


class TestSkillMatching:
    """验证用户指令能正确匹配到技能。"""

    @pytest.mark.parametrize(
        "query,expected_skill",
        [
            ("帮我搜一下天气", "浏览器搜索信息"),
            ("搜索 Python 教程", "浏览器搜索信息"),
            ("打开记事本写个备忘", "记事本编辑文本"),
            ("关闭这个窗口", "关闭当前窗口"),
            ("复制文件到桌面", "复制文件"),
            ("打开文件夹 D:\\Projects", "文件管理器操作"),
            ("打开应用微信", "打开应用程序"),
            ("截屏保存", "全屏截图"),
        ],
    )
    def test_match_real_commands(
        self, matcher: SkillMatcher, query: str, expected_skill: str
    ) -> None:
        """真实指令能匹配到预期技能。"""
        results = matcher.match(query, top_k=3, min_confidence=0.1)
        assert len(results) > 0, f"指令「{query}」无匹配结果"

        names = [r.skill.name for r in results]
        assert expected_skill in names, (
            f"指令「{query}」未匹配到「{expected_skill}」，实际匹配: {names}"
        )

    def test_match_returns_confidence(self, matcher: SkillMatcher) -> None:
        """匹配结果包含有效置信度。"""
        results = matcher.match("搜索天气")
        assert len(results) > 0
        for r in results:
            assert 0.0 <= r.confidence <= 1.0

    def test_no_match_for_gibberish(self, matcher: SkillMatcher) -> None:
        """乱码指令不应匹配到任何技能。"""
        results = matcher.match("xyzqwerty12345", min_confidence=0.3)
        # 乱码可能返回低分结果，但不应有高分匹配
        for r in results:
            assert r.confidence < 0.8


# ======================================================================
# 3. 执行确认测试
# ======================================================================


class TestExecutionConfirm:
    """验证执行确认机制。"""

    def test_high_confidence_auto_execute(self, executor: SkillExecutor) -> None:
        """高置信度指令应自动执行（精确触发词 → 满分）。"""
        result = executor.evaluate("关闭窗口")
        assert result.level == ConfirmLevel.AUTO_EXECUTE, (
            f"期望 AUTO_EXECUTE，实际 {result.level}，置信度 {result.best_confidence}"
        )

    def test_search_auto_execute(self, executor: SkillExecutor) -> None:
        """搜索类指令应自动执行。"""
        result = executor.evaluate("搜索天气")
        assert result.level in (ConfirmLevel.AUTO_EXECUTE, ConfirmLevel.NEED_CONFIRM)

    def test_empty_query_no_match(self, executor: SkillExecutor) -> None:
        """空查询应返回 NO_MATCH。"""
        result = executor.evaluate("")
        assert result.level == ConfirmLevel.NO_MATCH

    def test_obscure_query_no_match(self, executor: SkillExecutor) -> None:
        """不明确的查询应低置信度。"""
        result = executor.evaluate("随便做点什么xyz")
        # 低置信度 → NO_MATCH 或至少不是 AUTO_EXECUTE
        if result.level == ConfirmLevel.AUTO_EXECUTE:
            pytest.fail("模糊指令不应自动执行")

    def test_result_has_message(self, executor: SkillExecutor) -> None:
        """执行结果包含消息。"""
        result = executor.evaluate("截图")
        assert result.message, "执行结果缺少消息"


# ======================================================================
# 4. 结果评分测试
# ======================================================================


class TestResultTracker:
    """验证技能执行结果评分。"""

    def test_record_success(self, tmp_tracker: ResultTracker) -> None:
        """记录成功结果。"""
        tmp_tracker.record(SkillResult(
            skill_name="打开应用程序",
            rating=ResultRating.SUCCESS,
            confidence=0.95,
            query="打开微信",
        ))
        assert len(tmp_tracker.results) == 1
        assert tmp_tracker.results[0].rating == ResultRating.SUCCESS

    def test_record_failure(self, tmp_tracker: ResultTracker) -> None:
        """记录失败结果。"""
        tmp_tracker.record(SkillResult(
            skill_name="打开应用程序",
            rating=ResultRating.FAILURE,
            confidence=0.7,
            query="打开xxx",
            error_message="应用未找到",
        ))
        assert tmp_tracker.results[0].rating == ResultRating.FAILURE

    def test_record_partial(self, tmp_tracker: ResultTracker) -> None:
        """记录部分成功结果。"""
        tmp_tracker.record(SkillResult(
            skill_name="浏览器搜索信息",
            rating=ResultRating.PARTIAL,
            confidence=0.8,
            query="搜索天气",
            steps_total=6,
            steps_completed=4,
        ))
        assert tmp_tracker.results[0].rating == ResultRating.PARTIAL
        assert tmp_tracker.results[0].steps_completed == 4

    def test_stats_calculation(self, tmp_tracker: ResultTracker) -> None:
        """统计计算正确。"""
        tmp_tracker.record(SkillResult(
            skill_name="打开应用程序", rating=ResultRating.SUCCESS, confidence=0.9,
        ))
        tmp_tracker.record(SkillResult(
            skill_name="打开应用程序", rating=ResultRating.SUCCESS, confidence=0.85,
        ))
        tmp_tracker.record(SkillResult(
            skill_name="打开应用程序", rating=ResultRating.FAILURE, confidence=0.7,
        ))

        stats = tmp_tracker.get_stats("打开应用程序")
        assert stats["total"] == 3
        assert stats["success"] == 2
        assert stats["failure"] == 1
        assert stats["success_rate"] == pytest.approx(2 / 3, abs=0.01)

    def test_persistence(self, tmp_path: Path) -> None:
        """结果持久化到文件。"""
        path = tmp_path / "persist_test.jsonl"
        tracker1 = ResultTracker(storage_path=path)
        tracker1.record(SkillResult(
            skill_name="测试技能", rating=ResultRating.SUCCESS, confidence=0.9,
        ))

        # 新实例从文件加载
        tracker2 = ResultTracker(storage_path=path)
        assert len(tracker2.results) == 1
        assert tracker2.results[0].skill_name == "测试技能"

    def test_result_serialization(self) -> None:
        """SkillResult 序列化/反序列化。"""
        result = SkillResult(
            skill_name="截图",
            rating=ResultRating.SUCCESS,
            confidence=0.95,
            query="截个屏",
            steps_total=3,
            steps_completed=3,
        )
        data = result.to_dict()
        assert data["rating"] == "success"
        assert data["skill_name"] == "截图"

        restored = SkillResult.from_dict(data)
        assert restored.skill_name == result.skill_name
        assert restored.rating == result.rating
        assert restored.confidence == result.confidence

    def test_rating_enum_values(self) -> None:
        """ResultRating 枚举值正确。"""
        assert ResultRating.SUCCESS.value == "success"
        assert ResultRating.FAILURE.value == "failure"
        assert ResultRating.PARTIAL.value == "partial"


# ======================================================================
# 5. 端到端集成测试
# ======================================================================


class TestEndToEnd:
    """完整链路集成测试：加载 → 匹配 → 执行确认 → 评分。"""

    def test_full_pipeline_search(self, executor: SkillExecutor, tmp_tracker: ResultTracker) -> None:
        """完整链路：搜索场景。"""
        # 1. 评估指令（使用精确触发词 "搜索" 确保高置信度）
        result = executor.evaluate("搜索 Python 教程")
        assert result.level in (ConfirmLevel.AUTO_EXECUTE, ConfirmLevel.NEED_CONFIRM)
        assert result.best_match is not None

        # 2. 记录执行结果
        skill = result.best_match.skill
        tmp_tracker.record(SkillResult(
            skill_name=skill.name,
            rating=ResultRating.SUCCESS,
            confidence=result.best_confidence,
            query="搜索 Python 教程",
            steps_total=len(skill.steps),
            steps_completed=len(skill.steps),
        ))

        # 3. 验证追踪
        stats = tmp_tracker.get_stats(skill.name)
        assert stats["total"] == 1
        assert stats["success"] == 1
        assert stats["success_rate"] == 1.0

    def test_full_pipeline_notepad(self, executor: SkillExecutor, tmp_tracker: ResultTracker) -> None:
        """完整链路：记事本场景。"""
        result = executor.evaluate("写个备忘录")
        assert result.best_match is not None

        skill = result.best_match.skill
        tmp_tracker.record(SkillResult(
            skill_name=skill.name,
            rating=ResultRating.PARTIAL,
            confidence=result.best_confidence,
            query="写个备忘录",
            steps_total=len(skill.steps),
            steps_completed=3,
            error_message="保存失败",
        ))

        stats = tmp_tracker.get_stats(skill.name)
        assert stats["total"] == 1
        assert stats["partial"] == 1

    def test_full_pipeline_close_window(self, executor: SkillExecutor, tmp_tracker: ResultTracker) -> None:
        """完整链路：关闭窗口。"""
        result = executor.evaluate("关闭窗口")
        assert result.best_match is not None

        skill = result.best_match.skill
        tmp_tracker.record(SkillResult(
            skill_name=skill.name,
            rating=ResultRating.SUCCESS,
            confidence=result.best_confidence,
            query="关闭窗口",
        ))

        assert tmp_tracker.get_stats(skill.name)["success_rate"] == 1.0
