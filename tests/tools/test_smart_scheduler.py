"""SmartScheduler 智能日程调度工具测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.tools.schedule_models import (
    CalendarEvent,
    Priority,
    SchedulerConfig,
    ScheduleTask,
)
from src.tools.smart_scheduler import (
    SmartScheduler,
    _compute_free_slots,
    _fmt_dt,
    _next_work_time,
    _parse_dt,
    _sort_tasks,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def config() -> SchedulerConfig:
    """标准调度配置。"""
    return SchedulerConfig(
        work_start_hour=9, work_end_hour=18,
        work_days=[0, 1, 2, 3, 4],
        break_between_tasks=15,
        min_task_duration=15,
        default_lookahead_days=7,
    )


@pytest.fixture
def scheduler() -> SmartScheduler:
    """无日历后端的调度器。"""
    return SmartScheduler(calendar_ops=None)


@pytest.fixture
def scheduler_with_mock_cal() -> tuple[SmartScheduler, AsyncMock]:
    """带 mock 日历后端的调度器。"""
    mock_cal = AsyncMock()
    return SmartScheduler(calendar_ops=mock_cal), mock_cal


# ======================================================================
# 辅助函数测试
# ======================================================================


class TestHelpers:
    """辅助函数测试。"""

    def test_parse_dt_formats(self) -> None:
        assert _parse_dt("2025-06-01").day == 1
        assert _parse_dt("2025-06-01 10:30").hour == 10
        assert _parse_dt("2025-06-01T10:30").minute == 30
        assert _parse_dt("2025-06-01 10:30:45").second == 45

    def test_parse_dt_invalid(self) -> None:
        with pytest.raises(ValueError, match="无法解析"):
            _parse_dt("bad-date")

    def test_fmt_dt(self) -> None:
        dt = datetime(2025, 6, 1, 10, 30)
        assert _fmt_dt(dt) == "2025-06-01 10:30"

    def test_next_work_time_weekday(self, config: SchedulerConfig) -> None:
        # 周一 10:00 已经是工作时间
        mon = datetime(2025, 6, 2, 10, 0)  # 周一
        assert _next_work_time(mon, config) == mon

    def test_next_work_time_weekend(self, config: SchedulerConfig) -> None:
        # 周六 → 下周一
        sat = datetime(2025, 5, 31, 10, 0)  # 周六
        result = _next_work_time(sat, config)
        assert result.weekday() == 0  # 周一
        assert result.hour == 9

    def test_next_work_time_after_hours(self, config: SchedulerConfig) -> None:
        # 工作日 19:00 → 下个工作日 09:00
        mon_evening = datetime(2025, 6, 2, 19, 0)  # 周一 19:00
        result = _next_work_time(mon_evening, config)
        assert result.hour == 9
        assert result.day == 3  # 周二

    def test_next_work_time_before_hours(self, config: SchedulerConfig) -> None:
        # 工作日 07:00 → 当天 09:00
        mon_early = datetime(2025, 6, 2, 7, 0)
        result = _next_work_time(mon_early, config)
        assert result.hour == 9
        assert result.day == 2

    def test_compute_free_slots_empty(self, config: SchedulerConfig) -> None:
        ds = datetime(2025, 6, 2, 9, 0)
        de = datetime(2025, 6, 2, 18, 0)
        slots = _compute_free_slots(ds, de, [], config)
        assert len(slots) == 1
        assert slots[0].duration_minutes == 540

    def test_compute_free_slots_with_events(self, config: SchedulerConfig) -> None:
        ds = datetime(2025, 6, 2, 9, 0)
        de = datetime(2025, 6, 2, 18, 0)
        events = [CalendarEvent(subject="会议", start="2025-06-02 10:00", end="2025-06-02 11:00", busy_status="busy")]
        slots = _compute_free_slots(ds, de, events, config)
        assert len(slots) == 2
        assert slots[0].start == "2025-06-02 09:00"
        assert slots[0].duration_minutes == 60
        assert slots[1].start == "2025-06-02 11:00"
        assert slots[1].duration_minutes == 420

    def test_compute_free_slots_free_event_ignored(self, config: SchedulerConfig) -> None:
        ds = datetime(2025, 6, 2, 9, 0)
        de = datetime(2025, 6, 2, 18, 0)
        events = [CalendarEvent(subject="空闲事件", start="2025-06-02 10:00", end="2025-06-02 11:00", busy_status="free")]
        slots = _compute_free_slots(ds, de, events, config)
        assert len(slots) == 1  # free 事件不阻塞

    def test_sort_tasks_priority(self) -> None:
        tasks = [
            ScheduleTask(name="低", duration_minutes=30, priority=Priority.LOW),
            ScheduleTask(name="急", duration_minutes=30, priority=Priority.URGENT),
            ScheduleTask(name="普", duration_minutes=30, priority=Priority.NORMAL),
        ]
        sorted_t = _sort_tasks(tasks)
        assert sorted_t[0].name == "急"
        assert sorted_t[1].name == "普"
        assert sorted_t[2].name == "低"

    def test_sort_tasks_deadline(self) -> None:
        tasks = [
            ScheduleTask(name="后", duration_minutes=30, deadline="2025-06-10"),
            ScheduleTask(name="前", duration_minutes=30, deadline="2025-06-02"),
        ]
        sorted_t = _sort_tasks(tasks)
        assert sorted_t[0].name == "前"


# ======================================================================
# 数据模型测试
# ======================================================================


class TestModels:
    """数据模型测试。"""

    def test_priority_from_str(self) -> None:
        assert Priority.from_str("high") == Priority.HIGH
        assert Priority.from_str("urgent") == Priority.URGENT
        assert Priority.from_str("LOW") == Priority.LOW
        assert Priority.from_str("unknown") == Priority.NORMAL  # 默认

    def test_schedule_task_validation(self) -> None:
        with pytest.raises(ValueError, match="正数"):
            ScheduleTask(name="x", duration_minutes=0)
        with pytest.raises(ValueError, match="不能为空"):
            ScheduleTask(name="  ", duration_minutes=30)

    def test_calendar_event_blocking(self) -> None:
        assert CalendarEvent(busy_status="busy").is_blocking is True
        assert CalendarEvent(busy_status="tentative").is_blocking is True
        assert CalendarEvent(busy_status="free").is_blocking is False

    def test_time_slot_auto_duration(self) -> None:
        slot = CalendarEvent.__class__.__mro__  # skip, just test TimeSlot
        from src.tools.schedule_models import TimeSlot
        ts = TimeSlot(start="2025-06-02 09:00", end="2025-06-02 10:30")
        assert ts.duration_minutes == 90


# ======================================================================
# schedule_task 测试
# ======================================================================


class TestScheduleTask:
    """单任务安排测试。"""

    @pytest.mark.asyncio
    async def test_schedule_task_no_calendar(self, scheduler: SmartScheduler) -> None:
        """无日历后端时，应在工作时间找到空槽。"""
        result = await scheduler.execute("schedule_task", {
            "task_name": "写代码", "duration_minutes": 60,
            "preferred_start": "2025-06-02 09:00",  # 周一
        })
        assert result["status"] == "success"
        assert result["task_name"] == "写代码"
        assert "2025-06-02 09:00" == result["scheduled_start"]
        assert "2025-06-02 10:00" == result["scheduled_end"]

    @pytest.mark.asyncio
    async def test_schedule_task_with_busy_calendar(self) -> None:
        """有日程时，应跳到下一个空闲时段。"""
        mock_cal = AsyncMock()
        mock_cal.execute.return_value = {
            "events": [
                {"subject": "会议A", "start": "2025-06-02 09:00", "end": "2025-06-02 11:00", "busy_status": "busy"},
            ]
        }
        s = SmartScheduler(calendar_ops=mock_cal)
        result = await s.execute("schedule_task", {
            "task_name": "写周报", "duration_minutes": 60,
            "preferred_start": "2025-06-02 09:00",
        })
        assert result["status"] == "success"
        assert result["scheduled_start"] == "2025-06-02 11:00"
        assert result["scheduled_end"] == "2025-06-02 12:00"

    @pytest.mark.asyncio
    async def test_schedule_task_missing_name(self, scheduler: SmartScheduler) -> None:
        result = await scheduler.execute("schedule_task", {"duration_minutes": 60})
        assert "error" in result
        assert "task_name" in result["error"]

    @pytest.mark.asyncio
    async def test_schedule_task_missing_duration(self, scheduler: SmartScheduler) -> None:
        result = await scheduler.execute("schedule_task", {"task_name": "测试"})
        assert "error" in result
        assert "duration_minutes" in result["error"]

    @pytest.mark.asyncio
    async def test_schedule_task_invalid_duration(self, scheduler: SmartScheduler) -> None:
        result = await scheduler.execute("schedule_task", {"task_name": "测试", "duration_minutes": "abc"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_schedule_task_no_slot_found(self, scheduler: SmartScheduler) -> None:
        """搜索范围太小，找不到时段。"""
        result = await scheduler.execute("schedule_task", {
            "task_name": "大项目", "duration_minutes": 600,
            "preferred_start": "2025-06-02 17:00",
            "deadline": "2025-06-02 18:00",
        })
        assert result["status"] == "no_slot_found"


# ======================================================================
# detect_conflicts 测试
# ======================================================================


class TestDetectConflicts:
    """冲突检测测试。"""

    @pytest.mark.asyncio
    async def test_no_conflicts(self) -> None:
        """无冲突场景。"""
        mock_cal = AsyncMock()
        mock_cal.execute.return_value = {
            "events": [
                {"subject": "会议A", "start": "2025-06-02 09:00", "end": "2025-06-02 10:00", "busy_status": "busy"},
            ]
        }
        s = SmartScheduler(calendar_ops=mock_cal)
        result = await s.execute("detect_conflicts", {
            "new_events": [
                {"name": "编码", "start": "2025-06-02 10:00", "end": "2025-06-02 11:00"},
            ]
        })
        assert result["conflict_count"] == 0
        assert "编码" in result["no_conflict_events"]

    @pytest.mark.asyncio
    async def test_has_conflict(self) -> None:
        """有冲突场景。"""
        mock_cal = AsyncMock()
        mock_cal.execute.return_value = {
            "events": [
                {"subject": "会议A", "start": "2025-06-02 09:00", "end": "2025-06-02 11:00", "busy_status": "busy"},
            ]
        }
        s = SmartScheduler(calendar_ops=mock_cal)
        result = await s.execute("detect_conflicts", {
            "new_events": [
                {"name": "冲突事件", "start": "2025-06-02 10:00", "end": "2025-06-02 12:00"},
            ]
        })
        assert result["conflict_count"] == 1
        assert result["conflicts"][0]["existing_event"] == "会议A"

    @pytest.mark.asyncio
    async def test_invalid_time(self, scheduler: SmartScheduler) -> None:
        """一个无效时间 + 一个有效时间：无效的应出现在冲突列表。"""
        result = await scheduler.execute("detect_conflicts", {
            "new_events": [
                {"name": "错误", "start": "bad", "end": "2025-06-02 11:00"},
                {"name": "正常", "start": "2025-06-02 09:00", "end": "2025-06-02 10:00"},
            ]
        })
        assert result["conflict_count"] == 1
        assert "解析失败" in result["conflicts"][0]["existing_event"]

    @pytest.mark.asyncio
    async def test_end_before_start(self, scheduler: SmartScheduler) -> None:
        result = await scheduler.execute("detect_conflicts", {
            "new_events": [{"name": "反转", "start": "2025-06-02 11:00", "end": "2025-06-02 10:00"}]
        })
        assert result["conflict_count"] == 1

    @pytest.mark.asyncio
    async def test_free_event_no_conflict(self) -> None:
        """free 状态的事件不算冲突。"""
        mock_cal = AsyncMock()
        mock_cal.execute.return_value = {
            "events": [
                {"subject": "空闲", "start": "2025-06-02 09:00", "end": "2025-06-02 11:00", "busy_status": "free"},
            ]
        }
        s = SmartScheduler(calendar_ops=mock_cal)
        result = await s.execute("detect_conflicts", {
            "new_events": [
                {"name": "新事件", "start": "2025-06-02 09:30", "end": "2025-06-02 10:30"},
            ]
        })
        assert result["conflict_count"] == 0

    @pytest.mark.asyncio
    async def test_empty_events(self, scheduler: SmartScheduler) -> None:
        result = await scheduler.execute("detect_conflicts", {"new_events": []})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_param(self, scheduler: SmartScheduler) -> None:
        result = await scheduler.execute("detect_conflicts", {})
        assert "error" in result


# ======================================================================
# optimize_schedule 测试
# ======================================================================


class TestOptimizeSchedule:
    """批量优化测试。"""

    @pytest.mark.asyncio
    async def test_sort_and_schedule(self, scheduler: SmartScheduler) -> None:
        """按优先级排序并安排。"""
        result = await scheduler.execute("optimize_schedule", {
            "tasks": [
                {"task_name": "低优先级", "duration_minutes": 60, "priority": "low"},
                {"task_name": "高优先级", "duration_minutes": 60, "priority": "high"},
                {"task_name": "普通", "duration_minutes": 60, "priority": "normal"},
            ]
        })
        assert result["status"] == "success"
        assert result["scheduled_count"] == 3
        # 高优先级应排在第一
        items = result["scheduled_items"]
        assert items[0]["task_name"] == "高优先级"

    @pytest.mark.asyncio
    async def test_empty_tasks(self, scheduler: SmartScheduler) -> None:
        result = await scheduler.execute("optimize_schedule", {"tasks": []})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_param(self, scheduler: SmartScheduler) -> None:
        result = await scheduler.execute("optimize_schedule", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_with_deadlines(self, scheduler: SmartScheduler) -> None:
        """有截止时间的任务排序。"""
        result = await scheduler.execute("optimize_schedule", {
            "tasks": [
                {"task_name": "远期", "duration_minutes": 60, "priority": "normal", "deadline": "2027-12-31"},
                {"task_name": "紧急", "duration_minutes": 60, "priority": "normal", "deadline": "2027-06-03"},
            ]
        })
        assert result["scheduled_count"] == 2
        items = result["scheduled_items"]
        assert items[0]["task_name"] == "紧急"

    @pytest.mark.asyncio
    async def test_all_same_day(self, scheduler: SmartScheduler) -> None:
        """所有任务都安排在同一天。"""
        tasks = [{"task_name": f"任务{i}", "duration_minutes": 60, "priority": "normal"} for i in range(5)]
        result = await scheduler.execute("optimize_schedule", {"tasks": tasks})
        assert result["scheduled_count"] == 5


# ======================================================================
# generate_daily_plan 测试
# ======================================================================


class TestGenerateDailyPlan:
    """每日计划测试。"""

    @pytest.mark.asyncio
    async def test_empty_day(self, scheduler: SmartScheduler) -> None:
        """空的一天。"""
        result = await scheduler.execute("generate_daily_plan", {
            "date": "2025-06-02",
        })
        assert result["status"] == "success"
        assert result["date"] == "2025-06-02"
        assert len(result["existing_events"]) == 0
        assert len(result["free_slots"]) == 1  # 整天一个空闲段
        assert result["free_slots"][0]["duration_minutes"] == 540  # 9:00-18:00

    @pytest.mark.asyncio
    async def test_with_pending_tasks(self, scheduler: SmartScheduler) -> None:
        """有待办任务。"""
        result = await scheduler.execute("generate_daily_plan", {
            "date": "2025-06-02",
            "pending_tasks": [
                {"task_name": "写代码", "duration_minutes": 120, "priority": "high"},
                {"task_name": "开会", "duration_minutes": 60, "priority": "normal"},
            ]
        })
        assert result["status"] == "success"
        assert len(result["scheduled_items"]) == 2
        # 第一个应安排在 09:00
        assert result["scheduled_items"][0]["start"] == "2025-06-02 09:00"
        assert result["scheduled_items"][0]["end"] == "2025-06-02 11:00"

    @pytest.mark.asyncio
    async def test_with_existing_events(self) -> None:
        """有已有日程。"""
        mock_cal = AsyncMock()
        mock_cal.execute.return_value = {
            "events": [
                {"subject": "晨会", "start": "2025-06-02 09:00", "end": "2025-06-02 09:30", "busy_status": "busy"},
            ]
        }
        s = SmartScheduler(calendar_ops=mock_cal)
        result = await s.execute("generate_daily_plan", {
            "date": "2025-06-02",
            "pending_tasks": [
                {"task_name": "编码", "duration_minutes": 60},
            ]
        })
        assert result["status"] == "success"
        assert len(result["existing_events"]) == 1
        # 待办应从 09:30 开始（晨会后）
        assert result["scheduled_items"][0]["start"] == "2025-06-02 09:30"

    @pytest.mark.asyncio
    async def test_invalid_date(self, scheduler: SmartScheduler) -> None:
        result = await scheduler.execute("generate_daily_plan", {"date": "bad-date"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_default_today(self, scheduler: SmartScheduler) -> None:
        """不传 date 时默认今天。"""
        result = await scheduler.execute("generate_daily_plan", {})
        assert result["status"] == "success"
        assert result["date"] == datetime.now().strftime("%Y-%m-%d")


# ======================================================================
# execute 统一入口
# ======================================================================


class TestExecute:
    """统一入口测试。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, scheduler: SmartScheduler) -> None:
        result = await scheduler.execute("unknown_action", {})
        assert "error" in result
        assert "available_actions" in result
        expected = sorted(["schedule_task", "optimize_schedule", "detect_conflicts", "generate_daily_plan"])
        assert sorted(result["available_actions"]) == expected


# ======================================================================
# 注册表
# ======================================================================


class TestRegistry:
    """验证 SmartScheduler 在 TOOL_REGISTRY 中注册。"""

    def test_registered(self) -> None:
        from src.tools import TOOL_REGISTRY
        assert "smart_scheduler" in TOOL_REGISTRY
        assert TOOL_REGISTRY["smart_scheduler"] is SmartScheduler

    def test_metadata(self) -> None:
        from src.tools import TOOL_METADATA
        assert "smart_scheduler" in TOOL_METADATA
        assert "智能调度" in TOOL_METADATA["smart_scheduler"].description
