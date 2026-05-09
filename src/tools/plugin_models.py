"""PluginManager 数据模型。

定义插件管理器使用的所有数据结构，包括插件状态枚举、
插件清单模型（对应 plugin.yaml）、插件运行时信息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class PluginState(str, Enum):
    """插件运行时状态。"""

    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class PluginManifest:
    """插件清单模型（对应 plugin.yaml）。

    Attributes:
        id: 插件唯一标识，如 "weather_tool"
        name: 插件显示名称
        version: 语义化版本号，如 "1.0.0"
        description: 插件描述
        entry_point: 入口模块路径，如 "main.py" 或 "weather.plugin"
        dependencies: 依赖的其他插件 ID 列表
        author: 作者
        tags: 标签列表
        extra: 扩展字段
    """

    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    entry_point: str = "main.py"
    dependencies: list[str] = field(default_factory=list)
    author: str = ""
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "entry_point": self.entry_point,
            "dependencies": self.dependencies,
            "author": self.author,
            "tags": self.tags,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginManifest:
        """从字典创建实例（忽略多余字段）。"""
        return cls(
            id=data["id"],
            name=data["name"],
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            entry_point=data.get("entry_point", "main.py"),
            dependencies=data.get("dependencies", []),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            extra=data.get("extra", {}),
        )

    @classmethod
    def validate_dict(cls, data: dict[str, Any]) -> list[str]:
        """校验字典是否符合 PluginManifest 要求。

        Returns:
            错误消息列表，空列表表示校验通过。
        """
        errors: list[str] = []
        if "id" not in data or not isinstance(data["id"], str) or not data["id"].strip():
            errors.append("缺少必填字段 'id'（非空字符串）")
        if "name" not in data or not isinstance(data["name"], str) or not data["name"].strip():
            errors.append("缺少必填字段 'name'（非空字符串）")
        version = data.get("version")
        if version is not None and not isinstance(version, str):
            errors.append("'version' 应为字符串")
        entry_point = data.get("entry_point")
        if entry_point is not None and not isinstance(entry_point, str):
            errors.append("'entry_point' 应为字符串")
        deps = data.get("dependencies")
        if deps is not None:
            if not isinstance(deps, list):
                errors.append("'dependencies' 应为列表")
            elif not all(isinstance(d, str) for d in deps):
                errors.append("'dependencies' 列表中的每个元素应为字符串")
        return errors


@dataclass
class PluginInfo:
    """插件运行时信息。

    Attributes:
        plugin_id: 插件唯一标识
        manifest: 插件清单
        state: 当前状态
        install_path: 安装路径
        install_time: 安装时间
        loaded_module: 已加载的模块（运行时引用，不序列化）
        error_message: 错误信息（state == ERROR 时有值）
    """

    plugin_id: str
    manifest: PluginManifest
    state: PluginState = PluginState.INSTALLED
    install_path: str = ""
    install_time: datetime | None = None
    loaded_module: Any = None
    error_message: str = ""

    def to_dict(self, *, include_module: bool = False) -> dict[str, Any]:
        """转换为可序列化字典。

        Args:
            include_module: 是否包含已加载模块信息（默认不包含）。
        """
        result: dict[str, Any] = {
            "plugin_id": self.plugin_id,
            "manifest": self.manifest.to_dict(),
            "state": self.state.value,
            "install_path": self.install_path,
            "install_time": self.install_time.isoformat() if self.install_time else None,
            "error_message": self.error_message,
        }
        if include_module and self.loaded_module is not None:
            result["module"] = str(self.loaded_module)
        return result

    @classmethod
    def from_manifest(
        cls,
        manifest: PluginManifest,
        install_path: str = "",
        state: PluginState = PluginState.INSTALLED,
    ) -> PluginInfo:
        """从清单创建 PluginInfo 实例。"""
        return cls(
            plugin_id=manifest.id,
            manifest=manifest,
            state=state,
            install_path=install_path,
            install_time=datetime.now(),
        )
