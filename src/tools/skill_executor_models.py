"""技能执行引擎的数据模型定义。

包含 SkillMatch、ExecutionRecord、SkillChainStep 等核心数据结构。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SkillMatch:
    """技能匹配结果。

    描述一个技能与任务描述的匹配程度。
    """

    skill_name: str
    relevance_score: float  # 0.0-1.0，1.0 表示完全匹配
    match_reason: str  # 匹配原因说明

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return asdict(self)


@dataclass
class ExecutionRecord:
    """执行记录。

    记录一次技能执行的完整信息，用于历史查询和学习反馈。
    """

    record_id: str
    skill_name: str
    params_summary: dict[str, Any]  # 参数摘要（可能被截断）
    result_summary: dict[str, Any]  # 结果摘要
    success: bool
    error: str  # 错误信息，无错误为空字符串
    duration_ms: int  # 执行耗时（毫秒）
    timestamp: str  # ISO 8601 格式

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return asdict(self)


@dataclass
class SkillChainStep:
    """技能链步骤。

    描述技能链中的一个步骤，包含技能名称、参数和依赖关系。
    """

    step_index: int  # 步骤序号（从 0 开始）
    skill_name: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[int] = field(default_factory=list)  # 依赖的步骤索引

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return asdict(self)


@dataclass
class SkillChainResult:
    """技能链执行结果。

    记录整个技能链的执行情况，包含每个步骤的结果。
    """

    chain_id: str
    steps: list[SkillChainStep]
    step_results: list[dict[str, Any]]  # 每个步骤的执行结果
    success: bool
    error: str
    total_duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "chain_id": self.chain_id,
            "steps": [s.to_dict() for s in self.steps],
            "step_results": self.step_results,
            "success": self.success,
            "error": self.error,
            "total_duration_ms": self.total_duration_ms,
        }
