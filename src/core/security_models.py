"""安全管理模块数据模型。

定义权限、风险等级、操作、审批请求、安全策略、审计日志等核心数据结构。
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Permission(str, Enum):
    """操作权限类型。"""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DELETE = "delete"
    SYSTEM = "system"


class RiskLevel(str, Enum):
    """风险等级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(str, Enum):
    """审批状态。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TrustMode(str, Enum):
    """信任模式。"""

    AUTO = "auto"        # 全自动：所有操作自动批准
    NORMAL = "normal"    # 正常模式：按策略决定
    STRICT = "strict"    # 严格模式：所有操作需确认


@dataclass
class Operation:
    """操作描述。

    描述一个待执行的操作，包含类型、目标、所需权限等信息。
    """

    operation_type: str          # 操作类型：file_delete, process_kill, registry_modify 等
    target: str                  # 操作目标：文件路径、进程名、注册表键等
    required_permission: Permission = Permission.READ
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    risk_level: RiskLevel = RiskLevel.LOW  # 可被 SecurityManager 覆盖

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        data = asdict(self)
        data["required_permission"] = self.required_permission.value
        data["risk_level"] = self.risk_level.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Operation:
        """从字典还原 Operation。"""
        data = dict(data)
        if isinstance(data.get("required_permission"), str):
            data["required_permission"] = Permission(data["required_permission"])
        if isinstance(data.get("risk_level"), str):
            data["risk_level"] = RiskLevel(data["risk_level"])
        return cls(**data)


@dataclass
class ApprovalRequest:
    """审批请求。

    高危操作需要人工审批时创建的请求对象。
    """

    id: str
    operation: Operation
    risk_level: RiskLevel
    risk_reason: str                    # 风险说明
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None  # 超时时间，None 表示不超时
    resolved_at: datetime | None = None
    resolved_by: str = ""               # 审批人
    reason: str = ""                     # 审批/拒绝原因

    @property
    def is_expired(self) -> bool:
        """是否已超时。"""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at and self.status == ApprovalStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        data = asdict(self)
        data["operation"] = self.operation.to_dict()
        data["risk_level"] = self.risk_level.value
        data["status"] = self.status.value
        data["created_at"] = self.created_at.isoformat()
        data["expires_at"] = self.expires_at.isoformat() if self.expires_at else None
        data["resolved_at"] = self.resolved_at.isoformat() if self.resolved_at else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRequest:
        """从字典还原 ApprovalRequest。"""
        data = dict(data)
        if isinstance(data.get("operation"), dict):
            data["operation"] = Operation.from_dict(data["operation"])
        if isinstance(data.get("risk_level"), str):
            data["risk_level"] = RiskLevel(data["risk_level"])
        if isinstance(data.get("status"), str):
            data["status"] = ApprovalStatus(data["status"])
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("expires_at"), str):
            data["expires_at"] = datetime.fromisoformat(data["expires_at"])
        if isinstance(data.get("resolved_at"), str):
            data["resolved_at"] = datetime.fromisoformat(data["resolved_at"])
        return cls(**data)

    @classmethod
    def create(
        cls,
        operation: Operation,
        risk_level: RiskLevel,
        risk_reason: str,
        timeout_seconds: int = 300,
    ) -> ApprovalRequest:
        """工厂方法：创建审批请求。"""
        now = datetime.now()
        expires_at = now + __import__("datetime").timedelta(seconds=timeout_seconds) if timeout_seconds > 0 else None
        return cls(
            id=f"apr_{uuid.uuid4().hex[:12]}",
            operation=operation,
            risk_level=risk_level,
            risk_reason=risk_reason,
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=expires_at,
        )


@dataclass
class SecurityPolicy:
    """安全策略。

    定义各风险等级对应的处理策略（自动批准/需审批/禁止）。
    """

    name: str
    description: str = ""

    # 各风险等级的处理方式: "auto" | "approve" | "deny"
    low_action: str = "auto"
    medium_action: str = "approve"
    high_action: str = "approve"
    critical_action: str = "deny"

    # 审批超时时间（秒）
    approval_timeout: int = 300

    # 操作类型白名单（这些操作类型自动批准）
    auto_approved_types: list[str] = field(default_factory=list)

    # 目标路径/进程黑名单（这些操作总是拒绝）
    denied_targets: list[str] = field(default_factory=list)

    # 自定义风险规则（匹配模式 -> 风险等级覆盖）
    risk_overrides: dict[str, str] = field(default_factory=dict)

    # 优先级（数值越大越优先）
    priority: int = 0

    def get_action(self, risk_level: RiskLevel) -> str:
        """根据风险等级获取处理动作。"""
        mapping = {
            RiskLevel.LOW: self.low_action,
            RiskLevel.MEDIUM: self.medium_action,
            RiskLevel.HIGH: self.high_action,
            RiskLevel.CRITICAL: self.critical_action,
        }
        return mapping.get(risk_level, "approve")

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecurityPolicy:
        """从字典还原 SecurityPolicy。"""
        return cls(**data)


@dataclass
class AuditLogEntry:
    """审计日志条目。

    记录每一次敏感操作的详细信息。
    """

    id: str
    timestamp: datetime
    operation_type: str
    target: str
    required_permission: str
    risk_level: str
    result: str              # "success" | "denied" | "error"
    user_approved: bool | None  # None 表示自动处理
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditLogEntry:
        """从字典还原 AuditLogEntry。"""
        data = dict(data)
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)

    @classmethod
    def create(
        cls,
        operation: Operation,
        result: str,
        user_approved: bool | None = None,
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> AuditLogEntry:
        """工厂方法：创建审计日志条目。"""
        return cls(
            id=f"aud_{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(),
            operation_type=operation.operation_type,
            target=operation.target,
            required_permission=operation.required_permission.value,
            risk_level=operation.risk_level.value,
            result=result,
            user_approved=user_approved,
            reason=reason,
            details=details or {},
        )
