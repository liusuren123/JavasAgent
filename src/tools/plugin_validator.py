"""插件验证与安全检查。

提供 plugin.yaml 解析校验、依赖关系检查等功能。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from loguru import logger

from src.tools.plugin_models import (
    PluginInfo,
    PluginManifest,
    PluginState,
)

if TYPE_CHECKING:
    pass


# ------------------------------------------------------------------
# manifest 解析
# ------------------------------------------------------------------


def parse_manifest(path: Path) -> tuple[PluginManifest | None, list[str]]:
    """解析 plugin.yaml，返回 (manifest, errors)。

    Args:
        path: plugin.yaml 文件路径

    Returns:
        元组 (解析后的 manifest 对象, 错误列表)。
        manifest 为 None 表示校验失败。
    """
    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except Exception as e:
        return None, [f"读取或解析 YAML 失败: {e}"]

    if not isinstance(data, dict):
        return None, ["plugin.yaml 根元素应为字典"]

    errors = PluginManifest.validate_dict(data)
    if errors:
        return None, errors

    manifest = PluginManifest.from_dict(data)
    return manifest, []


# ------------------------------------------------------------------
# 依赖检查
# ------------------------------------------------------------------


def check_dependencies(
    manifest: PluginManifest,
    plugins: dict[str, PluginInfo],
) -> list[str]:
    """检查插件依赖是否已安装。

    Args:
        manifest: 插件清单
        plugins: 当前已安装的插件字典

    Returns:
        缺失的依赖 ID 列表。
    """
    missing: list[str] = []
    for dep_id in manifest.dependencies:
        if dep_id not in plugins:
            missing.append(dep_id)
    return missing


def check_dependencies_enabled(
    manifest: PluginManifest,
    plugins: dict[str, PluginInfo],
) -> list[str]:
    """检查插件依赖是否已启用。

    Args:
        manifest: 插件清单
        plugins: 当前已安装的插件字典

    Returns:
        未启用的依赖 ID 列表。
    """
    not_enabled: list[str] = []
    for dep_id in manifest.dependencies:
        if dep_id not in plugins:
            not_enabled.append(dep_id)
        elif plugins[dep_id].state != PluginState.ENABLED:
            not_enabled.append(dep_id)
    return not_enabled
