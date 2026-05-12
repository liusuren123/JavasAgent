# -*- coding: utf-8 -*-
"""YAML 技能文件验证器。

验证技能定义的格式、动作合法性和参数完整性。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


# 合法的 action 名称集合（20 个）
VALID_ACTIONS: set[str] = {
    "key_combo",
    "key_type",
    "click",
    "double_click",
    "right_click",
    "drag",
    "scroll",
    "type_text",
    "click_text",
    "click_icon",
    "move_mouse",
    "wait",
    "wait_text",
    "screenshot",
    "assert_text",
    "assert_screen",
    "condition",
    "loop",
    "run_skill",
    "set_var",
}

# 合法的 JSON Schema 类型
_VALID_PARAM_TYPES = {"string", "integer", "number", "boolean", "array", "object"}


@dataclass
class ValidationResult:
    """验证结果。

    Attributes:
        valid: 是否通过验证。
        errors: 错误列表（阻止加载）。
        warnings: 警告列表（可加载但不建议）。
    """
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SkillValidator:
    """YAML 技能文件验证器。"""

    def validate(self, data: dict[str, Any]) -> ValidationResult:
        """验证技能定义字典。

        Args:
            data: 从 YAML 解析出的字典。

        Returns:
            ValidationResult 包含 valid / errors / warnings。
        """
        errors: list[str] = []
        warnings: list[str] = []

        # 1. 必填字段
        for required in ("name", "description", "steps"):
            if required not in data:
                errors.append(f"缺少必填字段: {required}")
            elif not data[required]:
                errors.append(f"必填字段为空: {required}")

        # 有致命错误就提前返回
        if errors:
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        # 2. steps 必须是 list
        steps = data.get("steps")
        if not isinstance(steps, list):
            errors.append("steps 必须是列表")
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        # 3. 逐步骤验证
        for i, step in enumerate(steps):
            step_errors, step_warnings = self._validate_step(step, i)
            errors.extend(step_errors)
            warnings.extend(step_warnings)

        # 4. 参数类型验证
        params = data.get("parameters")
        if params and isinstance(params, dict):
            for pname, pschema in params.items():
                if isinstance(pschema, dict):
                    ptype = pschema.get("type")
                    if ptype and ptype not in _VALID_PARAM_TYPES:
                        errors.append(f"参数 '{pname}' 的 type '{ptype}' 不合法")

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def validate_file(self, path: Path) -> ValidationResult:
        """加载 YAML 文件并验证。

        Args:
            path: YAML 文件路径。

        Returns:
            ValidationResult。
        """
        try:
            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
        except Exception as e:
            return ValidationResult(
                valid=False,
                errors=[f"YAML 加载失败: {e}"],
            )

        if not isinstance(data, dict):
            return ValidationResult(
                valid=False,
                errors=["YAML 顶层必须是字典"],
            )

        return self.validate(data)

    def _validate_step(self, step: dict[str, Any], index: int) -> tuple[list[str], list[str]]:
        """验证单个步骤。

        Returns:
            (errors, warnings)
        """
        errors: list[str] = []
        warnings: list[str] = []
        prefix = f"步骤 {index}"

        if not isinstance(step, dict):
            errors.append(f"{prefix}: 步骤必须是字典")
            return errors, warnings

        action = step.get("action")
        if not action:
            errors.append(f"{prefix}: 缺少 action 字段")
            return errors, warnings

        if action not in VALID_ACTIONS:
            errors.append(f"{prefix}: 未知 action '{action}'")
            return errors, warnings

        # loop 必须有 max_iterations 且 <= 100
        if action == "loop":
            max_iter = step.get("max_iterations")
            if max_iter is None:
                errors.append(f"{prefix}: loop 必须有 max_iterations")
            elif not isinstance(max_iter, (int, float)) or max_iter > 100:
                errors.append(f"{prefix}: loop max_iterations 必须 <= 100")

        # condition 必须有 when
        if action == "condition":
            if "when" not in step:
                errors.append(f"{prefix}: condition 必须有 when 字段")

        # run_skill 嵌套深度提示
        if action == "run_skill":
            warnings.append(f"{prefix}: run_skill 会嵌套调用，注意控制递归深度")

        return errors, warnings
