"""Photoshop 脚本控制工具。

通过 Windows COM 接口 (win32com) 驱动 Photoshop，提供图像编辑、
滤镜、图层操作、导出等能力。仅在 Windows 上可用。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.path_safety import PathSafetyError, safe_resolve_path

_EXPORT_FORMATS: dict[str, str] = {
    "png": "pngFormat", "jpeg": "jpegFormat", "jpg": "jpegFormat",
    "pdf": "pdfFormat", "psd": "photoshopFormat", "tiff": "tiffFormat",
    "bmp": "bmpFormat", "gif": "compuservegifFormat",
}

_COLOR_MODE_MAP: dict[str, int] = {
    "bitmap": 1, "grayscale": 2, "duotone": 3, "indexed": 4,
    "rgb": 5, "cmyk": 6, "lab": 7, "multichannel": 8,
}
_COLOR_MODE_NAMES = {v: k for k, v in _COLOR_MODE_MAP.items()}


class PhotoshopControl:
    """Photoshop 脚本控制工具。

    通过 COM 接口控制 Photoshop。如果 Photoshop 未安装或未运行，
    所有操作将返回友好的错误提示，不会导致 agent 崩溃。

    Usage::

        ps = PhotoshopControl(workspace="/path/to/workspace")
        result = await ps.execute("open_document", {"path": "design.psd"})
        result = await ps.execute("get_document_info", {})
        result = await ps.execute("export_image", {
            "path": "output.png",
            "format": "png",
        })
    """

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = Path(workspace) if workspace else Path.cwd()
        self._app: Any = None
        self._connected = False

    # ------------------------------------------------------------------
    # COM 连接管理
    # ------------------------------------------------------------------

    def _get_app(self) -> Any:
        """获取 Photoshop COM 对象，支持延迟连接和缓存。

        Returns:
            Photoshop Application COM 对象

        Raises:
            RuntimeError: Photoshop 不可用（未安装/未运行）
        """
        if self._connected and self._app is not None:
            return self._app

        if sys.platform != "win32":
            raise RuntimeError(
                "Photoshop 控制仅支持 Windows 平台。"
                "macOS 请使用 AppleScript 方案。"
            )

        try:
            import win32com.client
        except ImportError:
            raise RuntimeError(
                "pywin32 未安装，请运行: pip install pywin32"
            ) from None

        try:
            app = win32com.client.GetActiveObject("Photoshop.Application")
            self._app = app
            self._connected = True
            logger.info("已连接到 Photoshop COM 对象")
            return app
        except Exception as e:
            self._connected = False
            logger.warning(f"无法连接 Photoshop: {e}")
            raise RuntimeError(
                "无法连接到 Photoshop。请确保 Photoshop 已安装并正在运行。"
            ) from e

    def _ensure_connected(self) -> Any:
        """确保已连接到 Photoshop，返回 COM 对象或抛出异常。"""
        return self._get_app()

    # ------------------------------------------------------------------
    # 统一入口
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行 Photoshop 操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            操作结果字典
        """
        handlers: dict[str, Any] = {
            "open_document": self._open_document,
            "save_document": self._save_document,
            "export_image": self._export_image,
            "run_action": self._run_action,
            "apply_filter": self._apply_filter,
            "resize": self._resize,
            "get_document_info": self._get_document_info,
            "close_document": self._close_document,
        }

        handler = handlers.get(action)
        if handler is None:
            logger.error(f"未知的 Photoshop 操作: {action}")
            return {
                "error": f"未知操作: {action}",
                "available_actions": sorted(handlers.keys()),
            }

        logger.debug(f"Photoshop 操作: {action}, 参数: {params}")
        return await handler(params)

    # ------------------------------------------------------------------
    # 路径安全
    # ------------------------------------------------------------------

    def _safe_path(self, user_path: str, *, allow_create_parents: bool = False) -> Path:
        """安全解析用户路径，防止路径遍历。"""
        return safe_resolve_path(
            self._workspace,
            user_path,
            allow_create_parents=allow_create_parents,
        )

    def _safe_path_or_absolute(self, user_path: str) -> Path:
        """解析路径：先尝试安全路径，失败则用绝对路径（用于打开外部文件）。

        对于 open_document 这类可能打开 workspace 外文件的场景，
        先尝试 workspace 内路径，如果不存在则作为绝对路径处理。
        """
        try:
            p = self._safe_path(user_path)
            if p.exists():
                return p
        except PathSafetyError:
            pass

        # 尝试作为绝对路径
        abs_path = Path(user_path).resolve()
        if abs_path.exists():
            return abs_path

        # 路径不存在，仍返回 workspace 内路径（让后续逻辑报错）
        return self._safe_path(user_path)

    # ------------------------------------------------------------------
    # 操作实现
    # ------------------------------------------------------------------

    async def _open_document(self, params: dict[str, Any]) -> dict[str, Any]:
        """打开 PSD/PNG/JPG 文件。"""
        raw_path = params.get("path")
        if not raw_path:
            return {"error": "请指定要打开的文件路径 (path)"}

        try:
            path = self._safe_path_or_absolute(raw_path)
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        try:
            app = self._ensure_connected()
            doc = app.Open(str(path))
            logger.info(f"已打开文档: {doc.Name}")
            return {
                "status": "opened",
                "document_name": doc.Name,
                "path": str(path),
            }
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"打开文档失败: {e}")
            return {"error": f"打开文档失败: {e}"}

    async def _save_document(self, params: dict[str, Any]) -> dict[str, Any]:
        """保存当前文档。可选另存为指定路径。"""
        try:
            app = self._ensure_connected()
            doc = app.ActiveDocument
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"没有打开的文档: {e}"}

        try:
            save_path = params.get("path")
            if save_path:
                try:
                    out_path = self._safe_path(save_path, allow_create_parents=True)
                except PathSafetyError as e:
                    return {"error": str(e)}
                out_path.parent.mkdir(parents=True, exist_ok=True)
                ext = out_path.suffix.lower().lstrip(".")
                save_type = _EXPORT_FORMATS.get(ext)
                if save_type:
                    save_options = self._get_save_options(app, save_type, params)
                    doc.SaveAs(str(out_path), save_options)
                else:
                    doc.SaveAs(str(out_path))
                logger.info(f"已另存为: {out_path}")
                return {"status": "saved", "path": str(out_path)}
            else:
                doc.Save()
                logger.info(f"已保存文档: {doc.Name}")
                return {"status": "saved", "document_name": doc.Name}
        except Exception as e:
            logger.error(f"保存文档失败: {e}")
            return {"error": f"保存文档失败: {e}"}

    async def _export_image(self, params: dict[str, Any]) -> dict[str, Any]:
        """导出为指定格式 (png/jpeg/pdf)。"""
        raw_path = params.get("path")
        fmt = params.get("format", "png").lower()

        if not raw_path:
            return {"error": "请指定导出路径 (path)"}

        if fmt not in _EXPORT_FORMATS:
            return {
                "error": f"不支持的导出格式: {fmt}",
                "supported_formats": sorted(_EXPORT_FORMATS.keys()),
            }

        try:
            out_path = self._safe_path(raw_path, allow_create_parents=True)
        except PathSafetyError as e:
            return {"error": str(e)}

        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            app = self._ensure_connected()
            doc = app.ActiveDocument
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"没有打开的文档: {e}"}

        try:
            save_type = _EXPORT_FORMATS[fmt]
            save_options = self._get_save_options(app, save_type, params)
            doc.SaveAs(str(out_path), save_options)

            logger.info(f"已导出: {out_path} (格式: {fmt})")
            return {
                "status": "exported",
                "path": str(out_path),
                "format": fmt,
            }
        except Exception as e:
            logger.error(f"导出失败: {e}")
            return {"error": f"导出失败: {e}"}

    async def _run_action(self, params: dict[str, Any]) -> dict[str, Any]:
        """执行 Photoshop Action。"""
        action_name = params.get("action_name")
        if not action_name:
            return {"error": "请指定 Action 名称 (action_name)"}

        try:
            app = self._ensure_connected()
        except RuntimeError as e:
            return {"error": str(e)}

        try:
            action_set = params.get("action_set", "")
            desc = app.ActionDescriptor()
            ref = app.ActionReference()

            if action_set:
                ref.PutName(app.charIDToTypeID("ASet"), action_set)
            ref.PutName(app.charIDToTypeID("Actn"), action_name)

            desc.PutReference(app.charIDToTypeID("null"), ref)
            app.ExecuteAction(app.charIDToTypeID("Ply "), desc)

            logger.info(f"已执行 Action: {action_name}")
            return {
                "status": "action_executed",
                "action_name": action_name,
                "action_set": action_set or "(default)",
            }
        except Exception as e:
            logger.error(f"执行 Action 失败: {e}")
            return {"error": f"执行 Action '{action_name}' 失败: {e}"}

    async def _apply_filter(self, params: dict[str, Any]) -> dict[str, Any]:
        """应用滤镜。"""
        filter_name = params.get("filter_name")
        if not filter_name:
            return {"error": "请指定滤镜名称 (filter_name)"}

        try:
            app = self._ensure_connected()
            doc = app.ActiveDocument
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"没有打开的文档: {e}"}

        try:
            # 使用 ActionDescriptor 方式执行滤镜
            # 通过 Photoshop 的脚本监听器获取的 filter ID
            filter_id = self._get_filter_id(filter_name)
            desc = self._build_filter_descriptor(app, filter_name, params)
            app.ExecuteAction(filter_id, desc)

            logger.info(f"已应用滤镜: {filter_name}")
            return {
                "status": "filter_applied",
                "filter_name": filter_name,
            }
        except Exception as e:
            logger.error(f"应用滤镜失败: {e}")
            return {"error": f"应用滤镜 '{filter_name}' 失败: {e}"}

    async def _resize(self, params: dict[str, Any]) -> dict[str, Any]:
        """调整画布/图像尺寸。mode=image/canvas。"""
        width = params.get("width")
        height = params.get("height")

        if width is None or height is None:
            return {"error": "请指定目标宽度和高度 (width, height)"}

        width = int(width)
        height = int(height)
        if width <= 0 or height <= 0:
            return {"error": "宽度和高度必须大于 0"}

        try:
            app = self._ensure_connected()
            doc = app.ActiveDocument
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"没有打开的文档: {e}"}

        mode = params.get("mode", "image")
        try:
            orig_w, orig_h = doc.Width, doc.Height
            desc = app.ActionDescriptor()
            desc.PutUnitDouble(app.charIDToTypeID("Wdth"), app.charIDToTypeID("#Pxl"), float(width))
            desc.PutUnitDouble(app.charIDToTypeID("Hght"), app.charIDToTypeID("#Pxl"), float(height))

            if mode == "canvas":
                desc.PutEnumerated(app.charIDToTypeID("Anch"), app.charIDToTypeID("Anch"), app.charIDToTypeID("Mdl "))
                app.ExecuteAction(app.charIDToTypeID("CnvS"), desc)
                logger.info(f"画布调整为: {width}x{height}")
            else:
                desc.PutBoolean(app.stringIDToTypeID("scaleStyles"), True)
                desc.PutBoolean(app.charIDToTypeID("CnsP"), params.get("constrain_proportions", False))
                app.ExecuteAction(app.charIDToTypeID("ImgS"), desc)
                logger.info(f"图像调整为: {width}x{height}")

            return {
                "status": "resized",
                "mode": mode,
                "original_size": [orig_w, orig_h],
                "new_size": [width, height],
            }
        except Exception as e:
            logger.error(f"调整尺寸失败: {e}")
            return {"error": f"调整尺寸失败: {e}"}

    async def _get_document_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取当前文档信息（尺寸、图层、色彩模式等）。"""
        try:
            app = self._ensure_connected()
            doc = app.ActiveDocument
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"没有打开的文档: {e}"}

        try:
            # 基本信息
            info: dict[str, Any] = {
                "name": doc.Name,
                "full_path": doc.FullName,
                "width": doc.Width,
                "height": doc.Height,
                "resolution": doc.Resolution,
            }

            # 色彩模式
            try:
                mode_num = int(doc.Mode)
                info["color_mode"] = _COLOR_MODE_NAMES.get(mode_num, f"unknown({mode_num})")
                info["color_mode_id"] = mode_num
            except Exception:
                info["color_mode"] = "unknown"

            # 位深度
            try:
                info["bit_depth"] = int(doc.BitsPerChannel)
            except Exception:
                pass

            # 图层数量
            try:
                info["layer_count"] = doc.ArtLayers.Count + doc.LayerSets.Count
            except Exception:
                info["layer_count"] = 0

            # 图层列表（最多前 20 层）
            try:
                layers = []
                for i, layer in enumerate(doc.ArtLayers):
                    if i >= 20:
                        layers.append("... (more layers)")
                        break
                    layers.append({
                        "name": layer.Name,
                        "visible": layer.Visible,
                        "opacity": layer.Opacity,
                    })
                info["layers"] = layers
            except Exception:
                info["layers"] = []

            # 选区信息
            try:
                sel = doc.Selection
                if sel.Bounds:
                    info["has_selection"] = True
            except Exception:
                info["has_selection"] = False

            logger.info(f"获取文档信息: {doc.Name}")
            return info
        except Exception as e:
            logger.error(f"获取文档信息失败: {e}")
            return {"error": f"获取文档信息失败: {e}"}

    async def _close_document(self, params: dict[str, Any]) -> dict[str, Any]:
        """关闭当前文档。save=True 时先保存。"""
        try:
            app = self._ensure_connected()
            doc = app.ActiveDocument
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"没有打开的文档: {e}"}

        save = params.get("save", False)
        doc_name = doc.Name

        try:
            save_flag = 2 if save else 3  # 2=SaveChanges, 3=DoNotSaveChanges
            doc.Close(save_flag)
            logger.info(f"已关闭文档: {doc_name} (save={save})")
            return {
                "status": "closed",
                "document_name": doc_name,
                "saved": save,
            }
        except Exception as e:
            logger.error(f"关闭文档失败: {e}")
            return {"error": f"关闭文档失败: {e}"}

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _get_save_options(self, app: Any, save_type: str, params: dict) -> Any:
        """根据格式类型创建保存选项对象。

        对于 mock 测试，Photoshop COM 对象的 SaveOptions 属性
        返回的对象只需要有构造方法即可。
        """
        try:
            save_options_class = getattr(app.SaveOptions, save_type)
            return save_options_class()
        except Exception:
            # 降级：返回 None，Photoshop 会使用默认选项
            logger.debug(f"无法创建 SaveOptions.{save_type}，使用默认选项")
            return None

    def _get_filter_id(self, filter_name: str) -> int:
        """根据滤镜名称获取 Action ID。"""
        common_filters = {
            "gaussian_blur": "GsnB", "motion_blur": "BlrM",
            "sharpen": "Shrp", "unsharp_mask": "UnsM", "emboss": "Embs",
        }
        char_id = common_filters.get(filter_name.lower().replace(" ", "_"))
        if char_id:
            return (
                (ord(char_id[0]) << 24) | (ord(char_id[1]) << 16)
                | (ord(char_id[2]) << 8) | ord(char_id[3])
            )
        logger.warning(f"未知滤镜 '{filter_name}'，使用名称哈希")
        return hash(filter_name) & 0xFFFFFFFF

    def _build_filter_descriptor(self, app: Any, filter_name: str, params: dict) -> Any:
        """构建滤镜参数描述符。"""
        desc = app.ActionDescriptor()
        fl = filter_name.lower().replace(" ", "_")
        if fl == "gaussian_blur":
            radius = params.get("radius", params.get("value", 5.0))
            desc.PutUnitDouble(app.charIDToTypeID("Rds "), app.charIDToTypeID("#Pxl"), float(radius))
        elif fl in ("sharpen", "unsharp_mask"):
            desc.PutInteger(app.charIDToTypeID("Amnt"), int(params.get("amount", 100)))
        return desc
