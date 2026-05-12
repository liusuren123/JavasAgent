# -*- coding: utf-8 -*-
"""技能执行上下文。

在 YAML 技能的步骤之间传递参数、中间变量和执行结果。
支持点号路径（parameters.xxx）和模板变量替换（{{name}}）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillContext:
    """技能执行上下文，在步骤之间传递数据。

    Attributes:
        parameters: 用户传入的参数（只读，技能调用时设定）。
        variables: 步骤中间变量（可通过 set 修改）。
        result: 最终执行结果。
        screenshots: 执行过程截图证据列表。
        current_step: 当前执行的步骤索引（从 0 开始）。
        total_steps: 总步骤数。
    """

    parameters: dict[str, Any] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    screenshots: list[bytes] = field(default_factory=list)
    current_step: int = 0
    total_steps: int = 0

    # ------------------------------------------------------------------
    # 变量访问
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """获取变量值，支持点号路径。

        路径格式：
        - ``parameters.filename`` → self.parameters["filename"]
        - ``variables.count`` → self.variables["count"]
        - ``result.status`` → self.result["status"]
        - 纯键名 → 先查 variables，再查 parameters

        Args:
            key: 变量路径或键名。
            default: 找不到时的默认值。

        Returns:
            变量值或 default。
        """
        if "." in key:
            parts = key.split(".", 1)
            namespace = parts[0]
            sub_key = parts[1]

            root = self._get_namespace(namespace)
            return self._deep_get(root, sub_key, default)

        # 无命名空间前缀：优先 variables → parameters
        if key in self.variables:
            return self.variables[key]
        if key in self.parameters:
            return self.parameters[key]
        return default

    def set(self, key: str, value: Any) -> None:
        """设置中间变量。

        Args:
            key: 变量名（支持点号路径设置嵌套值）。
            value: 变量值。
        """
        if "." in key:
            parts = key.split(".", 1)
            if parts[0] == "variables":
                self._deep_set(self.variables, parts[1], value)
            elif parts[0] == "result":
                self._deep_set(self.result, parts[1], value)
            else:
                self._deep_set(self.variables, key, value)
        else:
            self.variables[key] = value

    # ------------------------------------------------------------------
    # 模板变量替换
    # ------------------------------------------------------------------

    def resolve(self, template: Any) -> Any:
        """解析模板变量替换。

        将字符串中的 ``{{key}}`` 替换为上下文中对应的值。
        如果 template 不是字符串则原样返回。

        Args:
            template: 可能包含 ``{{...}}`` 占位符的模板。

        Returns:
            替换后的值。变量不存在时保留原模板。
        """
        if not isinstance(template, str):
            return template

        import re

        def _replace(match: re.Match) -> str:
            key = match.group(1).strip()
            value = self.get(key)
            if value is None:
                return match.group(0)  # 变量不存在，保留原模板
            return str(value)

        return re.sub(r"\{\{(.+?)\}\}", _replace, template)

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（screenshots 转为长度列表）。"""
        return {
            "parameters": self.parameters,
            "variables": self.variables,
            "result": self.result,
            "screenshots_count": len(self.screenshots),
            "current_step": self.current_step,
            "total_steps": self.total_steps,
        }

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _get_namespace(self, name: str) -> dict[str, Any]:
        """根据命名空间名称获取对应字典。"""
        if name == "parameters":
            return self.parameters
        if name == "variables":
            return self.variables
        if name == "result":
            return self.result
        return self.variables  # 未知命名空间降级为 variables

    @staticmethod
    def _deep_get(obj: dict, key: str, default: Any = None) -> Any:
        """支持多级点号路径的字典取值。"""
        parts = key.split(".")
        current = obj
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    @staticmethod
    def _deep_set(obj: dict, key: str, value: Any) -> None:
        """支持多级点号路径的字典设值。"""
        parts = key.split(".")
        current = obj
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
