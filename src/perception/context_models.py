"""ContextEngine 数据模型。

定义用户场景感知引擎的所有数据结构，包括场景类型枚举、
场景快照、建议操作等。
从 context_engine.py 拆分出来以控制文件大小。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SceneType(str, Enum):
    """场景类型枚举。"""

    CODING = "coding"
    BROWSING = "browsing"
    MEETING = "meeting"
    WRITING = "writing"
    GAMING = "gaming"
    MEDIA = "media"
    IDLE = "idle"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


@dataclass
class ContextSnapshot:
    """场景快照 — 捕获某一时刻的用户活动上下文。

    Attributes:
        timestamp: 快照时间戳（Unix 时间，秒）
        active_app: 当前活跃应用名称（进程名）
        active_window: 当前活跃窗口标题
        scene_type: 场景分类
        confidence: 置信度 0-1
        duration_seconds: 在当前场景的持续时间（秒）
        metadata: 额外信息字典
    """

    timestamp: float
    active_app: str
    active_window: str
    scene_type: SceneType
    confidence: float
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式，方便序列化。"""
        return {
            "timestamp": self.timestamp,
            "active_app": self.active_app,
            "active_window": self.active_window,
            "scene_type": str(self.scene_type),
            "confidence": self.confidence,
            "duration_seconds": self.duration_seconds,
            "metadata": self.metadata,
        }


@dataclass
class SuggestedAction:
    """建议操作。

    Attributes:
        action_type: 操作类型（如 "switch_app", "remind", "summarize" 等）
        title: 操作标题（简短描述）
        description: 操作详细描述
        priority: 优先级 0-1（1 为最高）
        metadata: 额外信息
    """

    action_type: str
    title: str
    description: str = ""
    priority: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TimeSlot:
    """时间段记录。

    Attributes:
        hour: 小时 (0-23)
        day_of_week: 星期几 (0=Monday, 6=Sunday)
        typical_scene: 该时段的典型场景
        app_frequency: 应用使用频率 {app_name: count}
    """

    hour: int
    day_of_week: int
    typical_scene: SceneType = SceneType.UNKNOWN
    app_frequency: dict[str, int] = field(default_factory=dict)


@dataclass
class ActivityInfo:
    """当前活动信息。

    由 ActivityDetector 产出的原始活动数据。

    Attributes:
        app_name: 应用程序名称
        window_title: 窗口标题
        pid: 进程 ID
        timestamp: 检测时间戳
    """

    app_name: str
    window_title: str
    pid: int = 0
    timestamp: float = 0.0
