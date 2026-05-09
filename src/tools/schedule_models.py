"""SmartScheduler 数据模型。

定义智能调度器使用的所有数据结构，包括任务、日程事件、
时间槽和调度结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# 优先级
# ---------------------------------------------------------------------------

class Priority(IntEnum):
    """任务优先级，数值越高越紧急。"""

    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4

    @classmethod
    def from_str(cls, value: str) -> Priority:
        """从字符串解析优先级。"""
        mapping: dict[str, Priority] = {
            "low": cls.LOW,
            "normal": cls.NORMAL,
            "medium": cls.NORMAL,
            "high": cls.HIGH,
            "urgent": cls.URGENT,
            "critical": cls.URGENT,
        }
        return mapping.get(value.lower(), cls.NORMAL)


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class ScheduleTask:
    """待安排的任务。"""

    name: str
    duration_minutes: int
    priority: Priority = Priority.NORMAL
    deadline: str | None = None          # ISO 格式或 "YYYY-MM-DD HH:MM"
    description: str = ""
    preferred_start: str | None = None   # 希望在什么时间开始
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.duration_minutes <= 0:
            raise ValueError(f"任务时长必须为正数: {self.duration_minutes}")
        if not self.name.strip():
            raise ValueError("任务名称不能为空")


@dataclass
class CalendarEvent:
    """日历上的已有事件。"""

    event_id: str = ""
    subject: str = ""
    start: str = ""   # "YYYY-MM-DD HH:MM"
    end: str = ""      # "YYYY-MM-DD HH:MM"
    location: str = ""
    busy_status: str = "busy"

    @property
    def is_blocking(self) -> bool:
        """是否占据时间（tentative 也视为忙碌）。"""
        return self.busy_status in ("busy", "tentative", "out_of_office")


@dataclass
class TimeSlot:
    """一段空闲时间。"""

    start: str  # "YYYY-MM-DD HH:MM"
    end: str    # "YYYY-MM-DD HH:MM"
    duration_minutes: int = 0

    def __post_init__(self) -> None:
        if self.duration_minutes <= 0:
            # 自动计算
            from datetime import datetime
            s = datetime.strptime(self.start, "%Y-%m-%d %H:%M")
            e = datetime.strptime(self.end, "%Y-%m-%d %H:%M")
            self.duration_minutes = int((e - s).total_seconds() / 60)


@dataclass
class ScheduledItem:
    """已安排到时间槽的任务。"""

    task_name: str
    start: str  # "YYYY-MM-DD HH:MM"
    end: str    # "YYYY-MM-DD HH:MM"
    priority: Priority = Priority.NORMAL
    status: str = "scheduled"  # scheduled / conflict / deferred
    conflict_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "task_name": self.task_name,
            "start": self.start,
            "end": self.end,
            "priority": self.priority.name.lower(),
            "status": self.status,
            "conflict_reason": self.conflict_reason,
        }


@dataclass
class ConflictInfo:
    """冲突信息。"""

    new_event: str       # 新事件标识
    existing_event: str  # 已有事件标识
    overlap_start: str = ""
    overlap_end: str = ""
    suggestion: str = ""  # 建议调整方案

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "new_event": self.new_event,
            "existing_event": self.existing_event,
            "overlap_start": self.overlap_start,
            "overlap_end": self.overlap_end,
            "suggestion": self.suggestion,
        }


@dataclass
class DailyPlan:
    """每日计划。"""

    date: str  # "YYYY-MM-DD"
    scheduled_items: list[ScheduledItem] = field(default_factory=list)
    existing_events: list[CalendarEvent] = field(default_factory=list)
    free_slots: list[TimeSlot] = field(default_factory=list)
    unscheduled_tasks: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "date": self.date,
            "scheduled_items": [item.to_dict() for item in self.scheduled_items],
            "existing_events": [
                {
                    "subject": e.subject,
                    "start": e.start,
                    "end": e.end,
                    "busy_status": e.busy_status,
                }
                for e in self.existing_events
            ],
            "free_slots": [
                {"start": s.start, "end": s.end, "duration_minutes": s.duration_minutes}
                for s in self.free_slots
            ],
            "unscheduled_tasks": self.unscheduled_tasks,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# 调度配置
# ---------------------------------------------------------------------------

@dataclass
class SchedulerConfig:
    """调度器配置。"""

    # 工作时间范围
    work_start_hour: int = 9
    work_end_hour: int = 18
    work_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon=0 .. Fri=4

    # 任务安排间隔（分钟）
    break_between_tasks: int = 15

    # 单个任务最小时长
    min_task_duration: int = 15

    # 每日最大安排时长（分钟）
    max_daily_schedule_minutes: int = 480  # 8 小时

    # 是否允许安排到非工作时间
    allow_overtime: bool = False

    # 默认查询天数（当没给 deadline 时向前看几天）
    default_lookahead_days: int = 7
