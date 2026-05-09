"""安全模块数据模型序列化/反序列化测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.core.security_models import (
    ApprovalRequest,
    AuditLogEntry,
    Operation,
    Permission,
    RiskLevel,
    SecurityPolicy,
)


class TestOperationSerialization:
    """Operation 序列化测试。"""

    def test_round_trip(self) -> None:
        op = Operation(
            operation_type="file_delete",
            target="C:\\test.txt",
            required_permission=Permission.DELETE,
            risk_level=RiskLevel.HIGH,
        )
        data = op.to_dict()
        restored = Operation.from_dict(data)
        assert restored.operation_type == op.operation_type
        assert restored.target == op.target
        assert restored.required_permission == Permission.DELETE
        assert restored.risk_level == RiskLevel.HIGH


class TestApprovalRequestSerialization:
    """ApprovalRequest 序列化测试。"""

    def test_round_trip(self) -> None:
        op = Operation(
            operation_type="process_kill",
            target="notepad.exe",
            required_permission=Permission.SYSTEM,
        )
        req = ApprovalRequest.create(
            operation=op,
            risk_level=RiskLevel.CRITICAL,
            risk_reason="终止进程",
            timeout_seconds=60,
        )
        data = req.to_dict()
        restored = ApprovalRequest.from_dict(data)
        assert restored.id == req.id
        assert restored.operation.operation_type == "process_kill"
        assert restored.risk_level == RiskLevel.CRITICAL

    def test_expiry_property(self) -> None:
        """测试超时属性。"""
        req = ApprovalRequest.create(
            operation=Operation(operation_type="test", target="x", required_permission=Permission.READ),
            risk_level=RiskLevel.HIGH,
            risk_reason="test",
            timeout_seconds=1,
        )
        assert req.expires_at is not None
        req.expires_at = datetime.now() - timedelta(seconds=1)
        assert req.is_expired is True

    def test_no_expiry(self) -> None:
        """测试不超时。"""
        req = ApprovalRequest.create(
            operation=Operation(operation_type="test", target="x", required_permission=Permission.READ),
            risk_level=RiskLevel.LOW,
            risk_reason="test",
            timeout_seconds=-1,
        )
        assert req.expires_at is None
        assert req.is_expired is False


class TestAuditLogEntrySerialization:
    """AuditLogEntry 序列化测试。"""

    def test_round_trip(self) -> None:
        op = Operation(
            operation_type="file_read",
            target="test.txt",
            required_permission=Permission.READ,
        )
        entry = AuditLogEntry.create(op, result="success", user_approved=None)
        data = entry.to_dict()
        restored = AuditLogEntry.from_dict(data)
        assert restored.id == entry.id
        assert restored.operation_type == "file_read"
        assert restored.result == "success"


class TestSecurityPolicySerialization:
    """SecurityPolicy 序列化测试。"""

    def test_round_trip(self) -> None:
        policy = SecurityPolicy(
            name="test",
            description="测试",
            priority=10,
            auto_approved_types=["file_read"],
            denied_targets=["C:\\Windows\\**"],
            risk_overrides={"custom_op": "high"},
        )
        data = policy.to_dict()
        restored = SecurityPolicy.from_dict(data)
        assert restored.name == "test"
        assert restored.priority == 10
        assert "file_read" in restored.auto_approved_types
