"""UserPreferenceEngine 用户偏好学习引擎测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.memory.user_preference import UserPreferenceEngine
from src.memory.user_preference_models import PreferenceData, WorkHourPattern


# ──────────────────────────────
# Fixtures
# ──────────────────────────────


@pytest.fixture
def tmp_pref_path(tmp_path: Path) -> Path:
    """临时偏好文件路径。"""
    return tmp_path / "preferences.json"


@pytest.fixture
def engine(tmp_pref_path: Path) -> UserPreferenceEngine:
    """已初始化的偏好引擎。"""
    eng = UserPreferenceEngine(storage_path=tmp_pref_path)
    asyncio.get_event_loop().run_until_complete(eng.initialize())
    return eng


# ──────────────────────────────
# 1. 初始化与持久化
# ──────────────────────────────


class TestInitializeAndPersistence:
    """测试引擎初始化和 save/load 循环。"""

    def test_initialize_creates_empty_data(self, tmp_pref_path: Path) -> None:
        """文件不存在时初始化应创建空偏好数据。"""
        eng = UserPreferenceEngine(storage_path=tmp_pref_path)
        asyncio.get_event_loop().run_until_complete(eng.initialize())

        assert eng._data.total_interactions == 0
        assert len(eng._data.tool_usage) == 0

    def test_save_and_reload(self, tmp_pref_path: Path) -> None:
        """保存后重新加载应恢复之前的数据。"""
        # 写入
        eng1 = UserPreferenceEngine(storage_path=tmp_pref_path)
        asyncio.get_event_loop().run_until_complete(eng1.initialize())
        eng1.record_tool_usage("browser", "open", True, 200)
        eng1.record_tool_usage("terminal", "exec", True, 150)
        asyncio.get_event_loop().run_until_complete(eng1.save())

        # 读取
        eng2 = UserPreferenceEngine(storage_path=tmp_pref_path)
        asyncio.get_event_loop().run_until_complete(eng2.initialize())

        assert eng2._data.total_interactions == 2
        assert "browser" in eng2._data.tool_usage
        assert eng2._data.tool_usage["browser"]["count"] == 1

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        """保存时应自动创建不存在的父目录。"""
        nested = tmp_path / "deep" / "nested" / "prefs.json"
        eng = UserPreferenceEngine(storage_path=nested)
        asyncio.get_event_loop().run_until_complete(eng.initialize())
        asyncio.get_event_loop().run_until_complete(eng.save())

        assert nested.exists()
        data = json.loads(nested.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_corrupted_file_fallback(self, tmp_pref_path: Path) -> None:
        """损坏的 JSON 文件应回退到空数据。"""
        tmp_pref_path.write_text("{bad json", encoding="utf-8")
        eng = UserPreferenceEngine(storage_path=tmp_pref_path)
        asyncio.get_event_loop().run_until_complete(eng.initialize())

        assert eng._data.total_interactions == 0

    def test_double_initialize_idempotent(self, tmp_pref_path: Path) -> None:
        """重复调用 initialize 不应重复加载数据。"""
        eng = UserPreferenceEngine(storage_path=tmp_pref_path)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(eng.initialize())
        eng.record_tool_usage("x", "y", True, 10)
        loop.run_until_complete(eng.initialize())

        # 仍为内存中的数据，不会被覆盖
        assert eng._data.total_interactions == 1


# ──────────────────────────────
# 2. 工具使用记录与偏好分数
# ──────────────────────────────


class TestToolUsageAndPreferenceScore:
    """测试工具使用记录和偏好分数计算。"""

    def test_record_single_usage(self, engine: UserPreferenceEngine) -> None:
        """记录单次工具使用。"""
        engine.record_tool_usage("browser", "open", True, 320)

        entry = engine._data.tool_usage["browser"]
        assert entry["count"] == 1
        assert entry["success_count"] == 1
        assert entry["total_duration_ms"] == 320

    def test_record_multiple_usages(self, engine: UserPreferenceEngine) -> None:
        """多次记录应累加。"""
        engine.record_tool_usage("browser", "open", True, 100)
        engine.record_tool_usage("browser", "open", False, 200)
        engine.record_tool_usage("browser", "open", True, 150)

        entry = engine._data.tool_usage["browser"]
        assert entry["count"] == 3
        assert entry["success_count"] == 2
        assert entry["total_duration_ms"] == 450

    def test_preference_score_no_record(self, engine: UserPreferenceEngine) -> None:
        """无记录的工具返回 0.0。"""
        assert engine.get_preference_score("unknown", "x") == 0.0

    def test_preference_score_single_success(self, engine: UserPreferenceEngine) -> None:
        """单次成功使用应返回较高分数。"""
        engine.record_tool_usage("browser", "open", True, 100)
        score = engine.get_preference_score("browser", "open")
        assert 0.0 < score <= 1.0

    def test_preference_score_all_failures(self, engine: UserPreferenceEngine) -> None:
        """全部失败的工具分数应较低。"""
        for _ in range(5):
            engine.record_tool_usage("bad_tool", "run", False, 50)

        score = engine.get_preference_score("bad_tool", "run")
        # freq_norm 可能 > 0 但 success_rate = 0
        assert score < 0.5

    def test_get_preferred_tools_ranking(self, engine: UserPreferenceEngine) -> None:
        """get_preferred_tools 应按偏好分数排序。"""
        # 高频高成功率
        for _ in range(10):
            engine.record_tool_usage("browser", "open", True, 100)
        # 低频
        engine.record_tool_usage("editor", "open", True, 100)

        tools = engine.get_preferred_tools("")
        assert len(tools) == 2
        assert tools[0] == "browser"

    def test_get_preferred_tools_filter_by_task(self, engine: UserPreferenceEngine) -> None:
        """指定 task_type 时应过滤工具。"""
        engine.record_tool_usage("browser", "open", True, 100)
        engine.record_tool_usage("editor", "open", True, 100)

        tools = engine.get_preferred_tools("browser")
        assert "browser" in tools
        assert "editor" not in tools

    def test_get_preferred_tools_empty(self, engine: UserPreferenceEngine) -> None:
        """无记录时返回空列表。"""
        assert engine.get_preferred_tools("web") == []


# ──────────────────────────────
# 3. 工作时间模式
# ──────────────────────────────


class TestWorkHoursPattern:
    """测试工作时间记录和活跃时间查询。"""

    def test_record_weekday_hours(self, engine: UserPreferenceEngine) -> None:
        """记录工作日活跃时间。"""
        for _ in range(5):
            engine.record_work_hours(9, True)
            engine.record_work_hours(10, True)

        pattern = engine._data.work_hours.weekday_hours
        assert pattern[9] == 5
        assert pattern[10] == 5

    def test_record_inactive_ignored(self, engine: UserPreferenceEngine) -> None:
        """记录不活跃的时间不应增加计数。"""
        engine.record_work_hours(3, False)
        assert 3 not in engine._data.work_hours.weekday_hours

    def test_record_invalid_hour_ignored(self, engine: UserPreferenceEngine) -> None:
        """无效小时值应被忽略。"""
        engine.record_work_hours(-1, True)
        engine.record_work_hours(24, True)
        assert len(engine._data.work_hours.weekday_hours) == 0

    def test_get_active_hours_threshold(self, engine: UserPreferenceEngine) -> None:
        """只有达到阈值的时段才返回。"""
        # 只记2次（低于阈值3）
        engine.record_work_hours(8, True)
        engine.record_work_hours(8, True)
        # 记5次（达到阈值）
        for _ in range(5):
            engine.record_work_hours(14, True)

        result = engine.get_active_hours()
        assert 8 not in result["weekday"]
        assert 14 in result["weekday"]

    def test_record_weekend_hours(self, engine: UserPreferenceEngine) -> None:
        """区分周末时间记录。"""
        for _ in range(5):
            engine.record_work_hours_v2(11, True, is_weekend=True)

        result = engine.get_active_hours()
        assert 11 in result["weekend"]

    def test_active_hours_sorted(self, engine: UserPreferenceEngine) -> None:
        """返回的活跃小时应排序。"""
        for h in [22, 9, 14, 18]:
            for _ in range(4):
                engine.record_work_hours(h, True)

        result = engine.get_active_hours()
        assert result["weekday"] == sorted(result["weekday"])


# ──────────────────────────────
# 4. 反馈与风险偏好
# ──────────────────────────────


class TestFeedbackAndRiskTolerance:
    """测试用户反馈记录和风险偏好推断。"""

    def test_record_feedback_basic(self, engine: UserPreferenceEngine) -> None:
        """记录基本反馈。"""
        engine.record_feedback("打开了浏览器", 5)

        assert len(engine._data.feedback_history) == 1
        assert engine._data.feedback_history[0]["rating"] == 5

    def test_low_rating_increases_risk_events(self, engine: UserPreferenceEngine) -> None:
        """低评分（<=2）应增加纠正计数。"""
        engine.record_feedback("动作A", 1)
        engine.record_feedback("动作B", 2)
        engine.record_feedback("动作C", 5)

        assert engine._data.risk_events == 2

    def test_rating_clamped(self, engine: UserPreferenceEngine) -> None:
        """评分应被限制在 1-5 范围。"""
        engine.record_feedback("动作", 0)
        assert engine._data.feedback_history[0]["rating"] == 1

        engine.record_feedback("动作", 10)
        assert engine._data.feedback_history[1]["rating"] == 5

    def test_feedback_history_capped_at_100(self, engine: UserPreferenceEngine) -> None:
        """反馈历史不应超过 100 条。"""
        for i in range(150):
            engine.record_feedback(f"动作{i}", 3)

        assert len(engine._data.feedback_history) == 100
        # 最旧的被淘汰
        assert engine._data.feedback_history[0]["action"] == "动作50"

    def test_risk_tolerance_default_moderate(self, engine: UserPreferenceEngine) -> None:
        """无记录时默认 moderate。"""
        assert engine.get_risk_tolerance() == "moderate"

    def test_risk_tolerance_cautious(self, engine: UserPreferenceEngine) -> None:
        """高纠正率 → cautious。"""
        # 10次低评分纠正 + 5次正常 = 15次交互, 纠正率 10/15 ≈ 0.67 > 0.30
        for _ in range(10):
            engine.record_feedback("纠正动作", 1)
        for _ in range(5):
            engine.record_feedback("正常动作", 4)

        assert engine.get_risk_tolerance() == "cautious"

    def test_risk_tolerance_aggressive(self, engine: UserPreferenceEngine) -> None:
        """低纠正率 → aggressive。"""
        # 1次纠正 + 50次正常 = 51次, 纠正率 1/51 ≈ 0.02 < 0.10
        engine.record_feedback("纠正动作", 1)
        for _ in range(50):
            engine.record_feedback("正常动作", 5)

        assert engine.get_risk_tolerance() == "aggressive"


# ──────────────────────────────
# 5. 命令快捷方式
# ──────────────────────────────


class TestCommandShortcuts:
    """测试命令模式记录和快捷方式提取。"""

    def test_record_command_pattern(self, engine: UserPreferenceEngine) -> None:
        """记录命令模式。"""
        engine.record_command_pattern("打开浏览器", 10, "chat")
        engine.record_command_pattern("打开浏览器", 14, "chat")

        assert engine._data.command_patterns["打开浏览器"] == 2

    def test_command_normalized(self, engine: UserPreferenceEngine) -> None:
        """命令应被归一化（小写、去空格）。"""
        engine.record_command_pattern("  Hello World  ", 10, "cli")
        assert "hello world" in engine._data.command_patterns

    def test_empty_command_ignored(self, engine: UserPreferenceEngine) -> None:
        """空命令应被忽略。"""
        engine.record_command_pattern("   ", 10, "cli")
        assert len(engine._data.command_patterns) == 0

    def test_get_command_shortcuts_min_count(self, engine: UserPreferenceEngine) -> None:
        """出现 < 3 次的命令不应生成快捷方式。"""
        engine.record_command_pattern("打开浏览器", 10, "chat")
        engine.record_command_pattern("打开浏览器", 14, "chat")

        shortcuts = engine.get_command_shortcuts()
        assert len(shortcuts) == 0

    def test_get_command_shortcuts_frequent(self, engine: UserPreferenceEngine) -> None:
        """出现 >= 3 次的命令应生成快捷方式。"""
        for _ in range(5):
            engine.record_command_pattern("打开浏览器", 10, "chat")

        shortcuts = engine.get_command_shortcuts()
        assert len(shortcuts) == 1
        # 中文无空格分词，快捷方式即原命令
        assert "打开浏览器" in shortcuts

    def test_shortcuts_persistence(self, tmp_pref_path: Path) -> None:
        """命令模式应在持久化后保留。"""
        eng1 = UserPreferenceEngine(storage_path=tmp_pref_path)
        asyncio.get_event_loop().run_until_complete(eng1.initialize())
        for _ in range(5):
            eng1.record_command_pattern("运行测试", 10, "cli")
        asyncio.get_event_loop().run_until_complete(eng1.save())

        eng2 = UserPreferenceEngine(storage_path=tmp_pref_path)
        asyncio.get_event_loop().run_until_complete(eng2.initialize())

        shortcuts = eng2.get_command_shortcuts()
        assert len(shortcuts) == 1


# ──────────────────────────────
# 6. 统计信息
# ──────────────────────────────


class TestGetStats:
    """测试 get_stats 返回值。"""

    def test_stats_empty(self, engine: UserPreferenceEngine) -> None:
        """空引擎的统计。"""
        stats = engine.get_stats()
        assert stats["total_interactions"] == 0
        assert stats["tool_count"] == 0
        assert stats["tool_ranking"] == []
        assert stats["risk_tolerance"] == "moderate"

    def test_stats_after_usage(self, engine: UserPreferenceEngine) -> None:
        """记录使用后的统计。"""
        for _ in range(3):
            engine.record_tool_usage("browser", "open", True, 100)
        engine.record_tool_usage("terminal", "exec", False, 500)
        engine.record_feedback("操作", 5)

        stats = engine.get_stats()
        assert stats["total_interactions"] == 5
        assert stats["tool_count"] == 2
        assert stats["tool_ranking"][0]["name"] == "browser"
        assert stats["tool_ranking"][0]["count"] == 3
        assert stats["tool_ranking"][0]["success_rate"] == 1.0
        assert stats["feedback_count"] == 1

    def test_stats_tool_ranking_sorted(self, engine: UserPreferenceEngine) -> None:
        """工具排名应按使用次数降序。"""
        engine.record_tool_usage("c_tool", "x", True, 10)
        for _ in range(5):
            engine.record_tool_usage("a_tool", "x", True, 10)
        for _ in range(3):
            engine.record_tool_usage("b_tool", "x", True, 10)

        stats = engine.get_stats()
        names = [r["name"] for r in stats["tool_ranking"]]
        assert names == ["a_tool", "b_tool", "c_tool"]

    def test_stats_avg_duration(self, engine: UserPreferenceEngine) -> None:
        """平均耗时计算。"""
        engine.record_tool_usage("t", "x", True, 100)
        engine.record_tool_usage("t", "x", True, 300)

        stats = engine.get_stats()
        assert stats["tool_ranking"][0]["avg_duration_ms"] == 200.0


# ──────────────────────────────
# 数据模型测试
# ──────────────────────────────


class TestPreferenceDataModels:
    """测试数据模型的序列化和反序列化。"""

    def test_work_hour_pattern_roundtrip(self) -> None:
        """WorkHourPattern 序列化/反序列化往返。"""
        pattern = WorkHourPattern(
            weekday_hours={9: 10, 14: 5},
            weekend_hours={11: 3},
        )
        serialized = pattern.to_dict()
        restored = WorkHourPattern.from_dict(serialized)

        assert restored.weekday_hours == {9: 10, 14: 5}
        assert restored.weekend_hours == {11: 3}

    def test_preference_data_roundtrip(self) -> None:
        """PreferenceData 完整序列化/反序列化往返。"""
        data = PreferenceData(
            tool_usage={"browser": {"count": 5, "success_count": 4, "total_duration_ms": 500}},
            command_patterns={"打开浏览器": 3},
            feedback_history=[{"action": "test", "rating": 4, "timestamp": 1000.0}],
            work_hours=WorkHourPattern(weekday_hours={9: 5}),
            risk_events=1,
            total_interactions=10,
            last_updated=2000.0,
        )
        serialized = data.to_dict()
        restored = PreferenceData.from_dict(serialized)

        assert restored.tool_usage["browser"]["count"] == 5
        assert restored.command_patterns["打开浏览器"] == 3
        assert restored.work_hours.weekday_hours[9] == 5
        assert restored.risk_events == 1
        assert restored.total_interactions == 10
