"""技能注册表与学习器的数据模型定义。

包含 SkillDefinition、LearnedPattern、SkillSuggestion 等核心数据结构。
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SkillDefinition:
    """技能定义。

    描述一个已注册的工具/技能，包含名称、描述、参数模式、使用示例等元信息。
    """

    id: str
    name: str
    description: str
    category: str  # "tool" | "workflow" | "learned" | "builtin"
    parameters: dict[str, Any] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    source: str = "manual"  # "manual" | "auto_learned" | "tool_registry"
    pattern_steps: list[str] = field(default_factory=list)  # 学习到的步骤序列
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillDefinition:
        """从字典还原 SkillDefinition。"""
        data = dict(data)
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        category: str = "tool",
        **kwargs: Any,
    ) -> SkillDefinition:
        """工厂方法：创建新技能定义并自动生成 ID。"""
        now = datetime.now()
        return cls(
            id=f"skill_{uuid.uuid4().hex[:12]}",
            name=name,
            description=description,
            category=category,
            created_at=now,
            updated_at=now,
            **kwargs,
        )


@dataclass
class LearnedPattern:
    """学习到的任务模式。

    记录一个被观察到的任务执行模式，包含步骤序列和出现频次。
    """

    id: str
    pattern_key: str  # 模式的唯一标识（由步骤序列生成）
    steps: list[str]  # 步骤描述列表
    tools_used: list[str]  # 使用的工具列表
    success_count: int = 0
    failure_count: int = 0
    last_seen_at: datetime = field(default_factory=datetime.now)
    first_seen_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

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

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        data = asdict(self)
        data["last_seen_at"] = self.last_seen_at.isoformat()
        data["first_seen_at"] = self.first_seen_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearnedPattern:
        """从字典还原 LearnedPattern。"""
        data = dict(data)
        if isinstance(data.get("last_seen_at"), str):
            data["last_seen_at"] = datetime.fromisoformat(data["last_seen_at"])
        if isinstance(data.get("first_seen_at"), str):
            data["first_seen_at"] = datetime.fromisoformat(data["first_seen_at"])
        return cls(**data)


@dataclass
class SkillSuggestion:
    """技能注册建议。

    当学习器检测到可复用模式时生成的注册建议。
    """

    id: str
    pattern: LearnedPattern
    suggested_name: str
    suggested_description: str
    suggested_category: str = "learned"
    status: str = "pending"  # "pending" | "approved" | "rejected"
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "id": self.id,
            "pattern": self.pattern.to_dict(),
            "suggested_name": self.suggested_name,
            "suggested_description": self.suggested_description,
            "suggested_category": self.suggested_category,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillSuggestion:
        """从字典还原 SkillSuggestion。"""
        data = dict(data)
        if isinstance(data.get("pattern"), dict):
            data["pattern"] = LearnedPattern.from_dict(data["pattern"])
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)
