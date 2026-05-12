# -*- coding: utf-8 -*-
"""键盘原语：key_combo, key_type。"""

from __future__ import annotations

from typing import Any

from loguru import logger


async def exec_key_combo(step: dict[str, Any], context: Any, platform: Any) -> dict[str, Any]:
    """执行组合键。

    参数：
        keys: 组合键字符串，如 "ctrl+s", "alt+f4", "f12"

    Returns:
        {"success": bool, "keys": str}
    """
    keys = step.get("keys", "")
    if not keys:
        return {"success": False, "error": "keys 参数为空"}

    keys = context.resolve(keys)
    logger.debug("key_combo: {}", keys)

    if platform:
        await _call(platform, "key_combo", keys)

    return {"success": True, "keys": keys}


async def exec_key_type(step: dict[str, Any], context: Any, platform: Any) -> dict[str, Any]:
    """执行单键输入。

    参数：
        keys: 按键名称，如 "enter", "tab", "escape"

    Returns:
        {"success": bool, "keys": str}
    """
    keys = step.get("keys", "")
    if not keys:
        return {"success": False, "error": "keys 参数为空"}

    keys = context.resolve(keys)
    logger.debug("key_type: {}", keys)

    if platform:
        await _call(platform, "type_key", keys)

    return {"success": True, "keys": keys}


async def _call(obj: Any, method: str, *args: Any) -> Any:
    """安全调用对象方法，兼容同步/异步。"""
    import asyncio
    fn = getattr(obj, method, None)
    if fn is None:
        return None
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args)
    return fn(*args)
