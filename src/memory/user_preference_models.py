"""用户偏好学习引擎的数据结构定义。

包含 ToolUsageSnapshot、WorkHourPattern 和 PreferenceData 数据类。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class WorkHourPattern:
    """工作时间段模式。

    分别跟踪工作日和周末每个小时的活跃次数。
    """

    weekday_hours: dict[int, int] = field(default_factory=dict)  # hour -> count
    weekend_hours: dict[int, int] = field(default_factory=dict)  # hour -> count

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "weekday_hours": {str(k): v for k, v in self.weekday_hours.items()},
            "weekend_hours": {str(k): v for k, v in self.weekend_hours.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkHourPattern:
        """从字典还原 WorkHourPattern。"""
        return cls(
            weekday_hours={int(k): v for k, v in data.get("weekday_hours", {}).items()},
            weekend_hours={int(k): v for k, v in data.get("weekend_hours", {}).items()},
        )


@dataclass
class PreferenceData:
    """用户偏好数据的持久化容器。

    Attributes:
        tool_usage: 工具使用统计 tool -> {count, success_count, total_duration_ms}
        command_patterns: 命令模式 command_lower -> count
        feedback_history: 用户反馈历史（最近 100 条）
        work_hours: 活跃时间模式
        risk_events: 用户纠正 agent 的次数
        total_interactions: 总交互次数
        last_updated: 最后更新时间戳
    """

    tool_usage: dict[str, dict[str, Any]] = field(default_factory=dict)
    command_patterns: dict[str, int] = field(default_factory=dict)
    feedback_history: list[dict[str, Any]] = field(default_factory=list)
    work_hours: WorkHourPattern = field(default_factory=WorkHourPattern)
    risk_events: int = 0
    total_interactions: int = 0
    last_updated: float = 0.0

    # ── 常量 ──
    MAX_FEEDBACK_ENTRIES: int = field(default=100, repr=False, compare=False)

    def add_feedback(self, entry: dict[str, Any]) -> None:
        """添加一条反馈记录，超出上限时淘汰最旧的。"""
        self.feedback_history.append(entry)
        if len(self.feedback_history) > self.MAX_FEEDBACK_ENTRIES:
            self.feedback_history = self.feedback_history[-self.MAX_FEEDBACK_ENTRIES :]

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "tool_usage": self.tool_usage,
            "command_patterns": self.command_patterns,
            "feedback_history": self.feedback_history,
            "work_hours": self.work_hours.to_dict(),
            "risk_events": self.risk_events,
            "total_interactions": self.total_interactions,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PreferenceData:
        """从字典还原 PreferenceData。"""
        work_hours_raw = data.get("work_hours", {})
        if isinstance(work_hours_raw, WorkHourPattern):
            work_hours = work_hours_raw
        elif isinstance(work_hours_raw, dict):
            work_hours = WorkHourPattern.from_dict(work_hours_raw)
        else:
            work_hours = WorkHourPattern()

        return cls(
            tool_usage=data.get("tool_usage", {}),
            command_patterns=data.get("command_patterns", {}),
            feedback_history=data.get("feedback_history", []),
            work_hours=work_hours,
            risk_events=data.get("risk_events", 0),
            total_interactions=data.get("total_interactions", 0),
            last_updated=data.get("last_updated", 0.0),
        )
