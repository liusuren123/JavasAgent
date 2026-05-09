"""插件管理器 — 动态加载、卸载、配置外部技能插件。

支持从本地路径或 Git URL 安装插件，自动校验 plugin.yaml 格式，
注册到 TOOL_REGISTRY，以及热重载、启用/禁用等操作。

插件目录结构::

    plugins/
    └── my_plugin/
        ├── plugin.yaml      # 元数据（id, name, version, ...）
        └── main.py          # 入口模块

plugin.yaml 格式::

    id: my_plugin
    name: 我的插件
    version: "1.0.0"
    description: "一个示例插件"
    entry_point: main.py
    dependencies: []

实际的验证逻辑委托给 plugin_validator，加载逻辑委托给 plugin_loader。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from src.tools.plugin_loader import (
    clone_from_git,
    copy_from_local,
    load_module,
    unload_module,
)
from src.tools.plugin_models import (
    PluginInfo,
    PluginManifest,
    PluginState,
)
from src.tools.plugin_validator import (
    check_dependencies,
    check_dependencies_enabled,
    parse_manifest,
)


class PluginManager:
    """插件管理器。

    操作入口:
    - install_plugin / uninstall_plugin — 安装/卸载
    - list_plugins / get_plugin_info — 查询
    - enable_plugin / disable_plugin — 启用/禁用
    - reload_plugin — 热重载

    Usage::

        mgr = PluginManager(plugins_dir="plugins")
        await mgr.execute("install_plugin", {"source": "/path/to/plugin"})
        await mgr.execute("enable_plugin", {"plugin_id": "my_plugin"})
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._plugins: dict[str, PluginInfo] = {}

        plugins_dir = self._config.get("plugins_dir", "plugins")
        self._plugins_dir = Path(plugins_dir)

        data_dir = self._config.get("data_dir", "data")
        self._state_file = Path(data_dir) / "plugin_state.json"

        self._actions: dict[str, Any] = {
            "install_plugin": self._install_plugin,
            "uninstall_plugin": self._uninstall_plugin,
            "list_plugins": self._list_plugins,
            "enable_plugin": self._enable_plugin,
            "disable_plugin": self._disable_plugin,
            "reload_plugin": self._reload_plugin,
            "get_plugin_info": self._get_plugin_info,
        }

        self._load_state()

    # ------------------------------------------------------------------
    # 统一入口
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行插件管理器操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            包含 success 和 data/error 的结果字典
        """
        handler = self._actions.get(action)
        if handler is None:
            logger.error(f"未知操作: {action}")
            return {
                "success": False,
                "error": f"未知操作: {action}，支持: {', '.join(sorted(self._actions.keys()))}",
            }
        try:
            return await handler(params)
        except Exception as e:
            logger.error(f"插件管理器操作失败 [{action}]: {e}")
            return {"success": False, "error": f"操作失败: {e}"}

    # ------------------------------------------------------------------
    # 安装插件
    # ------------------------------------------------------------------

    async def _install_plugin(self, params: dict[str, Any]) -> dict[str, Any]:
        """安装插件。需要 source（本地路径或 Git URL）。"""
        source = params.get("source")
        if not source:
            return {"success": False, "error": "缺少参数: source"}

        plugin_id = params.get("plugin_id")

        # 判断来源类型
        if source.startswith(("http://", "https://")) and source.endswith(".git"):
            target_dir = await clone_from_git(source, self._plugins_dir, plugin_id)
        elif Path(source).exists():
            target_dir = await copy_from_local(source, self._plugins_dir)
        else:
            return {"success": False, "error": f"无效的安装源: {source}"}

        if target_dir is None:
            return {"success": False, "error": "安装失败: 无法准备插件目录"}

        # 校验 plugin.yaml
        manifest_path = target_dir / "plugin.yaml"
        if not manifest_path.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"success": False, "error": "安装失败: 插件缺少 plugin.yaml"}

        manifest, errors = parse_manifest(manifest_path)
        if manifest is None:
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"success": False, "error": f"plugin.yaml 校验失败: {'; '.join(errors)}"}

        # 如果目录名与 plugin id 不一致，重命名
        actual_dir = target_dir
        if target_dir.name != manifest.id:
            renamed = target_dir.parent / manifest.id
            if renamed.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
                return {"success": False, "error": f"插件 ID '{manifest.id}' 已存在目录"}
            target_dir.rename(renamed)
            actual_dir = renamed

        # 检查依赖
        missing = check_dependencies(manifest, self._plugins)
        if missing:
            logger.warning(f"插件 '{manifest.id}' 缺少依赖: {missing}")

        # 创建 PluginInfo
        info = PluginInfo.from_manifest(
            manifest,
            install_path=str(actual_dir),
            state=PluginState.INSTALLED,
        )

        # 如果已存在同 ID 插件，先卸载旧的
        if manifest.id in self._plugins:
            logger.info(f"覆盖安装插件: {manifest.id}")
            old_info = self._plugins[manifest.id]
            if old_info.loaded_module is not None:
                unload_module(old_info)

        self._plugins[manifest.id] = info
        self._save_state()
        logger.info(f"安装插件成功: {manifest.id} v{manifest.version}")
        return {"success": True, "data": info.to_dict()}

    # ------------------------------------------------------------------
    # 卸载插件
    # ------------------------------------------------------------------

    async def _uninstall_plugin(self, params: dict[str, Any]) -> dict[str, Any]:
        """卸载插件。需要 plugin_id。"""
        plugin_id = params.get("plugin_id")
        if not plugin_id:
            return {"success": False, "error": "缺少参数: plugin_id"}
        if plugin_id not in self._plugins:
            return {"success": False, "error": f"插件不存在: {plugin_id}"}

        info = self._plugins[plugin_id]

        # 卸载模块
        if info.loaded_module is not None:
            unload_module(info)

        # 删除文件
        if info.install_path and Path(info.install_path).exists():
            shutil.rmtree(info.install_path, ignore_errors=True)
            logger.debug(f"已删除插件目录: {info.install_path}")

        del self._plugins[plugin_id]
        self._save_state()
        logger.info(f"卸载插件: {plugin_id}")
        return {"success": True, "data": {"uninstalled_plugin_id": plugin_id}}

    # ------------------------------------------------------------------
    # 列出插件
    # ------------------------------------------------------------------

    async def _list_plugins(self, params: dict[str, Any]) -> dict[str, Any]:
        """列出所有已安装插件。"""
        state_filter = params.get("state")
        plugins = list(self._plugins.values())
        if state_filter:
            plugins = [p for p in plugins if p.state.value == state_filter]
        return {
            "success": True,
            "data": {
                "plugins": [p.to_dict() for p in plugins],
                "count": len(plugins),
            },
        }

    # ------------------------------------------------------------------
    # 启用插件
    # ------------------------------------------------------------------

    async def _enable_plugin(self, params: dict[str, Any]) -> dict[str, Any]:
        """启用插件。需要 plugin_id。"""
        plugin_id = params.get("plugin_id")
        if not plugin_id:
            return {"success": False, "error": "缺少参数: plugin_id"}
        if plugin_id not in self._plugins:
            return {"success": False, "error": f"插件不存在: {plugin_id}"}

        info = self._plugins[plugin_id]
        if info.state == PluginState.ENABLED:
            return {"success": True, "data": info.to_dict()}

        # 检查依赖是否全部已启用
        missing = check_dependencies_enabled(info.manifest, self._plugins)
        if missing:
            return {"success": False, "error": f"依赖插件未启用: {', '.join(missing)}"}

        # 加载模块
        try:
            module = load_module(info)
            info.loaded_module = module
            info.state = PluginState.ENABLED
            info.error_message = ""
        except Exception as e:
            info.state = PluginState.ERROR
            info.error_message = str(e)
            logger.error(f"启用插件失败 [{plugin_id}]: {e}")
            self._save_state()
            return {"success": False, "error": f"加载插件模块失败: {e}"}

        self._save_state()
        logger.info(f"启用插件: {plugin_id}")
        return {"success": True, "data": info.to_dict()}

    # ------------------------------------------------------------------
    # 禁用插件
    # ------------------------------------------------------------------

    async def _disable_plugin(self, params: dict[str, Any]) -> dict[str, Any]:
        """禁用插件。需要 plugin_id。"""
        plugin_id = params.get("plugin_id")
        if not plugin_id:
            return {"success": False, "error": "缺少参数: plugin_id"}
        if plugin_id not in self._plugins:
            return {"success": False, "error": f"插件不存在: {plugin_id}"}

        info = self._plugins[plugin_id]
        if info.loaded_module is not None:
            unload_module(info)
        info.state = PluginState.DISABLED
        info.error_message = ""
        self._save_state()
        logger.info(f"禁用插件: {plugin_id}")
        return {"success": True, "data": info.to_dict()}

    # ------------------------------------------------------------------
    # 热重载插件
    # ------------------------------------------------------------------

    async def _reload_plugin(self, params: dict[str, Any]) -> dict[str, Any]:
        """热重载插件代码。需要 plugin_id。"""
        plugin_id = params.get("plugin_id")
        if not plugin_id:
            return {"success": False, "error": "缺少参数: plugin_id"}
        if plugin_id not in self._plugins:
            return {"success": False, "error": f"插件不存在: {plugin_id}"}

        info = self._plugins[plugin_id]

        # 卸载旧模块
        if info.loaded_module is not None:
            unload_module(info)

        # 重新解析 manifest
        manifest_path = Path(info.install_path) / "plugin.yaml"
        if manifest_path.exists():
            manifest, errors = parse_manifest(manifest_path)
            if manifest is not None:
                info.manifest = manifest
            else:
                logger.warning(f"重载时 manifest 解析失败: {errors}")

        # 重新加载模块
        try:
            module = load_module(info)
            info.loaded_module = module
            info.state = PluginState.ENABLED
            info.error_message = ""
        except Exception as e:
            info.state = PluginState.ERROR
            info.error_message = str(e)
            logger.error(f"重载插件失败 [{plugin_id}]: {e}")
            self._save_state()
            return {"success": False, "error": f"重载失败: {e}"}

        self._save_state()
        logger.info(f"热重载插件: {plugin_id}")
        return {"success": True, "data": info.to_dict()}

    # ------------------------------------------------------------------
    # 获取插件信息
    # ------------------------------------------------------------------

    async def _get_plugin_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取插件元数据。需要 plugin_id。"""
        plugin_id = params.get("plugin_id")
        if not plugin_id:
            return {"success": False, "error": "缺少参数: plugin_id"}
        if plugin_id not in self._plugins:
            return {"success": False, "error": f"插件不存在: {plugin_id}"}

        info = self._plugins[plugin_id]
        return {"success": True, "data": info.to_dict(include_module=True)}

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """保存插件状态到 JSON 文件。"""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "plugins": {
                    pid: p.to_dict() for pid, p in self._plugins.items()
                }
            }
            tmp = self._state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._state_file)
        except Exception as e:
            logger.error(f"保存插件状态失败: {e}")

    def _load_state(self) -> None:
        """从 JSON 文件恢复插件状态（仅恢复元信息，不重新加载模块）。"""
        if not self._state_file.exists():
            return
        try:
            raw = self._state_file.read_text(encoding="utf-8")
            data = json.loads(raw)

            for pid, p_data in data.get("plugins", {}).items():
                manifest_data = p_data.get("manifest", {})
                if not manifest_data.get("id"):
                    continue
                manifest = PluginManifest.from_dict(manifest_data)
                state_str = p_data.get("state", "installed")
                try:
                    state = PluginState(state_str)
                except ValueError:
                    state = PluginState.INSTALLED

                install_time = p_data.get("install_time")
                if isinstance(install_time, str):
                    install_time = datetime.fromisoformat(install_time)

                info = PluginInfo(
                    plugin_id=pid,
                    manifest=manifest,
                    state=state,
                    install_path=p_data.get("install_path", ""),
                    install_time=install_time,
                    error_message=p_data.get("error_message", ""),
                )
                # 已启用的插件需要重新加载模块
                if state == PluginState.ENABLED:
                    try:
                        module = load_module(info)
                        info.loaded_module = module
                    except Exception as e:
                        info.state = PluginState.ERROR
                        info.error_message = f"重新加载失败: {e}"
                        logger.warning(f"重新加载插件模块失败 [{pid}]: {e}")

                self._plugins[pid] = info

            logger.info(f"已恢复 {len(self._plugins)} 个插件状态")
        except Exception as e:
            logger.error(f"加载插件状态失败: {e}")
