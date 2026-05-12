# -*- coding: utf-8 -*-
"""控制流原语：wait, wait_text, condition, loop, run_skill, set_var。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from src.skills.expression import ExpressionEvaluator


async def exec_wait(step: dict[str, Any], context: Any) -> dict[str, Any]:
    """等待指定秒数。

    参数：duration（秒），默认 1.0，上限 30 秒。
    """
    duration = float(step.get("duration", 1.0))
    duration = min(duration, 30.0)  # 上限 30 秒
    logger.debug("wait: {:.2f}s", duration)
    await asyncio.sleep(duration)
    return {"success": True, "duration": duration}


async def exec_wait_text(step: dict[str, Any], context: Any, perception: Any = None) -> dict[str, Any]:
    """循环 OCR 等待文字出现。

    参数：text, timeout(默认5), interval(默认0.5)
    """
    text = step.get("text", "")
    if not text:
        return {"success": False, "error": "text 参数为空"}

    text = context.resolve(text)
    timeout = float(step.get("timeout", 5.0))
    interval = float(step.get("interval", 0.5))

    logger.debug("wait_text: '{}' timeout={} interval={}", text, timeout, interval)

    if not perception:
        await asyncio.sleep(timeout)
        return {"success": False, "error": "perception 未提供"}

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        screen_text = await _acall(perception, "get_screen_text")
        if screen_text and text in screen_text:
            elapsed = time.monotonic() - start
            return {"success": True, "text": text, "elapsed": round(elapsed, 2)}
        await asyncio.sleep(interval)

    return {"success": False, "error": f"等待文字超时: {text}"}


async def exec_condition(step: dict[str, Any], context: Any, executor: Any = None) -> dict[str, Any]:
    """条件分支。

    参数：when(表达式), then(步骤列表), else(可选步骤列表)
    """
    when_expr = step.get("when", "")
    evaluator = ExpressionEvaluator()
    result = evaluator.evaluate(when_expr, context)
    logger.debug("condition: '{}' => {}", when_expr, result)

    steps_to_run = step.get("then", []) if result else step.get("else", [])

    if not steps_to_run:
        return {"success": True, "branch": "then" if result else "else", "executed": 0}

    if executor is None:
        return {"success": False, "error": "executor 未提供"}

    exec_result = await executor.execute_steps(steps_to_run, context)
    return {
        "success": exec_result.get("success", True),
        "branch": "then" if result else "else",
        "executed": exec_result.get("completed_steps", 0),
    }


async def exec_loop(step: dict[str, Any], context: Any, executor: Any = None) -> dict[str, Any]:
    """循环执行步骤列表。

    参数：steps, max_iterations(上限100), break_when(可选条件表达式)
    """
    steps = step.get("steps", [])
    max_iter = min(int(step.get("max_iterations", 10)), 100)
    break_when = step.get("break_when")
    evaluator = ExpressionEvaluator()

    logger.debug("loop: max_iterations={}, break_when={}", max_iter, break_when)

    if not steps:
        return {"success": True, "iterations": 0}

    if executor is None:
        return {"success": False, "error": "executor 未提供"}

    actual_iterations = 0
    for i in range(max_iter):
        actual_iterations = i + 1

        # 检查 break 条件
        if break_when and evaluator.evaluate(break_when, context):
            logger.debug("loop break at iteration {}", i)
            break

        exec_result = await executor.execute_steps(steps, context)
        if not exec_result.get("success", True):
            return {
                "success": False,
                "iterations": actual_iterations,
                "error": f"循环第 {actual_iterations} 次迭代失败",
            }

    return {"success": True, "iterations": actual_iterations}


async def exec_run_skill(step: dict[str, Any], context: Any, skill_executor: Any = None) -> dict[str, Any]:
    """嵌套调用另一个技能。

    参数：skill_name, params(传给子技能的参数)
    """
    skill_name = step.get("skill_name", "")
    if not skill_name:
        return {"success": False, "error": "skill_name 参数为空"}

    params = step.get("params", {})

    # 递归深度检查
    depth = context.get("_skill_depth", 0)
    if depth >= 5:
        return {"success": False, "error": f"嵌套调用深度超限 (depth={depth})"}

    logger.debug("run_skill: '{}' depth={}", skill_name, depth)

    if skill_executor is None:
        return {"success": False, "error": "skill_executor 未提供"}

    # 设置子技能的深度
    child_params = dict(params)
    child_params["_skill_depth"] = depth + 1

    result = await _acall(skill_executor, "execute_skill", skill_name, child_params)
    if isinstance(result, dict):
        return result
    return {"success": True, "data": result}


async def exec_set_var(step: dict[str, Any], context: Any) -> dict[str, Any]:
    """设置步骤中间变量。

    参数：name, value
    """
    name = step.get("name", "")
    value = step.get("value")
    if not name:
        return {"success": False, "error": "name 参数为空"}

    # value 支持模板变量
    if isinstance(value, str):
        value = context.resolve(value)

    context.set(name, value)
    logger.debug("set_var: {} = {}", name, value)
    return {"success": True, "name": name, "value": value}


async def _acall(obj: Any, method: str, *args: Any) -> Any:
    """安全调用对象方法，兼容同步/异步。"""
    fn = getattr(obj, method, None)
    if fn is None:
        return None
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args)
    return fn(*args)
