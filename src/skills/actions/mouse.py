# -*- coding: utf-8 -*-
"""鼠标原语：click, double_click, right_click, drag, scroll, move_mouse。"""

from __future__ import annotations

from typing import Any

from loguru import logger


async def exec_click(step: dict[str, Any], context: Any, platform: Any) -> dict[str, Any]:
    """点击指定坐标。

    参数：x, y（支持模板变量）
    """
    x = _resolve_num(step, "x", context)
    y = _resolve_num(step, "y", context)
    logger.debug("click: ({}, {})", x, y)
    if platform:
        await _pcall(platform, "click", x, y)
    return {"success": True, "x": x, "y": y}


async def exec_double_click(step: dict[str, Any], context: Any, platform: Any) -> dict[str, Any]:
    """双击指定坐标。"""
    x = _resolve_num(step, "x", context)
    y = _resolve_num(step, "y", context)
    logger.debug("double_click: ({}, {})", x, y)
    if platform:
        await _pcall(platform, "double_click", x, y)
    return {"success": True, "x": x, "y": y}


async def exec_right_click(step: dict[str, Any], context: Any, platform: Any) -> dict[str, Any]:
    """右键点击指定坐标。"""
    x = _resolve_num(step, "x", context)
    y = _resolve_num(step, "y", context)
    logger.debug("right_click: ({}, {})", x, y)
    if platform:
        await _pcall(platform, "right_click", x, y)
    return {"success": True, "x": x, "y": y}


async def exec_drag(step: dict[str, Any], context: Any, platform: Any) -> dict[str, Any]:
    """从 start 拖拽到 end。

    参数：start_x, start_y, end_x, end_y
    """
    sx = _resolve_num(step, "start_x", context)
    sy = _resolve_num(step, "start_y", context)
    ex = _resolve_num(step, "end_x", context)
    ey = _resolve_num(step, "end_y", context)
    logger.debug("drag: ({},{}) -> ({},{})", sx, sy, ex, ey)
    if platform:
        await _pcall(platform, "drag", sx, sy, ex, ey)
    return {"success": True, "start": [sx, sy], "end": [ex, ey]}


async def exec_scroll(step: dict[str, Any], context: Any, platform: Any) -> dict[str, Any]:
    """滚轮滚动。

    参数：amount（正数向上，负数向下）
    """
    amount = step.get("amount", 3)
    if isinstance(amount, str):
        amount = int(context.resolve(amount))
    logger.debug("scroll: {}", amount)
    if platform:
        await _pcall(platform, "scroll", amount)
    return {"success": True, "amount": amount}


async def exec_move_mouse(step: dict[str, Any], context: Any, platform: Any) -> dict[str, Any]:
    """移动鼠标到指定坐标。"""
    x = _resolve_num(step, "x", context)
    y = _resolve_num(step, "y", context)
    logger.debug("move_mouse: ({}, {})", x, y)
    if platform:
        await _pcall(platform, "move_to", x, y)
    return {"success": True, "x": x, "y": y}


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def _resolve_num(step: dict, key: str, context: Any) -> int | float:
    """从 step 中解析数值参数，支持模板变量。"""
    val = step.get(key, 0)
    if isinstance(val, str):
        resolved = context.resolve(val)
        try:
            return int(resolved) if "." not in str(resolved) else float(resolved)
        except (ValueError, TypeError):
            return 0
    return val


async def _pcall(obj: Any, method: str, *args: Any) -> Any:
    """安全调用 platform 方法，兼容同步/异步。"""
    import asyncio
    fn = getattr(obj, method, None)
    if fn is None:
        return None
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args)
    return fn(*args)
