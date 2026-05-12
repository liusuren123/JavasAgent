# -*- coding: utf-8 -*-
"""技能描述执行系统 — YAML 技能加载、验证、执行核心包。

提供以下组件：
- SkillContext   — 执行上下文，在步骤之间传递数据
- SkillValidator — YAML 技能文件验证器
- StepExecutor   — 步骤执行器，将 YAML action 映射到平台原语
- SkillLoader    — YAML 技能文件加载器
- ExpressionEvaluator — 安全条件表达式求值器
"""

from src.skills.context import SkillContext

__all__ = [
    "SkillContext",
    "ExpressionEvaluator",
    "SkillValidator",
    "ValidationResult",
    "StepExecutor",
    "SkillLoader",
]

# 延迟导入——避免循环依赖和模块缺失
def __getattr__(name: str):
    if name == "ExpressionEvaluator":
        from src.skills.expression import ExpressionEvaluator
        return ExpressionEvaluator
    if name == "SkillValidator":
        from src.skills.validator import SkillValidator
        return SkillValidator
    if name == "ValidationResult":
        from src.skills.validator import ValidationResult
        return ValidationResult
    if name == "StepExecutor":
        from src.skills.step_executor import StepExecutor
        return StepExecutor
    if name == "SkillLoader":
        from src.skills.skill_loader import SkillLoader
        return SkillLoader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
