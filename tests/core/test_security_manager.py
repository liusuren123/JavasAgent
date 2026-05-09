"""SecurityManager 安全管理模块测试。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core.security_manager import SecurityManager
from src.core.security_models import (
    ApprovalStatus,
    Operation,
    Permission,
    RiskLevel,
    SecurityPolicy,
    TrustMode,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_dir(tmp_path: Path) -> Path:
    """创建临时审计日志目录。"""
    d = tmp_path / "audit"
    d.mkdir()
    return d


@pytest.fixture
def manager(audit_dir: Path) -> SecurityManager:
    """创建默认配置的 SecurityManager。"""
    return SecurityManager({
        "trust_mode": "normal",
        "audit_log_dir": str(audit_dir),
        "approval_timeout": 300,
    })


@pytest.fixture
def auto_manager(audit_dir: Path) -> SecurityManager:
    """创建 AUTO 模式的 SecurityManager。"""
    return SecurityManager({
        "trust_mode": "auto",
        "audit_log_dir": str(audit_dir),
    })


@pytest.fixture
def strict_manager(audit_dir: Path) -> SecurityManager:
    """创建 STRICT 模式的 SecurityManager。"""
    return SecurityManager({
        "trust_mode": "strict",
        "audit_log_dir": str(audit_dir),
    })


@pytest.fixture
def file_delete_op() -> Operation:
    """文件删除操作。"""
    return Operation(
        operation_type="file_delete",
        target="C:\\Users\\test\\document.txt",
        required_permission=Permission.DELETE,
        description="删除测试文件",
    )


@pytest.fixture
def file_read_op() -> Operation:
    """文件读取操作。"""
    return Operation(
        operation_type="file_read",
        target="C:\\Users\\test\\readme.md",
        required_permission=Permission.READ,
        description="读取文件",
    )


@pytest.fixture
def process_kill_op() -> Operation:
    """进程终止操作。"""
    return Operation(
        operation_type="process_kill",
        target="notepad.exe",
        required_permission=Permission.SYSTEM,
        description="终止记事本进程",
    )


@pytest.fixture
def registry_op() -> Operation:
    """注册表修改操作。"""
    return Operation(
        operation_type="registry_modify",
        target="HKLM\\SOFTWARE\\Test",
        required_permission=Permission.SYSTEM,
        description="修改注册表",
    )


@pytest.fixture
def system_path_op() -> Operation:
    """系统路径操作。"""
    return Operation(
        operation_type="file_delete",
        target="C:\\Windows\\System32\\drivers\\test.sys",
        required_permission=Permission.SYSTEM,
        description="删除系统文件",
    )


# ---------------------------------------------------------------------------
# 风险等级评估
# ---------------------------------------------------------------------------


class TestRiskEvaluation:
    """风险等级评估测试。"""

    def test_file_delete_is_high(self, manager: SecurityManager, file_delete_op: Operation) -> None:
        risk = manager.evaluate_risk(file_delete_op)
        assert risk == RiskLevel.HIGH

    def test_file_read_is_low(self, manager: SecurityManager, file_read_op: Operation) -> None:
        risk = manager.evaluate_risk(file_read_op)
        assert risk == RiskLevel.LOW

    def test_process_kill_is_critical(self, manager: SecurityManager, process_kill_op: Operation) -> None:
        risk = manager.evaluate_risk(process_kill_op)
        assert risk == RiskLevel.CRITICAL

    def test_registry_modify_is_critical(self, manager: SecurityManager, registry_op: Operation) -> None:
        risk = manager.evaluate_risk(registry_op)
        assert risk == RiskLevel.CRITICAL

    def test_system_path_is_critical(self, manager: SecurityManager, system_path_op: Operation) -> None:
        risk = manager.evaluate_risk(system_path_op)
        assert risk == RiskLevel.CRITICAL

    def test_unknown_type_default_risk(self, manager: SecurityManager) -> None:
        """未知操作类型+无匹配规则时使用操作自带的风险等级。"""
        op = Operation(
            operation_type="custom_op",
            target="something",
            required_permission=Permission.EXECUTE,
            risk_level=RiskLevel.MEDIUM,
        )
        # EXECUTE 权限映射到 MEDIUM，与操作自带等级一致
        risk = manager.evaluate_risk(op)
        assert risk == RiskLevel.MEDIUM

    def test_shell_command_is_high(self, manager: SecurityManager) -> None:
        op = Operation(
            operation_type="shell_command",
            target="rm -rf /",
            required_permission=Permission.EXECUTE,
        )
        risk = manager.evaluate_risk(op)
        assert risk == RiskLevel.HIGH

    def test_risk_override_by_policy(self, manager: SecurityManager) -> None:
        """策略中的 risk_overrides 可以覆盖内置规则。"""
        policy = SecurityPolicy(
            name="test_override",
            priority=100,
            risk_overrides={"file_read": "critical"},
        )
        manager.register_policy(policy)

        op = Operation(
            operation_type="file_read",
            target="safe.txt",
            required_permission=Permission.READ,
        )
        risk = manager.evaluate_risk(op)
        assert risk == RiskLevel.CRITICAL


# ---------------------------------------------------------------------------
# 权限检查
# ---------------------------------------------------------------------------


class TestPermissionCheck:
    """权限检查测试。"""

    def test_auto_mode_allows_all(self, auto_manager: SecurityManager, process_kill_op: Operation) -> None:
        result = auto_manager.check_permission(process_kill_op)
        assert result is True

    def test_strict_mode_denies_all(self, strict_manager: SecurityManager, file_read_op: Operation) -> None:
        result = strict_manager.check_permission(file_read_op)
        assert result is False

    def test_normal_low_risk_allowed(self, manager: SecurityManager, file_read_op: Operation) -> None:
        result = manager.check_permission(file_read_op)
        assert result is True

    def test_normal_high_risk_needs_approval(self, manager: SecurityManager, file_delete_op: Operation) -> None:
        result = manager.check_permission(file_delete_op)
        assert result is False  # 需要审批

    def test_denied_target_rejected(self, manager: SecurityManager) -> None:
        """黑名单目标总是被拒绝。"""
        policy = SecurityPolicy(
            name="block_sensitive",
            priority=100,
            denied_targets=["C:\\Windows\\**"],
        )
        manager.register_policy(policy)

        op = Operation(
            operation_type="file_read",
            target="C:\\Windows\\explorer.exe",
            required_permission=Permission.READ,
        )
        assert manager.check_permission(op) is False

    def test_auto_approved_type(self, manager: SecurityManager) -> None:
        """白名单类型自动放行。"""
        policy = SecurityPolicy(
            name="safe_reads",
            priority=50,
            auto_approved_types=["file_read"],
        )
        manager.register_policy(policy)

        op = Operation(
            operation_type="file_read",
            target="any_file.txt",
            required_permission=Permission.READ,
        )
        assert manager.check_permission(op) is True


# ---------------------------------------------------------------------------
# 自动批准
# ---------------------------------------------------------------------------


class TestAutoApproval:
    """自动批准逻辑测试。"""

    def test_auto_mode_always_approved(self, auto_manager: SecurityManager, process_kill_op: Operation) -> None:
        assert auto_manager.is_auto_approved(process_kill_op) is True

    def test_strict_mode_never_approved(self, strict_manager: SecurityManager, file_read_op: Operation) -> None:
        assert strict_manager.is_auto_approved(file_read_op) is False

    def test_low_risk_auto_approved(self, manager: SecurityManager, file_read_op: Operation) -> None:
        assert manager.is_auto_approved(file_read_op) is True

    def test_high_risk_not_auto_approved(self, manager: SecurityManager, file_delete_op: Operation) -> None:
        assert manager.is_auto_approved(file_delete_op) is False

    def test_critical_never_auto_approved(self, manager: SecurityManager, process_kill_op: Operation) -> None:
        assert manager.is_auto_approved(process_kill_op) is False

    def test_white_list_type_auto_approved(self, manager: SecurityManager) -> None:
        policy = SecurityPolicy(
            name="safe_ops",
            priority=50,
            auto_approved_types=["custom_safe_op"],
        )
        manager.register_policy(policy)

        op = Operation(
            operation_type="custom_safe_op",
            target="anything",
            required_permission=Permission.EXECUTE,
        )
        assert manager.is_auto_approved(op) is True


# ---------------------------------------------------------------------------
# 审批流程
# ---------------------------------------------------------------------------


class TestApprovalFlow:
    """审批流程测试。"""

    def test_create_approval_request(self, manager: SecurityManager, file_delete_op: Operation) -> None:
        req = manager.request_approval(file_delete_op)
        assert req.status == ApprovalStatus.PENDING
        assert req.operation == file_delete_op
        assert req.expires_at is not None
        assert req.risk_level == RiskLevel.HIGH

    def test_approve_request(self, manager: SecurityManager, file_delete_op: Operation) -> None:
        req = manager.request_approval(file_delete_op)
        result = manager.process_approval(req.id, approved=True, reason="已确认")
        assert result.status == ApprovalStatus.APPROVED
        assert result.reason == "已确认"

    def test_reject_request(self, manager: SecurityManager, file_delete_op: Operation) -> None:
        req = manager.request_approval(file_delete_op)
        result = manager.process_approval(req.id, approved=False, reason="太危险")
        assert result.status == ApprovalStatus.REJECTED
        assert result.reason == "太危险"

    def test_nonexistent_request_raises(self, manager: SecurityManager) -> None:
        with pytest.raises(KeyError, match="审批请求不存在"):
            manager.process_approval("nonexistent_id", approved=True)

    def test_double_process_raises(self, manager: SecurityManager, file_delete_op: Operation) -> None:
        req = manager.request_approval(file_delete_op)
        manager.process_approval(req.id, approved=True)
        # 已处理的请求应从 pending 中移除
        with pytest.raises(KeyError):
            manager.process_approval(req.id, approved=False)

    def test_expired_request(self, audit_dir: Path) -> None:
        """测试超时审批请求。"""
        mgr = SecurityManager({
            "trust_mode": "normal",
            "audit_log_dir": str(audit_dir),
            "approval_timeout": 0,  # 立即超时
        })
        op = Operation(
            operation_type="file_delete",
            target="test.txt",
            required_permission=Permission.DELETE,
        )
        req = mgr.request_approval(op)
        # 手动设置过期时间为过去
        req.expires_at = datetime.now() - timedelta(seconds=1)

        with pytest.raises(ValueError, match="已过期"):
            mgr.process_approval(req.id, approved=True)

    def test_get_pending_approvals(self, manager: SecurityManager) -> None:
        op1 = Operation(operation_type="file_delete", target="a.txt", required_permission=Permission.DELETE)
        op2 = Operation(operation_type="file_delete", target="b.txt", required_permission=Permission.DELETE)

        req1 = manager.request_approval(op1)
        req2 = manager.request_approval(op2)

        pending = manager.get_pending_approvals()
        assert len(pending) == 2

        manager.process_approval(req1.id, approved=True)
        pending = manager.get_pending_approvals()
        assert len(pending) == 1


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------


class TestAuditLog:
    """审计日志测试。"""

    def test_log_creates_entry(self, manager: SecurityManager) -> None:
        op = Operation(
            operation_type="file_read",
            target="test.txt",
            required_permission=Permission.READ,
        )
        entry = manager.log_operation(op, result="success", user_approved=None)
        assert entry.operation_type == "file_read"
        assert entry.result == "success"
        assert entry.user_approved is None

    def test_log_persists_to_file(self, manager: SecurityManager, audit_dir: Path) -> None:
        op = Operation(
            operation_type="file_write",
            target="output.txt",
            required_permission=Permission.WRITE,
        )
        manager.log_operation(op, result="success")

        # 检查文件已创建
        log_files = list(audit_dir.glob("audit_*.jsonl"))
        assert len(log_files) == 1

        # 检查内容可解析
        with open(log_files[0], "r", encoding="utf-8") as f:
            data = json.loads(f.readline())
            assert data["operation_type"] == "file_write"
            assert data["result"] == "success"

    def test_query_audit_log(self, manager: SecurityManager) -> None:
        op1 = Operation(operation_type="file_read", target="a.txt", required_permission=Permission.READ)
        op2 = Operation(operation_type="file_delete", target="b.txt", required_permission=Permission.DELETE)
        op3 = Operation(operation_type="file_read", target="c.txt", required_permission=Permission.READ)

        manager.log_operation(op1, result="success")
        manager.log_operation(op2, result="denied", user_approved=False)
        manager.log_operation(op3, result="success")

        # 按类型过滤
        reads = manager.get_audit_log({"operation_type": "file_read"})
        assert len(reads) == 2

        # 按结果过滤
        denied = manager.get_audit_log({"result": "denied"})
        assert len(denied) == 1
        assert denied[0].target == "b.txt"

    def test_query_with_target_pattern(self, manager: SecurityManager) -> None:
        op1 = Operation(operation_type="file_read", target="C:\\test\\a.txt", required_permission=Permission.READ)
        op2 = Operation(operation_type="file_read", target="C:\\other\\b.txt", required_permission=Permission.READ)

        manager.log_operation(op1, result="success")
        manager.log_operation(op2, result="success")

        results = manager.get_audit_log({"target": "C:\\test\\*"})
        assert len(results) == 1
        assert results[0].target == "C:\\test\\a.txt"

    def test_query_with_limit(self, manager: SecurityManager) -> None:
        for i in range(10):
            op = Operation(operation_type="file_read", target=f"file_{i}.txt", required_permission=Permission.READ)
            manager.log_operation(op, result="success")

        results = manager.get_audit_log({"limit": 3})
        assert len(results) == 3

    def test_query_empty_log(self, manager: SecurityManager) -> None:
        results = manager.get_audit_log()
        assert results == []

    def test_log_with_approval_creates_audit(self, manager: SecurityManager) -> None:
        """request_approval 内部会自动记录审计日志。"""
        op = Operation(
            operation_type="file_delete",
            target="important.txt",
            required_permission=Permission.DELETE,
        )
        manager.request_approval(op)

        # 应该有一条 pending_approval 日志
        logs = manager.get_audit_log({"result": "pending_approval"})
        assert len(logs) == 1


# ---------------------------------------------------------------------------
# 安全策略
# ---------------------------------------------------------------------------


class TestSecurityPolicy:
    """安全策略管理测试。"""

    def test_register_policy(self, manager: SecurityManager) -> None:
        policy = SecurityPolicy(
            name="test_policy",
            description="测试策略",
            priority=10,
        )
        manager.register_policy(policy)
        policies = manager.get_policies()
        assert any(p.name == "test_policy" for p in policies)

    def test_policy_priority_order(self, manager: SecurityManager) -> None:
        """高优先级策略排在前面。"""
        p_low = SecurityPolicy(name="low_priority", priority=1)
        p_high = SecurityPolicy(name="high_priority", priority=100)

        manager.register_policy(p_low)
        manager.register_policy(p_high)

        policies = manager.get_policies()
        names = [p.name for p in policies]
        assert names.index("high_priority") < names.index("low_priority")

    def test_remove_policy(self, manager: SecurityManager) -> None:
        policy = SecurityPolicy(name="to_remove", priority=10)
        manager.register_policy(policy)
        assert manager.remove_policy("to_remove") is True
        assert not any(p.name == "to_remove" for p in manager.get_policies())

    def test_remove_nonexistent(self, manager: SecurityManager) -> None:
        assert manager.remove_policy("nonexistent") is False

    def test_replace_same_name_policy(self, manager: SecurityManager) -> None:
        """同名策略会被替换。"""
        p1 = SecurityPolicy(name="dup", priority=10, low_action="auto")
        p2 = SecurityPolicy(name="dup", priority=20, low_action="approve")

        manager.register_policy(p1)
        manager.register_policy(p2)

        policies = manager.get_policies()
        dup_policies = [p for p in policies if p.name == "dup"]
        assert len(dup_policies) == 1
        assert dup_policies[0].priority == 20

    def test_policy_get_action(self) -> None:
        policy = SecurityPolicy(
            name="test",
            low_action="auto",
            medium_action="approve",
            high_action="approve",
            critical_action="deny",
        )
        assert policy.get_action(RiskLevel.LOW) == "auto"
        assert policy.get_action(RiskLevel.MEDIUM) == "approve"
        assert policy.get_action(RiskLevel.HIGH) == "approve"
        assert policy.get_action(RiskLevel.CRITICAL) == "deny"

    def test_config_policies_loaded(self, audit_dir: Path) -> None:
        """配置中指定的策略会被加载。"""
        mgr = SecurityManager({
            "trust_mode": "normal",
            "audit_log_dir": str(audit_dir),
            "policies": [
                {"name": "from_config", "description": "配置策略", "priority": 5},
            ],
        })
        assert any(p.name == "from_config" for p in mgr.get_policies())


# ---------------------------------------------------------------------------
# 信任模式切换
# ---------------------------------------------------------------------------


class TestTrustMode:
    """信任模式切换测试。"""

    def test_initial_mode(self, manager: SecurityManager) -> None:
        assert manager.trust_mode == TrustMode.NORMAL

    def test_switch_to_auto(self, manager: SecurityManager) -> None:
        manager.trust_mode = TrustMode.AUTO
        assert manager.trust_mode == TrustMode.AUTO

    def test_switch_to_strict(self, manager: SecurityManager) -> None:
        manager.trust_mode = TrustMode.STRICT
        assert manager.trust_mode == TrustMode.STRICT

    def test_switch_by_string(self, manager: SecurityManager) -> None:
        manager.trust_mode = "auto"
        assert manager.trust_mode == TrustMode.AUTO

    def test_auto_mode_bypasses_risk(self, manager: SecurityManager, process_kill_op: Operation) -> None:
        """AUTO 模式下即使是 CRITICAL 操作也放行。"""
        manager.trust_mode = TrustMode.AUTO
        assert manager.check_permission(process_kill_op) is True
        assert manager.is_auto_approved(process_kill_op) is True

    def test_strict_mode_blocks_low_risk(self, manager: SecurityManager, file_read_op: Operation) -> None:
        """STRICT 模式下 LOW 风险操作也需确认。"""
        manager.trust_mode = TrustMode.STRICT
        assert manager.check_permission(file_read_op) is False
        assert manager.is_auto_approved(file_read_op) is False

