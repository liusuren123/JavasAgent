"""技能链执行模块。

支持按顺序执行多个技能步骤，步骤间支持依赖关系和结果注入。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from loguru import logger

from src.tools.skill_executor_models import SkillChainResult, SkillChainStep


class SkillChainExecutor:
    """技能链执行器。

    按顺序执行多个技能步骤，支持步骤间的依赖关系。
    前一步骤的结果可以作为后续步骤的参数（通过 ``$step_{index}`` 引用）。

    Usage::

        chain = SkillChainExecutor(executor)
        result = await chain.run(steps)
    """

    def __init__(self, execute_skill_fn: Any) -> None:
        """初始化技能链执行器。

        Args:
            execute_skill_fn: 单技能执行函数，签名为
                ``async (skill_name: str, params: dict) -> dict``。
        """
        self._execute_skill = execute_skill_fn

    async def run(self, steps: list[SkillChainStep]) -> SkillChainResult:
        """执行技能链。

        按顺序执行多个技能步骤，支持步骤间的依赖关系。
        前一步骤的结果可以作为后续步骤的参数（通过 ``$prev`` 引用）。

        Args:
            steps: 技能链步骤列表。

        Returns:
            技能链执行结果。
        """
        chain_id = f"chain_{uuid.uuid4().hex[:8]}"
        logger.info("开始技能链执行: {} ({} 步)", chain_id, len(steps))

        start_time = time.monotonic()
        step_results: list[dict[str, Any]] = []
        completed: dict[int, dict[str, Any]] = {}
        chain_success = True
        chain_error = ""

        for step in steps:
            # 检查依赖是否都已完成
            deps_ok = all(dep in completed for dep in step.depends_on)
            if not deps_ok:
                chain_success = False
                chain_error = f"步骤 {step.step_index} 的依赖未完成"
                step_results.append({"success": False, "error": chain_error})
                break

            # 注入前序步骤的结果
            resolved_params = self._resolve_chain_params(step, completed)

            # 执行
            result = await self._execute_skill(step.skill_name, resolved_params)
            step_results.append(result)

            if result.get("success", False):
                completed[step.step_index] = result.get("data", {})
            else:
                chain_success = False
                chain_error = (
                    f"步骤 {step.step_index} ({step.skill_name}) "
                    f"执行失败: {result.get('error', '')}"
                )
                break

        total_duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "技能链完成: {} success={}, duration={}ms",
            chain_id,
            chain_success,
            total_duration_ms,
        )

        return SkillChainResult(
            chain_id=chain_id,
            steps=steps,
            step_results=step_results,
            success=chain_success,
            error=chain_error,
            total_duration_ms=total_duration_ms,
        )

    @staticmethod
    def _resolve_chain_params(
        step: SkillChainStep,
        completed: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        """解析技能链参数中的依赖引用。

        支持以 ``$step_{index}`` 格式引用前序步骤的结果。

        Args:
            step: 当前步骤。
            completed: 已完成步骤的结果映射。

        Returns:
            解析后的参数字典。
        """
        resolved = dict(step.params)

        # 将依赖步骤的结果注入到参数中
        for dep_index in step.depends_on:
            dep_key = f"$step_{dep_index}"
            if dep_index in completed:
                resolved[dep_key] = completed[dep_index]

        return resolved
