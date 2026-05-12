# -*- coding: utf-8 -*-
"""原语（Atomic Actions）注册表与包导出。

所有 action 执行函数统一注册到 ACTION_REGISTRY，
供 StepExecutor 查找调用。
"""

from __future__ import annotations

from typing import Any, Callable

# 延迟导入避免循环依赖
def _import_keyboard():
    from src.skills.actions.keyboard import exec_key_combo, exec_key_type
    return {"key_combo": exec_key_combo, "key_type": exec_key_type}

def _import_mouse():
    from src.skills.actions.mouse import (
        exec_click, exec_double_click, exec_right_click,
        exec_drag, exec_scroll, exec_move_mouse,
    )
    return {
        "click": exec_click,
        "double_click": exec_double_click,
        "right_click": exec_right_click,
        "drag": exec_drag,
        "scroll": exec_scroll,
        "move_mouse": exec_move_mouse,
    }

def _import_text():
    from src.skills.actions.text import exec_type_text, exec_click_text
    return {"type_text": exec_type_text, "click_text": exec_click_text}

def _import_vision():
    from src.skills.actions.vision import exec_click_icon, exec_assert_text, exec_assert_screen
    return {"click_icon": exec_click_icon, "assert_text": exec_assert_text, "assert_screen": exec_assert_screen}

def _import_control():
    from src.skills.actions.control import (
        exec_wait, exec_wait_text, exec_condition, exec_loop, exec_run_skill, exec_set_var,
    )
    return {
        "wait": exec_wait,
        "wait_text": exec_wait_text,
        "condition": exec_condition,
        "loop": exec_loop,
        "run_skill": exec_run_skill,
        "set_var": exec_set_var,
    }

def _import_screen():
    from src.skills.actions.screen import exec_screenshot
    return {"screenshot": exec_screenshot}

# 合并所有 action 到注册表
def _build_registry() -> dict[str, Callable]:
    registry = {}
    for importer in (_import_keyboard, _import_mouse, _import_text,
                     _import_vision, _import_control, _import_screen):
        registry.update(importer())
    return registry

ACTION_REGISTRY: dict[str, Callable] = {}

def get_action_registry() -> dict[str, Callable]:
    """获取 action 注册表（懒加载）。"""
    if not ACTION_REGISTRY:
        ACTION_REGISTRY.update(_build_registry())
    return ACTION_REGISTRY
