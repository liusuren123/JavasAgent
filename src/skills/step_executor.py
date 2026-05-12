# -*- coding: utf-8 -*-
"""步骤执行器 — YAML 技能的核心调度器。

将 YAML 中的 action 映射到注册的原语函数，顺序执行步骤列表，
支持模板变量替换和错误中断。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.skills.context import SkillContext


class StepExecutor:
    """YAML 技能步骤执行器。

    顺序执行步骤列表，某步失败时中断。
    每步通过 ACTION_REGISTRY 查找对应的执行函数。
    """

    def __init__(
        self,
        platform: Any = None,
        perception: Any = None,
        humanhand: Any = None,
        skill_executor: Any = None,
    ) -> None:
        self._platform = platform
        self._perception = perception
        self._humanhand = humanhand
        self._skill_executor = skill_executor

        logger.debug(
            "StepExecutor 初始化 (platform={}, perception={}, humanhand={})",
            platform is not None,
            perception is not None,
            humanhand is not None,
        )

    async def execute_step(self, step: dict[str, Any], context: SkillContext) -> dict[str, Any]:
        """执行单个步骤。

        从 step 中取 action 字段，查找注册函数并调用。

        Args:
            step: 步骤字典，包含 action 和参数。
            context: 执行上下文。

        Returns:
            执行结果字典。
        """
        action = step.get("action", "")
        if not action:
            return {"success": False, "error": "步骤缺少 action 字段"}

        # 获取注册表（懒加载）
        from src.skills.actions import get_action_registry
        registry = get_action_registry()

        fn = registry.get(action)
        if fn is None:
            return {"success": False, "error": f"未知 action: {action}"}

        # 模板变量替换
        resolved_step = self._resolve_params(step, context)

        # 根据函数签名传入不同参数
        try:
            result = await fn(
                step=resolved_step,
                context=context,
                platform=self._platform,
                perception=self._perception,
                humanhand=self._humanhand,
                executor=self,
                skill_executor=self._skill_executor,
            )
        except TypeError:
            # 函数不接受所有参数，只传它需要的
            try:
                result = await fn(
                    step=resolved_step,
                    context=context,
                    platform=self._platform,
                )
            except TypeError:
                result = await fn(resolved_step, context)

        if isinstance(result, dict):
            return result
        return {"success": True, "data": result}

    async def execute_steps(
        self,
        steps: list[dict[str, Any]],
        context: SkillContext,
    ) -> dict[str, Any]:
        """顺序执行步骤列表。

        某步返回 success=false 时中断执行。

        Args:
            steps: 步骤列表。
            context: 执行上下文。

        Returns:
            最终结果字典。
        """
        total = len(steps)
        context.total_steps = total

        for i, step in enumerate(steps):
            context.current_step = i
            action_name = step.get("action", "?")
            logger.debug("执行步骤 {}/{}: action={}", i + 1, total, action_name)

            result = await self.execute_step(step, context)

            if not result.get("success", True):
                logger.warning(
                    "步骤 {}/{} 失败: action={} error={}",
                    i + 1, total, action_name, result.get("error", ""),
                )
                return {
                    "success": False,
                    "completed_steps": i,
                    "total_steps": total,
                    "failed_step": i,
                    "failed_action": action_name,
                    "error": result.get("error", "未知错误"),
                }

        return {
            "success": True,
            "completed_steps": total,
            "total_steps": total,
        }

    def _resolve_params(self, step: dict[str, Any], context: SkillContext) -> dict[str, Any]:
        """对 step 中所有字符串值做模板变量替换。

        Args:
            step: 原始步骤字典。
            context: 执行上下文。

        Returns:
            替换后的步骤字典。
        """
        resolved = {}
        for key, value in step.items():
            if isinstance(value, str):
                resolved[key] = context.resolve(value)
            elif isinstance(value, list):
                resolved[key] = [
                    context.resolve(v) if isinstance(v, str) else v
                    for v in value
                ]
            elif isinstance(value, dict):
                resolved[key] = self._resolve_params(value, context)
            else:
                resolved[key] = value
        return resolved
