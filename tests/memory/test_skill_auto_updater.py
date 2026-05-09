"""测试技能自动优化器模块。"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.core.models import (
    ExecutionResult,
    PlanStatus,
    Priority,
    Step,
    StepStatus,
    TaskPlan,
)
from src.memory.skill_auto_updater import REGISTER_THRESHOLD, SkillAutoUpdater
from src.memory.skill_auto_updater_models import SkillUpdate, ToolUsageRecord
from src.memory.skill_models import LearnedPattern, SkillDefinition, SkillSuggestion
from src.memory.skill_registry import SkillRegistry


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def run(coro):
    """同步运行异步函数。"""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def registry(tmp_path: Path) -> SkillRegistry:
    """创建使用临时目录的技能注册表。"""
    reg = SkillRegistry(storage_dir=tmp_path / "skills")
    run(reg.initialize())
    return reg


@pytest.fixture
def updater(registry: SkillRegistry, tmp_path: Path) -> SkillAutoUpdater:
    """创建使用临时目录的技能自动优化器。"""
    return SkillAutoUpdater(
        skill_registry=registry,
        data_dir=tmp_path / "data",
    )


def _make_pattern(
    tools: list[str] | None = None,
    success_count: int = 3,
    failure_count: int = 0,
) -> LearnedPattern:
    """创建测试用学习模式。"""
    tools = tools or ["tool_a"]
    steps = [f"step_{t}" for t in tools]
    return LearnedPattern(
        id=f"pat_test_{id(tools)}",
        pattern_key=f"key_{hash(tuple(tools)) % 10000:04d}",
        steps=steps,
        tools_used=tools,
        success_count=success_count,
        failure_count=failure_count,
    )


def _make_suggestion(
    name: str = "test_skill",
    success_count: int = 3,
    tools: list[str] | None = None,
) -> SkillSuggestion:
    """创建测试用技能建议。"""
    pattern = _make_pattern(
        tools=tools,
        success_count=success_count,
    )
    return SkillSuggestion(
        id=f"sug_test_{id(pattern)}",
        pattern=pattern,
        suggested_name=name,
        suggested_description=f"测试技能: {name}",
        suggested_category="learned",
        status="pending",
    )


def _make_task_plan(
    tools: list[str] | None = None,
    success: bool = True,
) -> TaskPlan:
    """创建测试用任务计划。"""
    tools = tools or ["tool_a"]
    steps: list[Step] = []
    for tool in tools:
        steps.append(Step(
            id=f"step_{tool}",
            action=f"use_{tool}",
            tool=tool,
            status=StepStatus.DONE if success else StepStatus.FAILED,
        ))

    return TaskPlan(
        id=f"plan_test_{id(tools)}",
        intent="测试任务",
        steps=steps,
        status=PlanStatus.DONE if success else PlanStatus.FAILED,
    )


def _make_execution_result(
    plan: TaskPlan,
    success: bool = True,
) -> ExecutionResult:
    """创建测试用执行结果。"""
    completed = sum(1 for s in plan.steps if s.status == StepStatus.DONE)
    return ExecutionResult(
        plan_id=plan.id,
        success=success,
        completed_steps=completed,
        total_steps=len(plan.steps),
    )


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


class TestOnSkillSuggestion:
    """测试技能建议处理。"""

    async def test_on_skill_suggestion_registers_when_threshold_met(
        self, updater: SkillAutoUpdater, registry: SkillRegistry
    ):
        """成功次数达标时自动注册。"""
        suggestion = _make_suggestion(
            name="auto_skill",
            success_count=REGISTER_THRESHOLD,
        )

        registered = await updater.on_skill_suggestion(suggestion)

        assert registered is True
        assert suggestion.status == "approved"
        assert registry.count == 1

        # 验证注册的技能
        skill = await registry.get_by_name("auto_skill")
        assert skill is not None
        assert skill.source == "auto_learned"

    async def test_on_skill_suggestion_not_enough_success(
        self, updater: SkillAutoUpdater, registry: SkillRegistry
    ):
        """成功次数不足时不注册。"""
        suggestion = _make_suggestion(
            name="pending_skill",
            success_count=REGISTER_THRESHOLD - 1,
        )

        registered = await updater.on_skill_suggestion(suggestion)

        assert registered is False
        assert registry.count == 0
        assert len(updater._pending_suggestions) == 1

    async def test_on_skill_suggestion_accumulates_pending(
        self, updater: SkillAutoUpdater
    ):
        """多次建议累积在挂起列表中。"""
        for i in range(3):
            suggestion = _make_suggestion(
                name=f"pending_{i}",
                success_count=1,
                tools=[f"tool_{i}"],
            )
            await updater.on_skill_suggestion(suggestion)

        assert len(updater._pending_suggestions) == 3


class TestGetRecommendedTools:
    """测试工具推荐。"""

    async def test_get_recommended_tools_returns_frequent_tools(
        self, updater: SkillAutoUpdater
    ):
        """根据历史记录推荐高频使用的工具。"""
        # 手动填充工具使用记录
        updater._tool_records["tool_a"] = ToolUsageRecord(
            tool_name="tool_a",
            success_count=10,
            failure_count=1,
            last_used=time.time(),
        )
        updater._tool_records["tool_b"] = ToolUsageRecord(
            tool_name="tool_b",
            success_count=3,
            failure_count=5,
            last_used=time.time(),
        )
        updater._tool_records["tool_c"] = ToolUsageRecord(
            tool_name="tool_c",
            success_count=8,
            failure_count=2,
            last_used=time.time() - 86400 * 30,  # 30 天前
        )

        recommended = updater.get_recommended_tools("任意任务描述")

        # tool_a (10/11, 近期) 应排在最前
        assert len(recommended) == 3
        assert recommended[0] == "tool_a"

    async def test_get_recommended_tools_empty(
        self, updater: SkillAutoUpdater
    ):
        """无记录时返回空列表。"""
        recommended = updater.get_recommended_tools("任意描述")
        assert recommended == []


class TestCleanup:
    """测试过期技能清理。"""

    async def test_cleanup_removes_stale_skills(
        self, updater: SkillAutoUpdater, registry: SkillRegistry
    ):
        """清理长期未使用且成功率低的技能。"""
        # 注册一个自动学习技能
        suggestion = _make_suggestion(
            name="stale_skill",
            success_count=REGISTER_THRESHOLD,
            tools=["stale_tool"],
        )
        await updater.on_skill_suggestion(suggestion)

        # 获取技能 ID
        skill = await registry.get_by_name("stale_skill")
        assert skill is not None
        skill_id = skill.id

        # 模拟注册时间为 31 天前
        update = updater._skill_updates[skill_id]
        update.registered_at = time.time() - 31 * 86400
        update.effectiveness_score = 0.3  # 低有效性

        # 工具也长期未使用
        updater._tool_records["stale_tool"].last_used = time.time() - 31 * 86400

        # 执行清理
        cleaned = await updater.cleanup_stale_skills(days=30)

        assert cleaned == 1
        assert await registry.get(skill_id) is None
        assert skill_id not in updater._skill_updates

    async def test_cleanup_keeps_effective_skills(
        self, updater: SkillAutoUpdater, registry: SkillRegistry
    ):
        """保留高有效性的技能，即使长期未使用。"""
        suggestion = _make_suggestion(
            name="effective_skill",
            success_count=REGISTER_THRESHOLD,
        )
        await updater.on_skill_suggestion(suggestion)

        skill = await registry.get_by_name("effective_skill")
        skill_id = skill.id

        # 模拟注册时间为 31 天前，但有效性高
        update = updater._skill_updates[skill_id]
        update.registered_at = time.time() - 31 * 86400
        update.effectiveness_score = 0.8  # 高有效性

        cleaned = await updater.cleanup_stale_skills(days=30)
        assert cleaned == 0
        assert await registry.get(skill_id) is not None


class TestPersistence:
    """测试持久化。"""

    async def test_save_and_load_state_roundtrip(
        self, registry: SkillRegistry, tmp_path: Path
    ):
        """状态保存后重新加载应完全一致。"""
        data_dir = tmp_path / "data"

        # 创建 updater 并填充数据
        updater1 = SkillAutoUpdater(
            skill_registry=registry,
            data_dir=data_dir,
        )

        # 注册技能
        suggestion = _make_suggestion(
            name="persist_skill",
            success_count=REGISTER_THRESHOLD,
            tools=["tool_persist"],
        )
        await updater1.on_skill_suggestion(suggestion)

        # 添加工具记录
        updater1._tool_records["tool_extra"] = ToolUsageRecord(
            tool_name="tool_extra",
            success_count=5,
            failure_count=1,
            last_used=time.time(),
        )

        # 添加挂起建议
        pending = _make_suggestion(
            name="pending_skill",
            success_count=1,
            tools=["tool_pending"],
        )
        await updater1.on_skill_suggestion(pending)

        # 保存
        updater1.save_state()

        # 创建新实例加载
        updater2 = SkillAutoUpdater(
            skill_registry=registry,
            data_dir=data_dir,
        )
        updater2.load_state()

        # 验证数据完整性
        assert len(updater2._skill_updates) == 1
        assert len(updater2._tool_records) == 2  # tool_persist + tool_extra
        assert len(updater2._pending_suggestions) == 1

        # 验证工具记录值
        loaded_extra = updater2._tool_records["tool_extra"]
        assert loaded_extra.success_count == 5
        assert loaded_extra.failure_count == 1

    async def test_save_creates_json_file(
        self, updater: SkillAutoUpdater, tmp_path: Path
    ):
        """保存后文件存在且内容为合法 JSON。"""
        updater._tool_records["tool_a"] = ToolUsageRecord(
            tool_name="tool_a",
            success_count=1,
        )
        updater.save_state()

        state_file = tmp_path / "data" / "skill_updates.json"
        assert state_file.exists()

        content = state_file.read_text(encoding="utf-8")
        data = json.loads(content)
        assert "tool_records" in data
        assert "tool_a" in data["tool_records"]


class TestOnTaskCompleted:
    """测试任务完成后的更新。"""

    async def test_on_task_completed_updates_usage_record(
        self, updater: SkillAutoUpdater
    ):
        """任务完成后更新工具使用记录。"""
        plan = _make_task_plan(tools=["tool_a", "tool_b"], success=True)
        result = _make_execution_result(plan, success=True)

        await updater.on_task_completed(plan, result)

        # 验证工具记录已更新
        assert "tool_a" in updater._tool_records
        assert "tool_b" in updater._tool_records

        rec_a = updater._tool_records["tool_a"]
        assert rec_a.success_count == 1
        assert rec_a.failure_count == 0
        assert rec_a.last_used > 0

    async def test_on_task_completed_records_failures(
        self, updater: SkillAutoUpdater
    ):
        """任务失败时记录失败次数。"""
        plan = _make_task_plan(tools=["tool_fail"], success=False)
        # 修改步骤状态为失败
        for step in plan.steps:
            step.status = StepStatus.FAILED

        result = _make_execution_result(plan, success=False)

        await updater.on_task_completed(plan, result)

        rec = updater._tool_records["tool_fail"]
        assert rec.failure_count == 1
        assert rec.success_count == 0

    async def test_on_task_completed_updates_existing_record(
        self, updater: SkillAutoUpdater
    ):
        """多次任务完成累积更新使用记录。"""
        for _ in range(3):
            plan = _make_task_plan(tools=["tool_a"], success=True)
            result = _make_execution_result(plan, success=True)
            await updater.on_task_completed(plan, result)

        rec = updater._tool_records["tool_a"]
        assert rec.success_count == 3


class TestEffectivenessScore:
    """测试有效性分数计算。"""

    async def test_effectiveness_score_calculation(
        self, updater: SkillAutoUpdater, registry: SkillRegistry
    ):
        """有效性分数应基于关联工具的成功率计算。"""
        # 注册一个技能（关联 tool_score_a 和 tool_score_b）
        suggestion = _make_suggestion(
            name="scored_skill",
            success_count=REGISTER_THRESHOLD,
            tools=["tool_score_a", "tool_score_b"],
        )
        await updater.on_skill_suggestion(suggestion)

        skill = await registry.get_by_name("scored_skill")
        skill_id = skill.id

        # 预设工具记录（先设置好，再让 on_task_completed 累加）
        updater._tool_records["tool_score_a"] = ToolUsageRecord(
            tool_name="tool_score_a",
            success_count=8,
            failure_count=2,  # 80% 成功率
        )
        updater._tool_records["tool_score_b"] = ToolUsageRecord(
            tool_name="tool_score_b",
            success_count=6,
            failure_count=4,  # 60% 成功率
        )

        # 模拟任务完成触发更新
        # on_task_completed 会给两个工具各加 1 次成功，并更新 effectiveness_score
        plan = _make_task_plan(tools=["tool_score_a", "tool_score_b"], success=True)
        result = _make_execution_result(plan, success=True)
        await updater.on_task_completed(plan, result)

        update = updater._skill_updates[skill_id]
        assert update.usage_count == 1

        # 有效性分数 = 两个工具成功率的均值
        # tool_score_a: (8+1)/(10+1) = 9/11
        # tool_score_b: (6+1)/(10+1) = 7/11
        # avg = (9/11 + 7/11) / 2 = 8/11
        expected = (9 / 11 + 7 / 11) / 2
        assert abs(update.effectiveness_score - expected) < 0.01


class TestAutoRegisterSkills:
    """测试批量自动注册。"""

    async def test_auto_register_registers_pending(
        self, updater: SkillAutoUpdater, registry: SkillRegistry
    ):
        """批量注册所有满足条件的挂起建议。"""
        # 添加多个挂起建议，部分满足条件
        sug1 = _make_suggestion(
            name="batch_1",
            success_count=REGISTER_THRESHOLD,
            tools=["tool_batch_1"],
        )
        sug2 = _make_suggestion(
            name="batch_2",
            success_count=REGISTER_THRESHOLD + 1,
            tools=["tool_batch_2"],
        )
        sug3 = _make_suggestion(
            name="batch_3",
            success_count=1,  # 不满足条件
            tools=["tool_batch_3"],
        )

        await updater.on_skill_suggestion(sug1)
        await updater.on_skill_suggestion(sug2)
        await updater.on_skill_suggestion(sug3)

        # sug1 在 on_skill_suggestion 时已自动注册，sug3 不满足
        # 手动注册 sug2 的 pattern 以满足条件，再调用批量注册
        count = await updater.auto_register_skills()

        # sug2 在首次 on_skill_suggestion 时已自动注册
        # 只剩 sug3 不满足条件
        assert count == 0

    async def test_auto_register_processes_accumulated(
        self, updater: SkillAutoUpdater, registry: SkillRegistry
    ):
        """累积的建议在满足条件后批量注册。"""
        # 先添加一个不满足条件的建议
        sug = _make_suggestion(
            name="accumulated",
            success_count=1,
            tools=["tool_acc"],
        )
        await updater.on_skill_suggestion(sug)

        assert len(updater._pending_suggestions) == 1

        # 模拟模式被验证成功次数增加
        sug.pattern.success_count = REGISTER_THRESHOLD

        # 批量注册
        count = await updater.auto_register_skills()
        assert count == 1
        assert registry.count == 1


class TestGetSkillStats:
    """测试统计信息。"""

    async def test_get_skill_stats_returns_complete_info(
        self, updater: SkillAutoUpdater, registry: SkillRegistry
    ):
        """统计信息包含完整的数据。"""
        # 注册技能
        suggestion = _make_suggestion(
            name="stats_skill",
            success_count=REGISTER_THRESHOLD,
            tools=["tool_stats"],
        )
        await updater.on_skill_suggestion(suggestion)

        # 添加工具记录
        updater._tool_records["tool_stats"] = ToolUsageRecord(
            tool_name="tool_stats",
            success_count=5,
            failure_count=1,
        )

        stats = updater.get_skill_stats()

        assert stats["total_auto_registered"] == 1
        assert stats["tracked_tools"] == 1
        assert stats["pending_suggestions"] == 0
        assert len(stats["tool_records"]) == 1
        assert len(stats["skill_updates"]) == 1

        # 验证工具记录
        tool_stat = stats["tool_records"][0]
        assert tool_stat["tool_name"] == "tool_stats"
        assert tool_stat["success_rate"] == pytest.approx(5 / 6, abs=0.01)
