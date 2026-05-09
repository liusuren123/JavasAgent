"""After Effects COM 连接与工具核心。

提供 AfterEffectsControl 主类、COM 连接管理、统一 execute 入口、
路径安全工具和项目内辅助方法。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.path_safety import PathSafetyError, safe_resolve_path

_RENDER_PRESETS: dict[str, str] = {
    "h264": "H.264",
    "lossless": "Lossless",
    "prores": "Apple ProRes 422",
    "png_sequence": "PNG Sequence",
    "tiff_sequence": "TIFF Sequence",
    "webm": "WebM",
}


class AfterEffectsControl:
    """After Effects 脚本控制工具。

    通过 COM 接口控制 After Effects。如果 After Effects 未安装或未运行，
    所有操作将返回友好的错误提示，不会导致 agent 崩溃。

    Usage::

        ae = AfterEffectsControl(workspace="/path/to/workspace")
        result = await ae.execute("list_projects", {})
        result = await ae.execute("get_active_composition", {})
    """

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = Path(workspace) if workspace else Path.cwd()
        self._app: Any = None
        self._connected = False

    # ------------------------------------------------------------------
    # COM 连接管理
    # ------------------------------------------------------------------

    def _get_app(self) -> Any:
        """获取 After Effects COM 对象，支持延迟连接和缓存。

        Raises:
            RuntimeError: After Effects 不可用（未安装/未运行）
        """
        if self._connected and self._app is not None:
            return self._app

        if sys.platform != "win32":
            raise RuntimeError("After Effects 控制仅支持 Windows 平台。")

        try:
            import win32com.client
        except ImportError:
            raise RuntimeError("pywin32 未安装，请运行: pip install pywin32") from None

        try:
            app = win32com.client.GetActiveObject("AfterEffects.Application")
            self._app = app
            self._connected = True
            logger.info("已连接到 After Effects COM 对象")
            return app
        except Exception as e:
            self._connected = False
            logger.warning(f"无法连接 After Effects: {e}")
            raise RuntimeError(
                "无法连接到 After Effects。请确保 After Effects 已安装并正在运行。"
            ) from e

    def _ensure_connected(self) -> Any:
        """确保已连接到 After Effects，返回 COM 对象或抛出异常。"""
        return self._get_app()

    # ------------------------------------------------------------------
    # 统一入口
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行 After Effects 操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            操作结果字典
        """
        # 延迟导入避免循环依赖
        from src.tools.aftereffects_operations import (
            _add_solid_layer,
            _add_text_layer,
            _export_frame,
            _get_active_composition,
            _import_file,
            _list_layers,
            _list_projects,
            _render_composition,
            _set_layer_property,
        )

        handlers: dict[str, Any] = {
            "list_projects": _list_projects,
            "get_active_composition": _get_active_composition,
            "list_layers": _list_layers,
            "add_text_layer": _add_text_layer,
            "add_solid_layer": _add_solid_layer,
            "set_layer_property": _set_layer_property,
            "render_composition": _render_composition,
            "import_file": _import_file,
            "export_frame": _export_frame,
        }

        handler = handlers.get(action)
        if handler is None:
            logger.error(f"未知的 After Effects 操作: {action}")
            return {
                "error": f"未知操作: {action}",
                "available_actions": sorted(handlers.keys()),
            }

        logger.debug(f"After Effects 操作: {action}, 参数: {params}")
        return await handler(self, params)

    # ------------------------------------------------------------------
    # 路径安全
    # ------------------------------------------------------------------

    def _safe_path(self, user_path: str, *, allow_create_parents: bool = False) -> Path:
        """安全解析用户路径，防止路径遍历。"""
        return safe_resolve_path(
            self._workspace, user_path, allow_create_parents=allow_create_parents,
        )

    def _safe_path_or_absolute(self, user_path: str) -> Path:
        """解析路径：先尝试 workspace 内路径，不存在则尝试绝对路径。"""
        try:
            p = self._safe_path(user_path)
            if p.exists():
                return p
        except PathSafetyError:
            pass
        abs_path = Path(user_path).resolve()
        if abs_path.exists():
            return abs_path
        return self._safe_path(user_path)

    # ------------------------------------------------------------------
    # 项目内辅助
    # ------------------------------------------------------------------

    def _resolve_composition(self, app: Any, composition_name: str | None) -> Any:
        """解析目标合成对象。返回合成 COM 对象或错误字典。"""
        if composition_name:
            try:
                proj = app.Project
                if proj is None:
                    return {"error": "当前没有打开的项目"}
                items = proj.Items
                for i in range(1, items.Count + 1):
                    item = items[i]
                    if (
                        getattr(item, "TypeName", "") == "Composition"
                        and getattr(item, "Name", "") == composition_name
                    ):
                        return item
                available = [
                    getattr(items[j], "Name", f"Item {j}")
                    for j in range(1, items.Count + 1)
                    if getattr(items[j], "TypeName", "") == "Composition"
                ]
                return {"error": f"未找到合成: {composition_name}", "available_compositions": available}
            except Exception as e:
                return {"error": f"查找合成失败: {e}"}

        # 使用当前活动合成
        try:
            comp = app.ActiveItem
            if comp is not None and getattr(comp, "TypeName", "") == "Composition":
                return comp
        except Exception:
            pass

        # 从项目中获取第一个合成
        try:
            proj = app.Project
            if proj is None:
                return {"error": "当前没有打开的项目，也没有活动的合成"}
            items = proj.Items
            for i in range(1, items.Count + 1):
                item = items[i]
                if getattr(item, "TypeName", "") == "Composition":
                    return item
            return {"error": "项目中没有合成"}
        except Exception as e:
            return {"error": f"获取合成失败: {e}"}

    @staticmethod
    def _get_layer_type(layer: Any) -> str:
        """判断图层类型。"""
        try:
            if hasattr(layer, "Text"):
                return "text"
        except Exception:
            pass
        try:
            source = getattr(layer, "Source", None)
            if source is not None:
                type_name = getattr(source, "TypeName", "")
                for keyword, label in [
                    ("Footage", "footage"), ("Solid", "solid"),
                    ("Composition", "precomposition"), ("Audio", "audio"),
                ]:
                    if keyword in type_name:
                        return label
        except Exception:
            pass
        for attr, label in [("AdjustmentLayer", "adjustment"), ("NullLayer", "null"), ("Camera", "camera"), ("Light", "light")]:
            try:
                if hasattr(layer, attr):
                    return label
            except Exception:
                pass
        return "unknown"

    @staticmethod
    def _get_layer_property(layer: Any, property_name: str) -> Any | None:
        """根据属性名获取图层属性对象。"""
        prop_map = {
            "position": "Position", "scale": "Scale",
            "rotation": "Rotation", "opacity": "Opacity",
            "anchor_point": "AnchorPoint",
        }
        ae_name = prop_map.get(property_name.lower().replace(" ", "_"))
        if not ae_name:
            return None
        for accessor in (lambda: getattr(layer.Property, ae_name), lambda: getattr(layer, ae_name)):
            try:
                prop = accessor()
                if prop is not None:
                    return prop
            except Exception:
                pass
        return None
