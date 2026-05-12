# -*- coding: utf-8 -*-
"""截屏原语：screenshot。"""

from __future__ import annotations

from typing import Any

from loguru import logger


async def exec_screenshot(step: dict[str, Any], context: Any, platform: Any = None) -> dict[str, Any]:
    """截取屏幕并保存证据。

    参数：
        region: 可选区域 {"x":..,"y":..,"w":..,"h":..}
        save_to: 可选保存路径
    """
    region = step.get("region")
    save_to = step.get("save_to")

    logger.debug("screenshot: region={} save_to={}", region, save_to)

    if platform:
        img_data = await _acall(platform, "screenshot")
    else:
        img_data = b""  # 无平台时返回空

    if img_data:
        context.screenshots.append(img_data)
        # 简单估算尺寸（实际由平台提供）
        size_info = "captured"
    else:
        size_info = "empty"

    return {"success": True, "captured": bool(img_data), "size": size_info}


async def _acall(obj: Any, method: str, *args: Any) -> Any:
    """安全调用对象方法，兼容同步/异步。"""
    import asyncio
    fn = getattr(obj, method, None)
    if fn is None:
        return None
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args)
    return fn(*args)
