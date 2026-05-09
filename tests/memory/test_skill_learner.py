"""测试技能学习器模块。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.core.models import ExecutionResult, PlanStatus, Priority, Step, StepStatus, TaskPlan
from src.memory.skill_learner import SkillLearner, _make_pattern_key
from src.memory.skill_models import LearnedPattern, SkillDefinition, SkillSuggestion


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def run(coro):
    """同步运行异步函数。"""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def learner(tmp_path: Path) -> SkillLearner:
    """创建使用临时目录的学习器。"""
    lrn = SkillLearner(
        storage_dir=tmp_path / "learned_patterns",
        min_success_count=3,
        min_success_rate=0.6,
    )
    run(lrn.initialize())
    return lrn


@pytest.fixture
def learner_memory() -> SkillLearner:
    """纯内存模式的学习器。"""
    return SkillLearner(min_success_count=3)


def _make_plan(
    steps: list[tuple[str, str]] | None = None,
    plan_id: str = "plan_001",
) -> TaskPlan:
    """创建测试用任务计划。

    Args:
        steps: [(action, tool), ...] 列表
        plan_id: 计划 ID
    """
    if steps is None:
        steps = [("read", "system_control"), ("write", "system_control")]

    task_steps = [
        Step(id=f"step_{i}", action=action, tool=tool)
        for i, (action, tool) in enumerate(steps)
    ]
    return TaskPlan(id=plan_id, intent="test", steps=task_steps)


def _make_result(
    plan_id: str = "plan_001",
    success: bool = True,
    completed_steps: int = 2,
    total_steps: int = 2,
) -> ExecutionResult:
    """创建测试用执行结果。"""
    return ExecutionResult(
        plan_id=plan_id,
        success=success,
        completed_steps=completed_steps,
        total_steps=total_steps,
    )


# ---------------------------------------------------------------------------
# 记录执行
# ---------------------------------------------------------------------------


class TestRecordExecution:
    async def test_record_success(self, learner: SkillLearner):
        plan = _make_plan()
        result = _make_result(success=True)

        await learner.record_execution(plan, result)
        assert learner.pattern_count == 1

        patterns = await learner.analyze_patterns()
        assert patterns[0].success_count == 1
        assert patterns[0].failure_count == 0

    async def test_record_failure(self, learner: SkillLearner):
        plan = _make_plan()
        result = _make_result(success=False)

        await learner.record_execution(plan, result)
        patterns = await learner.analyze_patterns()
        assert patterns[0].failure_count == 1
        assert patterns[0].success_count == 0

    async def test_record_same_pattern_multiple_times(self, learner: SkillLearner):
        """相同步骤序列应归入同一模式。"""
        for i in range(5):
            plan = _make_plan(plan_id=f"plan_{i}")
            result = _make_result(success=True, plan_id=f"plan_{i}")
            await learner.record_execution(plan, result)

        assert learner.pattern_count == 1
        patterns = await learner.analyze_patterns()
        assert patterns[0].success_count == 5

    async def test_record_different_patterns(self, learner: SkillLearner):
        """不同步骤序列应创建不同模式。"""
        plan1 = _make_plan(steps=[("read", "tool_a")])
        plan2 = _make_plan(steps=[("write", "tool_b")])

        await learner.record_execution(plan1, _make_result(success=True))
        await learner.record_execution(plan2, _make_result(success=True))

        assert learner.pattern_count == 2

    async def test_record_empty_plan_skipped(self, learner: SkillLearner):
        """无步骤的计划应被跳过。"""
        plan = TaskPlan(id="empty_plan", intent="empty")
        result = _make_result(plan_id="empty_plan")

        await learner.record_execution(plan, result)
        assert learner.pattern_count == 0

    async def test_tools_extracted(self, learner: SkillLearner):
        plan = _make_plan(steps=[
            ("read", "system_control"),
            ("write", "browser_control"),
            ("exec", "system_control"),  # 重复 tool
        ])
        result = _make_result(success=True)
        await learner.record_execution(plan, result)

        patterns = await learner.analyze_patterns()
        assert set(patterns[0].tools_used) == {"system_control", "browser_control"}


# ---------------------------------------------------------------------------
# 分析模式
# ---------------------------------------------------------------------------


class TestAnalyzePatterns:
    async def test_analyze_sorted_by_success_count(self, learner: SkillLearner):
        # 模式 A: 5 次成功
        plan_a = _make_plan(steps=[("a", "tool_a")], plan_id="a")
        for _ in range(5):
            await learner.record_execution(plan_a, _make_result(success=True))

        # 模式 B: 2 次成功
        plan_b = _make_plan(steps=[("b", "tool_b")], plan_id="b")
        for _ in range(2):
            await learner.record_execution(plan_b, _make_result(success=True))

        patterns = await learner.analyze_patterns()
        assert len(patterns) == 2
        assert patterns[0].success_count >= patterns[1].success_count

    async def test_analyze_empty(self, learner: SkillLearner):
        patterns = await learner.analyze_patterns()
        assert patterns == []


# ---------------------------------------------------------------------------
# 建议注册
# ---------------------------------------------------------------------------


class TestSuggestSkills:
    async def test_suggest_when_threshold_met(self, learner: SkillLearner):
        """成功次数达到阈值时应生成建议。"""
        plan = _make_plan(steps=[("action", "tool_x")])
        for i in range(4):
            await learner.record_execution(plan, _make_result(success=True))

        suggestions = await learner.suggest_skills()
        assert len(suggestions) == 1
        assert suggestions[0].status == "pending"
        assert suggestions[0].suggested_category == "learned"

    async def test_no_suggest_below_threshold(self, learner: SkillLearner):
        """成功次数未达阈值时不应生成建议。"""
        plan = _make_plan(steps=[("action", "tool_x")])
        for i in range(2):  # 只 2 次，低于阈值 3
            await learner.record_execution(plan, _make_result(success=True))

        suggestions = await learner.suggest_skills()
        assert len(suggestions) == 0

    async def test_no_suggest_low_success_rate(self, learner: SkillLearner):
        """成功率低于阈值时不应生成建议。"""
        plan = _make_plan(steps=[("action", "tool_x")])
        # 3 次成功，3 次失败 = 50% < 60%
        for _ in range(3):
            await learner.record_execution(plan, _make_result(success=True))
        for _ in range(3):
            await learner.record_execution(plan, _make_result(success=False))

        suggestions = await learner.suggest_skills()
        assert len(suggestions) == 0

    async def test_suggest_idempotent(self, learner: SkillLearner):
        """重复调用不应重复生成建议。"""
        plan = _make_plan(steps=[("action", "tool_x")])
        for _ in range(4):
            await learner.record_execution(plan, _make_result(success=True))

        s1 = await learner.suggest_skills()
        s2 = await learner.suggest_skills()
        assert len(s1) == 1
        assert len(s2) == 0  # 已有 pending 建议，不再生成


class TestApproveSuggestion:
    async def test_approve_creates_skill(self, learner: SkillLearner):
        plan = _make_plan(steps=[("action", "tool_x")])
        for _ in range(4):
            await learner.record_execution(plan, _make_result(success=True))

        suggestions = await learner.suggest_skills()
        suggestion_id = suggestions[0].id

        skill = await learner.approve_suggestion(suggestion_id)
        assert isinstance(skill, SkillDefinition)
        assert skill.source == "auto_learned"
        assert skill.category == "learned"
        assert skill.name.startswith("workflow_")
        assert len(skill.pattern_steps) > 0

    async def test_approve_nonexistent_raises(self, learner: SkillLearner):
        with pytest.raises(KeyError):
            await learner.approve_suggestion("nonexistent")

    async def test_approve_non_pending_raises(self, learner: SkillLearner):
        plan = _make_plan(steps=[("action", "tool_x")])
        for _ in range(4):
            await learner.record_execution(plan, _make_result(success=True))

        suggestions = await learner.suggest_skills()
        sid = suggestions[0].id

        # 先 approve
        await learner.approve_suggestion(sid)

        # 再次 approve 应报错
        with pytest.raises(ValueError):
            await learner.approve_suggestion(sid)


class TestRejectSuggestion:
    async def test_reject_pending(self, learner: SkillLearner):
        plan = _make_plan(steps=[("action", "tool_x")])
        for _ in range(4):
            await learner.record_execution(plan, _make_result(success=True))

        suggestions = await learner.suggest_skills()
        sid = suggestions[0].id

        result = await learner.reject_suggestion(sid)
        assert result is True
        assert len(learner.pending_suggestions) == 0

    async def test_reject_nonexistent(self, learner: SkillLearner):
        result = await learner.reject_suggestion("nonexistent")
        assert result is False


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------


class TestPersistence:
    async def test_save_and_reload(self, tmp_path: Path):
        storage_dir = tmp_path / "learned_patterns"

        # 创建并记录
        lrn1 = SkillLearner(storage_dir=storage_dir, min_success_count=3)
        await lrn1.initialize()

        plan = _make_plan(steps=[("action", "tool_x")])
        for _ in range(4):
            await lrn1.record_execution(plan, _make_result(success=True))

        await lrn1.suggest_skills()
        await lrn1.save()

        # 重新加载
        lrn2 = SkillLearner(storage_dir=storage_dir, min_success_count=3)
        await lrn2.initialize()

        assert lrn2.pattern_count == 1
        assert lrn2.suggestion_count == 1

    async def test_memory_mode_no_persistence(self, learner_memory: SkillLearner):
        plan = _make_plan()
        await learner_memory.record_execution(plan, _make_result(success=True))
        # save 不应报错
        await learner_memory.save()
        assert learner_memory.pattern_count == 1


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


class TestMakePatternKey:
    def test_same_input_same_key(self):
        key1 = _make_pattern_key(["a", "b"], ["tool1"])
        key2 = _make_pattern_key(["a", "b"], ["tool1"])
        assert key1 == key2

    def test_different_steps_different_key(self):
        key1 = _make_pattern_key(["a", "b"], ["tool1"])
        key2 = _make_pattern_key(["b", "a"], ["tool1"])
        assert key1 != key2

    def test_tool_order_irrelevant(self):
        """工具列表顺序不同应产生相同的 key。"""
        key1 = _make_pattern_key(["a"], ["tool1", "tool2"])
        key2 = _make_pattern_key(["a"], ["tool2", "tool1"])
        assert key1 == key2


# ---------------------------------------------------------------------------
# 统计属性
# ---------------------------------------------------------------------------


class TestProperties:
    async def test_pattern_count(self, learner: SkillLearner):
        assert learner.pattern_count == 0
        await learner.record_execution(_make_plan(), _make_result())
        assert learner.pattern_count == 1

    async def test_suggestion_count(self, learner: SkillLearner):
        assert learner.suggestion_count == 0

    async def test_pending_suggestions(self, learner: SkillLearner):
        plan = _make_plan(steps=[("action", "tool_x")])
        for _ in range(4):
            await learner.record_execution(plan, _make_result(success=True))
        await learner.suggest_skills()

        pending = learner.pending_suggestions
        assert len(pending) == 1
        assert all(s.status == "pending" for s in pending)


# ---------------------------------------------------------------------------
# 数据模型序列化
# ---------------------------------------------------------------------------


class TestLearnedPatternSerialization:
    def test_to_dict_and_from_dict(self):
        import datetime

        now = datetime.datetime.now()
        pattern = LearnedPattern(
            id="pat_123",
            pattern_key="abc123",
            steps=["step1", "step2"],
            tools_used=["tool_a"],
            success_count=5,
            failure_count=1,
            last_seen_at=now,
            first_seen_at=now,
        )

        d = pattern.to_dict()
        restored = LearnedPattern.from_dict(d)

        assert restored.id == pattern.id
        assert restored.pattern_key == pattern.pattern_key
        assert restored.steps == pattern.steps
        assert restored.success_count == 5
        assert restored.success_rate == 5 / 6

    def test_total_count_and_success_rate(self):
        pattern = LearnedPattern(
            id="pat_1",
            pattern_key="k",
            steps=[],
            tools_used=[],
            success_count=3,
            failure_count=1,
        )
        assert pattern.total_count == 4
        assert pattern.success_rate == 0.75


class TestSkillSuggestionSerialization:
    def test_to_dict_and_from_dict(self):
        import datetime

        now = datetime.datetime.now()
        pattern = LearnedPattern(
            id="pat_1",
            pattern_key="k",
            steps=["s1"],
            tools_used=["t1"],
        )
        suggestion = SkillSuggestion(
            id="sug_1",
            pattern=pattern,
            suggested_name="test_skill",
            suggested_description="test desc",
            created_at=now,
        )

        d = suggestion.to_dict()
        restored = SkillSuggestion.from_dict(d)

        assert restored.id == "sug_1"
        assert restored.suggested_name == "test_skill"
        assert restored.pattern.pattern_key == "k"
