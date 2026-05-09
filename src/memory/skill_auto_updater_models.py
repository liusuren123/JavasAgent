"""技能自动优化器的数据结构定义。

包含 ToolUsageRecord 和 SkillUpdate 数据类。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ToolUsageRecord:
    """工具使用记录。

    跟踪单个工具的成功/失败次数、最后使用时间和平均执行耗时。
    """

    tool_name: str
    success_count: int = 0
    failure_count: int = 0
    last_used: float = 0.0  # Unix timestamp
    avg_execution_time: float = 0.0
    _total_time: float = 0.0  # 累计执行时间，用于计算均值
    _total_executions: int = 0  # 累计执行次数（含成功和失败）

    @property
    def total_count(self) -> int:
        """总执行次数。"""
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        """成功率。"""
        if self.total_count == 0:
            return 0.0
        return self.success_count / self.total_count

    def record_success(self, execution_time: float = 0.0) -> None:
        """记录一次成功执行。"""
        self.success_count += 1
        self.last_used = time.time()
        self._update_avg_time(execution_time)

    def record_failure(self, execution_time: float = 0.0) -> None:
        """记录一次失败执行。"""
        self.failure_count += 1
        self.last_used = time.time()
        self._update_avg_time(execution_time)

    def _update_avg_time(self, execution_time: float) -> None:
        """更新平均执行时间（增量均值）。"""
        if execution_time <= 0:
            return
        self._total_executions += 1
        self._total_time += execution_time
        self.avg_execution_time = self._total_time / self._total_executions

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "tool_name": self.tool_name,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_used": self.last_used,
            "avg_execution_time": self.avg_execution_time,
            "_total_time": self._total_time,
            "_total_executions": self._total_executions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolUsageRecord:
        """从字典还原 ToolUsageRecord。"""
        return cls(
            tool_name=data["tool_name"],
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            last_used=data.get("last_used", 0.0),
            avg_execution_time=data.get("avg_execution_time", 0.0),
            _total_time=data.get("_total_time", 0.0),
            _total_executions=data.get("_total_executions", 0),
        )


@dataclass
class SkillUpdate:
    """技能更新记录。

    记录一个从 SkillSuggestion 自动注册到 SkillRegistry 的技能及其使用效果。
    """

    skill_id: str
    suggestion_id: str
    registered_at: float  # Unix timestamp
    usage_count: int = 0
    effectiveness_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillUpdate:
        """从字典还原 SkillUpdate。"""
        return cls(**data)
