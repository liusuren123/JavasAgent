"""数据模型定义。

所有核心数据结构集中定义，保持模块间解耦。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PlanStatus(str, Enum):
    """任务计划状态。"""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"


class StepStatus(str, Enum):
    """步骤状态。"""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class Priority(int, Enum):
    """任务优先级。"""

    LOW = 0
    NORMAL = 5
    HIGH = 10
    URGENT = 20


@dataclass
class Step:
    """单个执行步骤。"""

    id: str
    action: str
    tool: str
    params: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    status: StepStatus = StepStatus.PENDING
    result: str | None = None
    error: str | None = None

    @property
    def can_retry(self) -> bool:
        """是否可以重试。"""
        return self.retry_count < self.max_retries


@dataclass
class TaskPlan:
    """任务计划。"""

    id: str
    intent: str
    steps: list[Step] = field(default_factory=list)
    priority: Priority = Priority.NORMAL
    created_at: datetime = field(default_factory=datetime.now)
    status: PlanStatus = PlanStatus.PENDING
    parent_id: str | None = None

    @property
    def progress(self) -> float:
        """完成进度（0-1）。"""
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps if s.status == StepStatus.DONE)
        return done / len(self.steps)

    @property
    def current_step(self) -> Step | None:
        """当前待执行的步骤。"""
        for step in self.steps:
            if step.status in (StepStatus.PENDING, StepStatus.RUNNING):
                # 检查依赖是否都已完成
                deps_done = all(
                    self._get_step(dep_id).status == StepStatus.DONE
                    for dep_id in step.depends_on
                    if self._get_step(dep_id) is not None
                )
                if deps_done:
                    return step
        return None

    def _get_step(self, step_id: str) -> Step | None:
        """根据 ID 获取步骤。"""
        for s in self.steps:
            if s.id == step_id:
                return s
        return None


@dataclass
class ActionItem:
    """反思审查的行动项。"""

    category: str
    description: str
    severity: str  # "low" | "medium" | "high"
    suggestion: str


@dataclass
class ReflectionReport:
    """反思审查报告。"""

    timestamp: datetime = field(default_factory=datetime.now)
    checklist_results: dict[str, str] = field(default_factory=dict)
    overall_score: float = 0.0
    action_items: list[ActionItem] = field(default_factory=list)
    should_continue: bool = True
    summary: str = ""


@dataclass
class DecisionPoint:
    """决策点。"""

    context: str
    question: str
    confidence: float  # 0-1，越高越确定
    options: list[str] = field(default_factory=list)
    auto_decided: bool = False
