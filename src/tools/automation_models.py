"""AutomationEngine 数据模型。

定义自动化引擎使用的所有数据结构，包括触发器类型、
动作类型、自动化规则、规则统计信息，以及 cron 匹配等工具函数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class TriggerType(str, Enum):
    """触发器类型。"""

    FILE_CHANGE = "file_change"
    SCHEDULE = "schedule"
    SYSTEM_EVENT = "system_event"
    PROCESS_EVENT = "process_event"


class ActionType(str, Enum):
    """动作类型。"""

    RUN_TOOL = "run_tool"
    NOTIFY = "notify"
    LOG = "log"


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class AutomationRule:
    """自动化规则。

    Attributes:
        rule_id: 唯一标识
        name: 规则名称
        trigger_type: 触发器类型
        trigger_config: 触发器配置
        action_type: 动作类型
        action_config: 动作配置
        enabled: 是否启用
        last_triggered: 最后触发时间
    """

    rule_id: str
    name: str
    trigger_type: str
    trigger_config: dict[str, Any] = field(default_factory=dict)
    action_type: str = "log"
    action_config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_triggered: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "trigger_type": self.trigger_type,
            "trigger_config": self.trigger_config,
            "action_type": self.action_type,
            "action_config": self.action_config,
            "enabled": self.enabled,
            "last_triggered": self.last_triggered.isoformat() if self.last_triggered else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AutomationRule:
        """从字典创建实例。"""
        last_triggered = data.get("last_triggered")
        if isinstance(last_triggered, str):
            last_triggered = datetime.fromisoformat(last_triggered)
        return cls(
            rule_id=data["rule_id"],
            name=data["name"],
            trigger_type=data["trigger_type"],
            trigger_config=data.get("trigger_config", {}),
            action_type=data.get("action_type", "log"),
            action_config=data.get("action_config", {}),
            enabled=data.get("enabled", True),
            last_triggered=last_triggered,
        )


@dataclass
class RuleStats:
    """规则运行统计。"""

    rule_id: str
    trigger_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_trigger_time: datetime | None = None
    last_success_time: datetime | None = None
    last_failure_time: datetime | None = None
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "rule_id": self.rule_id,
            "trigger_count": self.trigger_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_trigger_time": self.last_trigger_time.isoformat() if self.last_trigger_time else None,
            "last_success_time": self.last_success_time.isoformat() if self.last_success_time else None,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_error": self.last_error,
        }

    def record_trigger(self) -> None:
        """记录一次触发。"""
        self.trigger_count += 1
        self.last_trigger_time = datetime.now()

    def record_success(self) -> None:
        """记录一次成功。"""
        self.success_count += 1
        self.last_success_time = datetime.now()
        self.last_error = ""

    def record_failure(self, error: str = "") -> None:
        """记录一次失败。"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        self.last_error = error


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def compare_values(current: float, threshold: float, op: str) -> bool:
    """比较当前值与阈值。"""
    ops = {
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        "==": lambda a, b: a == b,
    }
    return ops.get(op, lambda a, b: False)(current, threshold)


def match_cron(cron_expr: str) -> bool:
    """匹配简化的 cron 表达式。

    格式: "分 时 日 月 周"，每个字段支持 * / 具体值 / 逗号分隔 / 范围。
    """
    now = datetime.now()
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False

    checks = [
        (fields[0], now.minute),
        (fields[1], now.hour),
        (fields[2], now.day),
        (fields[3], now.month),
        (fields[4], now.weekday()),
    ]
    return all(_cron_field_match(f, v) for f, v in checks)


def _cron_field_match(field: str, value: int) -> bool:
    """检查 cron 字段是否匹配给定值。"""
    if field == "*":
        return True
    for part in field.split(","):
        if "-" in part:
            try:
                s, e = part.split("-", 1)
                if int(s) <= value <= int(e):
                    return True
            except ValueError:
                continue
        elif "/" in part:
            try:
                base, step = part.split("/", 1)
                step = int(step)
                base_val = 0 if base == "*" else int(base)
                if base_val <= value and (value - base_val) % step == 0:
                    return True
            except ValueError:
                continue
        else:
            try:
                if int(part) == value:
                    return True
            except ValueError:
                continue
    return False
