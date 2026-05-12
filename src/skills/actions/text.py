# -*- coding: utf-8 -*-
"""文字原语：type_text, click_text。"""

from __future__ import annotations

from typing import Any

from loguru import logger


async def exec_type_text(step: dict[str, Any], context: Any, platform: Any, humanhand: Any = None) -> dict[str, Any]:
    """拟人打字。

    参数：
        text: 要输入的文字（支持模板变量）
        speed: 打字速度 "fast" / "normal" / "slow"
    """
    text = step.get("text", "")
    if not text:
        return {"success": False, "error": "text 参数为空"}

    text = context.resolve(text)
    speed = step.get("speed", "normal")
    logger.debug("type_text: '{}' (speed={})", text[:50], speed)

    if humanhand:
        await _acall(humanhand, "type_text", text, speed)
    elif platform:
        await _acall(platform, "type_text", text)

    return {"success": True, "text": text, "speed": speed}


async def exec_click_text(step: dict[str, Any], context: Any, platform: Any, perception: Any = None) -> dict[str, Any]:
    """OCR 找文字后点击。

    参数：
        text: 要查找的文字
        timeout: 超时秒数（默认 3）
        offset_x: X 偏移（默认 0）
        offset_y: Y 偏移（默认 0）
    """
    text = step.get("text", "")
    if not text:
        return {"success": False, "error": "text 参数为空"}

    text = context.resolve(text)
    timeout = float(step.get("timeout", 3.0))
    offset_x = int(step.get("offset_x", 0))
    offset_y = int(step.get("offset_y", 0))

    logger.debug("click_text: '{}' timeout={} offset=({},{})", text, timeout, offset_x, offset_y)

    if not perception:
        return {"success": False, "error": "perception 未提供"}

    # OCR 查找文字坐标
    pos = await _acall(perception, "find_text", text)
    if pos is None:
        return {"success": False, "error": f"未找到文字: {text}"}

    x, y = pos
    click_x = x + offset_x
    click_y = y + offset_y

    if platform:
        await _acall(platform, "click", click_x, click_y)

    return {"success": True, "text": text, "x": click_x, "y": click_y}


async def _acall(obj: Any, method: str, *args: Any) -> Any:
    """安全调用对象方法，兼容同步/异步。"""
    import asyncio
    fn = getattr(obj, method, None)
    if fn is None:
        return None
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args)
    return fn(*args)
