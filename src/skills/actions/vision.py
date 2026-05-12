# -*- coding: utf-8 -*-
"""视觉原语：click_icon, assert_text, assert_screen。"""

from __future__ import annotations

from typing import Any

from loguru import logger


async def exec_click_icon(step: dict[str, Any], context: Any, platform: Any, perception: Any = None) -> dict[str, Any]:
    """视觉找图标后点击其中心。

    参数：
        description: 图标描述（如"保存按钮"）
        timeout: 超时秒数（默认 5）
    """
    description = step.get("description", "")
    if not description:
        return {"success": False, "error": "description 参数为空"}

    description = context.resolve(description)
    timeout = float(step.get("timeout", 5.0))
    logger.debug("click_icon: '{}' timeout={}", description, timeout)

    if not perception:
        return {"success": False, "error": "perception 未提供"}

    bbox = await _acall(perception, "find_object", description)
    if bbox is None:
        return {"success": False, "error": f"未找到图标: {description}"}

    # bbox: [x1, y1, x2, y2] → 取中心
    cx = (bbox[0] + bbox[2]) // 2
    cy = (bbox[1] + bbox[3]) // 2

    if platform:
        await _acall(platform, "click", cx, cy)

    return {"success": True, "description": description, "x": cx, "y": cy}


async def exec_assert_text(step: dict[str, Any], context: Any, perception: Any = None) -> dict[str, Any]:
    """断言屏幕上存在指定文字。

    参数：
        text: 要断言的文字（支持 | 分隔多个匹配）
        timeout: 超时秒数（默认 3）
    """
    text = step.get("text", "")
    if not text:
        return {"success": True, "passed": True, "found": ""}

    text = context.resolve(text)
    timeout = float(step.get("timeout", 3.0))
    targets = [t.strip() for t in text.split("|") if t.strip()]

    logger.debug("assert_text: '{}' targets={}", text, targets)

    if not perception:
        return {"success": True, "passed": False, "found": ""}

    screen_text = await _acall(perception, "get_screen_text")
    if screen_text is None:
        screen_text = ""

    for target in targets:
        if target in screen_text:
            return {"success": True, "passed": True, "found": target}

    return {"success": True, "passed": False, "found": ""}


async def exec_assert_screen(step: dict[str, Any], context: Any, platform: Any = None) -> dict[str, Any]:
    """断言屏幕发生变化。

    截取当前屏幕与上一步截图对比。
    参数：
        min_change: 最小变化比例（默认 0.01，即 1%）
    """
    min_change = float(step.get("min_change", 0.01))
    logger.debug("assert_screen: min_change={}", min_change)

    if not platform:
        return {"success": True, "passed": True, "change_ratio": 1.0}

    current = await _acall(platform, "screenshot")
    if not current:
        return {"success": True, "passed": True, "change_ratio": 1.0}

    if not context.screenshots:
        context.screenshots.append(current)
        return {"success": True, "passed": True, "change_ratio": 1.0}

    previous = context.screenshots[-1]
    change = _compute_change(previous, current)
    context.screenshots.append(current)

    passed = change >= min_change
    return {"success": True, "passed": passed, "change_ratio": round(change, 4)}


def _compute_change(img_a: bytes, img_b: bytes) -> float:
    """计算两张图片的像素差异率（简单字节比较）。"""
    if not img_a or not img_b:
        return 1.0
    min_len = min(len(img_a), len(img_b))
    if min_len == 0:
        return 1.0
    diff_count = sum(1 for i in range(min_len) if img_a[i] != img_b[i])
    return diff_count / min_len


async def _acall(obj: Any, method: str, *args: Any) -> Any:
    """安全调用对象方法，兼容同步/异步。"""
    import asyncio
    fn = getattr(obj, method, None)
    if fn is None:
        return None
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args)
    return fn(*args)
