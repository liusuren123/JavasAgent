"""安全管理器。

对危险操作进行权限校验、风险评级、审批流程和审计日志。
"""

from __future__ import annotations

import fnmatch
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.security_models import (
    ApprovalRequest,
    ApprovalStatus,
    AuditLogEntry,
    Operation,
    Permission,
    RiskLevel,
    SecurityPolicy,
    TrustMode,
)
from src.core.security_risk_engine import RiskRuleEngine


class SecurityManager:
    """安全管理器。

    核心职责：
    - 评估操作风险等级
    - 检查权限
    - 管理审批流程
    - 记录审计日志
    - 管理安全策略

    使用方式::

        mgr = SecurityManager(config)
        risk = mgr.evaluate_risk(operation)
        if mgr.is_auto_approved(operation):
            # 直接执行
        else:
            req = mgr.request_approval(operation)
            # 等待人工审批...
            mgr.process_approval(req.id, approved=True)
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """初始化安全管理器。

        Args:
            config: 配置字典，支持以下键：
                - trust_mode: 信任模式 ("auto" | "normal" | "strict")
                - audit_log_dir: 审计日志目录
                - approval_timeout: 默认审批超时（秒）
                - policies: 策略列表（字典形式）
        """
        config = config or {}
        self._trust_mode = TrustMode(config.get("trust_mode", "normal"))
        self._audit_log_dir = Path(config.get("audit_log_dir", "./data/audit"))
        self._approval_timeout = config.get("approval_timeout", 300)

        # 审批请求暂存（内存中）
        self._pending_requests: dict[str, ApprovalRequest] = {}

        # 安全策略列表（按优先级排序）
        self._policies: list[SecurityPolicy] = []

        # 风险规则引擎
        self._risk_engine = RiskRuleEngine()

        # 加载配置中的策略
        for policy_data in config.get("policies", []):
            policy = SecurityPolicy.from_dict(policy_data)
            self._policies.append(policy)
        self._policies.sort(key=lambda p: p.priority, reverse=True)

        # 确保审计日志目录存在
        self._audit_log_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "SecurityManager 初始化完成 | trust_mode={} | policies={} | audit_dir={}",
            self._trust_mode.value,
            len(self._policies),
            self._audit_log_dir,
        )

    # ------------------------------------------------------------------
    # 风险评估
    # ------------------------------------------------------------------

    def evaluate_risk(self, operation: Operation) -> RiskLevel:
        """评估操作的风险等级。

        评估优先级：
        1. 策略中的 risk_overrides
        2. 内置风险规则（取最高）
        3. 回退到操作自带的风险等级

        Args:
            operation: 待评估的操作

        Returns:
            评估后的风险等级
        """
        # 收集所有策略的 risk_overrides
        overrides: dict[str, str] = {}
        for policy in self._policies:
            overrides.update(policy.risk_overrides)

        result = self._risk_engine.evaluate(operation, policy_overrides=overrides if overrides else None)
        if result is not None:
            return result

        return operation.risk_level

    # ------------------------------------------------------------------
    # 权限检查
    # ------------------------------------------------------------------

    def check_permission(self, operation: Operation, context: dict[str, Any] | None = None) -> bool:
        """检查操作是否被允许。

        Args:
            operation: 待检查的操作
            context: 上下文信息（可选）

        Returns:
            True 表示允许，False 表示拒绝
        """
        context = context or {}

        if self._trust_mode == TrustMode.AUTO:
            logger.debug("AUTO 模式，自动放行: {}", operation.operation_type)
            return True

        if self._trust_mode == TrustMode.STRICT:
            logger.debug("STRICT 模式，需审批: {}", operation.operation_type)
            return False

        risk = self.evaluate_risk(operation)

        # 检查目标黑名单
        for policy in self._policies:
            for denied in policy.denied_targets:
                if self._match_target(operation.target, denied):
                    logger.warning("目标 {} 匹配黑名单策略 {}，拒绝", operation.target, policy.name)
                    return False

        # 检查操作类型白名单
        for policy in self._policies:
            if operation.operation_type in policy.auto_approved_types:
                logger.debug("操作类型 {} 在白名单中，自动放行", operation.operation_type)
                return True

        # 根据风险等级对应的策略动作判断
        for policy in self._policies:
            action = policy.get_action(risk)
            if action == "auto":
                return True
            elif action == "deny":
                return False
            return False

        return risk in (RiskLevel.LOW,)

    # ------------------------------------------------------------------
    # 自动批准判断
    # ------------------------------------------------------------------

    def is_auto_approved(self, operation: Operation) -> bool:
        """判断操作是否可以自动批准。"""
        if self._trust_mode == TrustMode.AUTO:
            return True
        if self._trust_mode == TrustMode.STRICT:
            return False

        risk = self.evaluate_risk(operation)
        if risk == RiskLevel.CRITICAL:
            return False

        for policy in self._policies:
            if operation.operation_type in policy.auto_approved_types:
                return True

        for policy in self._policies:
            action = policy.get_action(risk)
            if action == "auto":
                return True
            if action in ("approve", "deny"):
                return False

        return risk == RiskLevel.LOW

    # ------------------------------------------------------------------
    # 审批流程
    # ------------------------------------------------------------------

    def request_approval(self, operation: Operation) -> ApprovalRequest:
        """创建审批请求。"""
        risk = self.evaluate_risk(operation)
        risk_reason = self._build_risk_reason(operation, risk)

        req = ApprovalRequest.create(
            operation=operation,
            risk_level=risk,
            risk_reason=risk_reason,
            timeout_seconds=self._approval_timeout,
        )
        self._pending_requests[req.id] = req

        logger.info(
            "创建审批请求: id={} | type={} | target={} | risk={}",
            req.id, operation.operation_type, operation.target, risk.value,
        )
        self.log_operation(operation, result="pending_approval", user_approved=None)
        return req

    def process_approval(self, request_id: str, approved: bool, reason: str = "") -> ApprovalRequest:
        """处理审批结果。"""
        req = self._pending_requests.get(request_id)
        if req is None:
            raise KeyError(f"审批请求不存在: {request_id}")
        if req.status != ApprovalStatus.PENDING:
            raise ValueError(f"请求已处理: 当前状态={req.status.value}")
        if req.is_expired:
            req.status = ApprovalStatus.EXPIRED
            req.resolved_at = datetime.now()
            logger.warning("审批请求已过期: id={}", request_id)
            self.log_operation(req.operation, result="expired", user_approved=None)
            raise ValueError("审批请求已过期")

        req.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        req.resolved_at = datetime.now()
        req.reason = reason

        result = "approved" if approved else "rejected"
        self.log_operation(req.operation, result=result, user_approved=approved, reason=reason)
        logger.info("审批结果: id={} | status={} | reason={}", request_id, req.status.value, reason)

        self._pending_requests.pop(request_id, None)
        return req

    def get_pending_approvals(self) -> list[ApprovalRequest]:
        """获取所有待审批的请求。"""
        expired_ids = []
        for req_id, req in self._pending_requests.items():
            if req.is_expired:
                req.status = ApprovalStatus.EXPIRED
                req.resolved_at = datetime.now()
                expired_ids.append(req_id)
        for req_id in expired_ids:
            self._pending_requests.pop(req_id, None)
        return [req for req in self._pending_requests.values() if req.status == ApprovalStatus.PENDING]

    def _build_risk_reason(self, operation: Operation, risk: RiskLevel) -> str:
        """生成风险说明文本。"""
        reasons = {
            RiskLevel.LOW: "低风险操作",
            RiskLevel.MEDIUM: "中等风险操作，可能影响系统状态",
            RiskLevel.HIGH: "高风险操作，可能导致数据丢失或系统不稳定",
            RiskLevel.CRITICAL: "极高风险操作，直接影响系统核心功能",
        }
        base = reasons.get(risk, "未知风险")
        details = []
        if operation.required_permission in (Permission.DELETE, Permission.SYSTEM):
            details.append(f"需要 {operation.required_permission.value} 权限")
        if operation.operation_type in ("process_kill", "registry_modify", "registry_delete"):
            details.append(f"操作类型 {operation.operation_type} 属于高危操作")
        if any(pat in operation.target.lower() for pat in ["windows", "system32", "program files"]):
            details.append(f"目标路径 {operation.target} 属于系统保护区域")
        return f"{base}。{'；'.join(details)}" if details else base

    # ------------------------------------------------------------------
    # 审计日志
    # ------------------------------------------------------------------

    def log_operation(
        self,
        operation: Operation,
        result: str,
        user_approved: bool | None = None,
        reason: str = "",
    ) -> AuditLogEntry:
        """记录操作审计日志。"""
        entry = AuditLogEntry.create(
            operation=operation, result=result, user_approved=user_approved, reason=reason,
        )
        self._persist_audit_entry(entry)
        logger.debug(
            "审计日志: type={} | target={} | result={} | user_approved={}",
            operation.operation_type, operation.target, result, user_approved,
        )
        return entry

    def get_audit_log(self, filters: dict[str, Any] | None = None) -> list[AuditLogEntry]:
        """查询审计日志。"""
        filters = filters or {}
        limit = filters.get("limit", 100)
        entries = self._load_all_audit_entries()

        if "operation_type" in filters:
            entries = [e for e in entries if e.operation_type == filters["operation_type"]]
        if "result" in filters:
            entries = [e for e in entries if e.result == filters["result"]]
        if "risk_level" in filters:
            entries = [e for e in entries if e.risk_level == filters["risk_level"]]
        if "target" in filters:
            entries = [e for e in entries if fnmatch.fnmatch(e.target, filters["target"])]
        if "start_time" in filters:
            start = datetime.fromisoformat(filters["start_time"])
            entries = [e for e in entries if e.timestamp >= start]
        if "end_time" in filters:
            end = datetime.fromisoformat(filters["end_time"])
            entries = [e for e in entries if e.timestamp <= end]

        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit]

    def _persist_audit_entry(self, entry: AuditLogEntry) -> None:
        """将审计日志持久化到 JSONL 文件。"""
        log_file = self._audit_log_dir / f"audit_{entry.timestamp.strftime('%Y-%m-%d')}.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.error("审计日志写入失败: {}", e)

    def _load_all_audit_entries(self) -> list[AuditLogEntry]:
        """加载所有审计日志文件。"""
        entries: list[AuditLogEntry] = []
        if not self._audit_log_dir.exists():
            return entries
        for log_file in self._audit_log_dir.glob("audit_*.jsonl"):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        entries.append(AuditLogEntry.from_dict(json.loads(line)))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("读取审计日志文件 {} 失败: {}", log_file, e)
        return entries

    # ------------------------------------------------------------------
    # 策略管理
    # ------------------------------------------------------------------

    def register_policy(self, policy: SecurityPolicy) -> None:
        """注册安全策略。"""
        self._policies = [p for p in self._policies if p.name != policy.name]
        self._policies.append(policy)
        self._policies.sort(key=lambda p: p.priority, reverse=True)
        logger.info("注册安全策略: name={} | priority={}", policy.name, policy.priority)

    def remove_policy(self, name: str) -> bool:
        """移除安全策略。"""
        original_count = len(self._policies)
        self._policies = [p for p in self._policies if p.name != name]
        removed = len(self._policies) < original_count
        if removed:
            logger.info("移除安全策略: name={}", name)
        return removed

    def get_policies(self) -> list[SecurityPolicy]:
        """获取所有已注册的安全策略。"""
        return list(self._policies)

    # ------------------------------------------------------------------
    # 信任模式
    # ------------------------------------------------------------------

    @property
    def trust_mode(self) -> TrustMode:
        """获取当前信任模式。"""
        return self._trust_mode

    @trust_mode.setter
    def trust_mode(self, mode: TrustMode | str) -> None:
        """设置信任模式。"""
        if isinstance(mode, str):
            mode = TrustMode(mode)
        self._trust_mode = mode
        logger.info("信任模式切换为: {}", mode.value)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _match_target(target: str, pattern: str) -> bool:
        """匹配目标与模式（不区分大小写）。"""
        return fnmatch.fnmatch(target.lower(), pattern.lower())
