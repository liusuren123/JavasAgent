"""安全风险规则引擎。

内置风险评估规则，包含操作类型、文件路径、进程名、权限等级等风险映射。
"""

from __future__ import annotations

import fnmatch
from typing import Any

from loguru import logger

from src.core.security_models import Operation, RiskLevel


class RiskRuleEngine:
    """风险规则引擎。

    收集所有匹配规则，取最高风险等级作为最终评估结果。
    规则优先级：路径/进程模式 > 操作类型 > 权限映射。
    """

    # 风险等级排序权重
    _RISK_ORDER: dict[RiskLevel, int] = {
        RiskLevel.LOW: 0,
        RiskLevel.MEDIUM: 1,
        RiskLevel.HIGH: 2,
        RiskLevel.CRITICAL: 3,
    }

    def __init__(self) -> None:
        self._builtin_rules = self._build_builtin_rules()

    def evaluate(self, operation: Operation, policy_overrides: dict[str, str] | None = None) -> RiskLevel | None:
        """评估操作风险等级。

        Args:
            operation: 待评估的操作
            policy_overrides: 策略层覆盖规则（pattern -> risk_level）

        Returns:
            评估后的风险等级，无匹配返回 None
        """
        candidates: list[RiskLevel] = []

        # 1. 策略覆盖规则
        if policy_overrides:
            for pattern, risk_str in policy_overrides.items():
                if self._match(operation.target, pattern) or self._match(operation.operation_type, pattern):
                    candidates.append(RiskLevel(risk_str))

        rules = self._builtin_rules

        # 2. 文件路径模式
        for pattern, risk_str in rules.get("path_patterns", {}).items():
            if self._match(operation.target, pattern):
                candidates.append(RiskLevel(risk_str))

        # 3. 进程名模式
        for pattern, risk_str in rules.get("process_patterns", {}).items():
            if self._match(operation.target, pattern):
                candidates.append(RiskLevel(risk_str))

        # 4. 操作类型
        type_rules = rules.get("operation_types", {})
        if operation.operation_type in type_rules:
            candidates.append(RiskLevel(type_rules[operation.operation_type]))

        # 5. 权限等级映射
        perm_rules = rules.get("permission_mapping", {})
        perm_str = operation.required_permission.value
        if perm_str in perm_rules:
            candidates.append(RiskLevel(perm_rules[perm_str]))

        if not candidates:
            return None

        return max(candidates, key=lambda r: self._RISK_ORDER[r])

    @staticmethod
    def _match(text: str, pattern: str) -> bool:
        """匹配文本与通配符模式（不区分大小写）。"""
        return fnmatch.fnmatch(text.lower(), pattern.lower())

    def _build_builtin_rules(self) -> dict[str, Any]:
        """构建内置风险规则。"""
        return {
            "operation_types": {
                "file_delete": "high",
                "file_write": "medium",
                "file_move": "medium",
                "file_copy": "low",
                "file_read": "low",
                "process_kill": "critical",
                "process_start": "medium",
                "registry_modify": "critical",
                "registry_delete": "critical",
                "registry_read": "medium",
                "system_shutdown": "critical",
                "system_restart": "critical",
                "network_connect": "medium",
                "network_download": "medium",
                "network_upload": "high",
                "app_install": "high",
                "app_uninstall": "high",
                "script_execute": "high",
                "shell_command": "high",
            },
            "path_patterns": {
                "C:\\Windows\\**": "critical",
                "C:\\Program Files\\**": "high",
                "C:\\Program Files (x86)\\**": "high",
                "C:\\ProgramData\\**": "high",
                "**\\*.sys": "critical",
                "**\\*.dll": "high",
                "**\\*.exe": "high",
                "**\\*.bat": "high",
                "**\\*.ps1": "high",
                "**\\*.vbs": "high",
            },
            "process_patterns": {
                "svchost*": "critical",
                "csrss*": "critical",
                "lsass*": "critical",
                "wininit*": "critical",
                "services*": "critical",
                "explorer*": "high",
                "dwm*": "high",
            },
            "permission_mapping": {
                "read": "low",
                "write": "medium",
                "execute": "medium",
                "delete": "high",
                "system": "critical",
            },
        }
