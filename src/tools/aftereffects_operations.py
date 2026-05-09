"""After Effects 操作实现。

包含 AfterEffectsControl.execute() 调用的所有异步操作函数。
每个函数签名统一为 ``async def _(ctrl, params) -> dict``，
其中 ``ctrl`` 是 AfterEffectsControl 实例。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

_RENDER_PRESETS: dict[str, str] = {
    "h264": "H.264",
    "lossless": "Lossless",
    "prores": "Apple ProRes 422",
    "png_sequence": "PNG Sequence",
    "tiff_sequence": "TIFF Sequence",
    "webm": "WebM",
}


async def _list_projects(ctrl: Any, params: dict[str, Any]) -> dict[str, Any]:
    """列出 After Effects 中打开的项目。"""
    try:
        app = ctrl._ensure_connected()
    except RuntimeError as e:
        return {"error": str(e)}

    try:
        projects: list[dict[str, Any]] = []
        try:
            ae_projects = app.Projects
            for i in range(ae_projects.Count):
                proj = ae_projects[i]
                proj_info: dict[str, Any] = {
                    "name": getattr(proj, "Name", f"Project {i}"),
                    "path": getattr(proj, "Path", ""),
                    "id": getattr(proj, "ID", i),
                }
                try:
                    cnt = proj.Items.Count
                    comp_count = sum(
                        1 for j in range(cnt)
                        if getattr(proj.Items[j], "TypeName", "") == "Composition"
                    )
                    proj_info["composition_count"] = comp_count
                    proj_info["item_count"] = cnt
                except Exception:
                    proj_info["composition_count"] = 0
                    proj_info["item_count"] = 0
                projects.append(proj_info)
        except AttributeError:
            proj = app.Project
            if proj is not None:
                projects.append({
                    "name": getattr(proj, "Name", "Untitled"),
                    "path": getattr(proj, "Path", ""),
                    "composition_count": 0,
                })

        logger.info(f"列出项目: {len(projects)} 个")
        return {"status": "ok", "project_count": len(projects), "projects": projects}
    except Exception as e:
        logger.error(f"列出项目失败: {e}")
        return {"error": f"列出项目失败: {e}"}


async def _get_active_composition(ctrl: Any, params: dict[str, Any]) -> dict[str, Any]:
    """获取当前活动合成的详细信息。"""
    try:
        app = ctrl._ensure_connected()
    except RuntimeError as e:
        return {"error": str(e)}

    try:
        comp = app.ActiveItem
        if comp is None:
            try:
                proj = app.Project
                if proj is None:
                    return {"error": "当前没有打开的项目"}
                items = proj.Items
                for i in range(items.Count):
                    item = items[i]
                    if getattr(item, "TypeName", "") == "Composition":
                        comp = item
                        break
            except Exception:
                pass

        if comp is None:
            return {"error": "当前没有活动的合成"}

        info: dict[str, Any] = {
            "name": getattr(comp, "Name", "Untitled"),
            "width": getattr(comp, "Width", 0),
            "height": getattr(comp, "Height", 0),
            "fps": getattr(comp, "FrameRate", 0.0),
            "duration": getattr(comp, "Duration", 0.0),
            "bg_color": getattr(comp, "BgColor", [0, 0, 0]),
        }
        try:
            info["layer_count"] = comp.Layers.Count
        except Exception:
            info["layer_count"] = 0
        try:
            info["pixel_aspect"] = getattr(comp, "PixelAspectRatio", 1.0)
        except Exception:
            pass

        logger.info(f"获取合成信息: {info['name']}")
        return info
    except Exception as e:
        logger.error(f"获取合成信息失败: {e}")
        return {"error": f"获取合成信息失败: {e}"}


async def _list_layers(ctrl: Any, params: dict[str, Any]) -> dict[str, Any]:
    """列出合成中的所有图层。"""
    try:
        app = ctrl._ensure_connected()
    except RuntimeError as e:
        return {"error": str(e)}

    try:
        comp = ctrl._resolve_composition(app, params.get("composition_name"))
        if isinstance(comp, dict):
            return comp

        layers: list[dict[str, Any]] = []
        comp_layers = comp.Layers
        for i in range(1, comp_layers.Count + 1):
            layer = comp_layers[i]
            layer_info: dict[str, Any] = {
                "index": i,
                "name": getattr(layer, "Name", f"Layer {i}"),
                "enabled": getattr(layer, "Enabled", True),
                "locked": getattr(layer, "Locked", False),
                "solo": getattr(layer, "Solo", False),
                "shy": getattr(layer, "Shy", False),
            }
            try:
                layer_info["type"] = ctrl._get_layer_type(layer)
            except Exception:
                layer_info["type"] = "unknown"

            # 变换属性
            try:
                props = layer.Property
                for prop_name, key in [("Position", "position"), ("Scale", "scale")]:
                    try:
                        val = getattr(props, prop_name).Value
                        layer_info[key] = list(val) if hasattr(val, "__iter__") else val
                    except Exception:
                        pass
                try:
                    layer_info["rotation"] = props.Rotation.Value
                except Exception:
                    pass
                try:
                    layer_info["opacity"] = props.Opacity.Value
                except Exception:
                    pass
            except Exception:
                pass

            try:
                layer_info["in_point"] = getattr(layer, "InPoint", 0)
                layer_info["out_point"] = getattr(layer, "OutPoint", 0)
                layer_info["duration"] = getattr(layer, "Duration", 0)
            except Exception:
                pass

            layers.append(layer_info)

        comp_name = getattr(comp, "Name", "Unknown")
        logger.info(f"列出图层: {comp_name} ({len(layers)} 层)")
        return {"status": "ok", "composition": comp_name, "layer_count": len(layers), "layers": layers}
    except Exception as e:
        logger.error(f"列出图层失败: {e}")
        return {"error": f"列出图层失败: {e}"}


async def _add_text_layer(ctrl: Any, params: dict[str, Any]) -> dict[str, Any]:
    """添加文字图层到合成。"""
    text = params.get("text")
    if not text:
        return {"error": "请指定文字内容 (text)"}

    try:
        app = ctrl._ensure_connected()
    except RuntimeError as e:
        return {"error": str(e)}

    try:
        comp = ctrl._resolve_composition(app, params.get("composition_name"))
        if isinstance(comp, dict):
            return comp

        text_layer = comp.Layers.AddText(text)
        if text_layer is None:
            return {"error": "创建文字图层失败"}

        layer_name = getattr(text_layer, "Name", text)

        # 字体属性
        try:
            text_doc = text_layer.SourceText.Value
            if text_doc is not None:
                font_size = params.get("font_size")
                if font_size is not None:
                    text_doc.FontSize = float(font_size)
                font_name = params.get("font_name")
                if font_name:
                    text_doc.Font = font_name
                color = params.get("color")
                if color and isinstance(color, (list, tuple)) and len(color) >= 3:
                    text_doc.FillColor = color[:3]
                text_layer.SourceText.SetValue(text_doc)
        except Exception as e:
            logger.debug(f"设置文字属性时部分失败: {e}")

        # 位置
        position = params.get("position")
        if position and isinstance(position, (list, tuple)) and len(position) >= 2:
            try:
                text_layer.Property.Position.SetValue(position[:2])
            except Exception:
                try:
                    text_layer.Position.SetValue(position[:2])
                except Exception as e:
                    logger.debug(f"设置位置失败: {e}")

        comp_name = getattr(comp, "Name", "Unknown")
        logger.info(f"已添加文字图层: '{text}' 到合成 '{comp_name}'")
        return {"status": "created", "layer_name": layer_name, "text": text, "composition": comp_name}
    except Exception as e:
        logger.error(f"添加文字图层失败: {e}")
        return {"error": f"添加文字图层失败: {e}"}


async def _add_solid_layer(ctrl: Any, params: dict[str, Any]) -> dict[str, Any]:
    """添加纯色图层到合成。"""
    try:
        app = ctrl._ensure_connected()
    except RuntimeError as e:
        return {"error": str(e)}

    try:
        comp = ctrl._resolve_composition(app, params.get("composition_name"))
        if isinstance(comp, dict):
            return comp

        color = params.get("color", [1.0, 1.0, 1.0])
        if not isinstance(color, (list, tuple)) or len(color) < 3:
            return {"error": "颜色格式应为 [r, g, b]，值范围 0-1"}

        layer_name = params.get("name", "Solid")
        width = params.get("width", getattr(comp, "Width", 1920))
        height = params.get("height", getattr(comp, "Height", 1080))

        solid_layer = comp.Layers.AddSolid(
            color[:3], layer_name, int(width), int(height),
            getattr(comp, "PixelAspectRatio", 1.0),
            getattr(comp, "Duration", 1.0),
        )
        if solid_layer is None:
            return {"error": "创建纯色图层失败"}

        comp_name = getattr(comp, "Name", "Unknown")
        logger.info(f"已添加纯色图层: '{layer_name}' 到合成 '{comp_name}'")
        return {
            "status": "created", "layer_name": layer_name,
            "color": color[:3], "size": [int(width), int(height)],
            "composition": comp_name,
        }
    except Exception as e:
        logger.error(f"添加纯色图层失败: {e}")
        return {"error": f"添加纯色图层失败: {e}"}


async def _set_layer_property(ctrl: Any, params: dict[str, Any]) -> dict[str, Any]:
    """设置图层属性（位置、缩放、旋转、透明度等）。"""
    layer_name = params.get("layer_name")
    property_name = params.get("property_name")
    value = params.get("value")

    if not layer_name:
        return {"error": "请指定图层名称 (layer_name)"}
    if not property_name:
        return {"error": "请指定属性名称 (property_name)"}
    if value is None:
        return {"error": "请指定属性值 (value)"}

    try:
        app = ctrl._ensure_connected()
    except RuntimeError as e:
        return {"error": str(e)}

    try:
        comp = ctrl._resolve_composition(app, params.get("composition_name"))
        if isinstance(comp, dict):
            return comp

        # 查找图层
        target_layer = None
        comp_layers = comp.Layers
        for i in range(1, comp_layers.Count + 1):
            layer = comp_layers[i]
            if getattr(layer, "Name", "") == layer_name:
                target_layer = layer
                break

        if target_layer is None:
            return {"error": f"未找到图层: {layer_name}", "hint": "请先通过 list_layers 查看可用图层"}

        prop = ctrl._get_layer_property(target_layer, property_name)
        if prop is None:
            return {
                "error": f"不支持或未找到属性: {property_name}",
                "supported_properties": ["position", "scale", "rotation", "opacity", "anchor_point"],
            }

        time = params.get("time")
        if isinstance(value, list):
            if time is not None:
                prop.SetValueAtTime(float(time), value)
            else:
                prop.SetValue(value)
        else:
            if time is not None:
                prop.SetValueAtTime(float(time), float(value))
            else:
                prop.SetValue(float(value))

        comp_name = getattr(comp, "Name", "Unknown")
        logger.info(f"已设置属性 '{property_name}' = {value} on '{layer_name}' (合成: {comp_name})")
        return {
            "status": "set", "layer_name": layer_name,
            "property_name": property_name, "value": value,
            "composition": comp_name,
        }
    except Exception as e:
        logger.error(f"设置图层属性失败: {e}")
        return {"error": f"设置图层属性失败: {e}"}


async def _render_composition(ctrl: Any, params: dict[str, Any]) -> dict[str, Any]:
    """渲染合成到文件。"""
    raw_path = params.get("output_path")
    if not raw_path:
        return {"error": "请指定输出文件路径 (output_path)"}

    preset_key = params.get("preset", "h264").lower()
    preset_name = _RENDER_PRESETS.get(preset_key)
    if not preset_name:
        return {"error": f"不支持的渲染预设: {preset_key}", "available_presets": sorted(_RENDER_PRESETS.keys())}

    try:
        out_path = ctrl._safe_path(raw_path, allow_create_parents=True)
    except Exception as e:
        return {"error": str(e)}
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        app = ctrl._ensure_connected()
    except RuntimeError as e:
        return {"error": str(e)}

    try:
        comp = ctrl._resolve_composition(app, params.get("composition_name"))
        if isinstance(comp, dict):
            return comp

        rq = app.Project.RenderQueue
        rq_item = rq.Add(comp)
        if rq_item is None:
            return {"error": "无法创建渲染队列项"}

        # 输出模块
        try:
            output_module = rq_item.OutputModules[1]
            output_module.File = str(out_path)
            try:
                output_module.ApplyTemplate(preset_name)
            except Exception:
                logger.debug(f"无法应用预设 '{preset_name}'，使用默认设置")
        except Exception as e:
            logger.warning(f"设置输出模块失败: {e}")

        # 渲染范围
        start_frame = params.get("start_frame")
        end_frame = params.get("end_frame")
        if start_frame is not None or end_frame is not None:
            try:
                rq_item.TimeSpanStart = int(start_frame or 0)
                if end_frame is not None:
                    rq_item.TimeSpanDuration = int(end_frame) - int(start_frame or 0)
            except Exception as e:
                logger.debug(f"设置渲染范围失败: {e}")

        rq.Render()

        comp_name = getattr(comp, "Name", "Unknown")
        logger.info(f"已开始渲染: {comp_name} -> {out_path} (预设: {preset_key})")
        return {
            "status": "rendering", "composition": comp_name,
            "output_path": str(out_path), "preset": preset_key,
            "note": "渲染在 After Effects 后台进行，请等待完成",
        }
    except Exception as e:
        logger.error(f"渲染合成失败: {e}")
        return {"error": f"渲染合成失败: {e}"}


async def _import_file(ctrl: Any, params: dict[str, Any]) -> dict[str, Any]:
    """导入素材文件到项目。"""
    raw_path = params.get("path")
    if not raw_path:
        return {"error": "请指定要导入的文件路径 (path)"}

    try:
        path = ctrl._safe_path_or_absolute(raw_path)
    except Exception as e:
        return {"error": str(e)}

    if not path.exists():
        return {"error": f"文件不存在: {path}"}

    try:
        app = ctrl._ensure_connected()
    except RuntimeError as e:
        return {"error": str(e)}

    try:
        proj = app.Project
        if proj is None:
            return {"error": "当前没有打开的项目"}

        as_seq = params.get("as_sequence", False)
        try:
            io_obj = app.ImportOptions(str(path))
            if isinstance(as_seq, bool):
                io_obj.Sequence = as_seq
            imported = proj.ImportFile(io_obj)
        except (AttributeError, TypeError):
            imported = proj.ImportFile(str(path))

        if imported is None:
            return {"error": f"导入文件失败: {path.name}"}

        item_name = params.get("name") or path.name
        try:
            imported.Name = item_name
        except Exception:
            item_name = getattr(imported, "Name", path.name)

        logger.info(f"已导入文件: {item_name}")
        return {"status": "imported", "name": item_name, "path": str(path), "as_sequence": bool(as_seq)}
    except Exception as e:
        logger.error(f"导入文件失败: {e}")
        return {"error": f"导入文件失败: {e}"}


async def _export_frame(ctrl: Any, params: dict[str, Any]) -> dict[str, Any]:
    """导出当前帧为图片。"""
    raw_path = params.get("output_path")
    if not raw_path:
        return {"error": "请指定输出图片路径 (output_path)"}

    try:
        out_path = ctrl._safe_path(raw_path, allow_create_parents=True)
    except Exception as e:
        return {"error": str(e)}

    ext = out_path.suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"):
        return {"error": f"不支持的图片格式: {ext}", "supported_formats": [".png", ".jpg", ".jpeg", ".bmp", ".tiff"]}

    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        app = ctrl._ensure_connected()
    except RuntimeError as e:
        return {"error": str(e)}

    try:
        comp = ctrl._resolve_composition(app, params.get("composition_name"))
        if isinstance(comp, dict):
            return comp

        time = params.get("time")
        if time is not None:
            try:
                comp.Time = float(time)
            except Exception:
                pass

        # 尝试 SaveFrameToPng，降级为渲染队列单帧导出
        try:
            comp.SaveFrameToPng(str(out_path))
        except AttributeError:
            try:
                rq = app.Project.RenderQueue
                rq_item = rq.Add(comp)
                try:
                    rq_item.TimeSpanStart = comp.Time
                    rq_item.TimeSpanDuration = 0
                except Exception:
                    pass
                output_module = rq_item.OutputModules[1]
                output_module.File = str(out_path)
                try:
                    output_module.ApplyTemplate("PNG Sequence")
                except Exception:
                    pass
                rq.Render()
                try:
                    rq_item.Remove()
                except Exception:
                    pass
            except Exception as e:
                return {"error": f"当前 AE 版本不支持帧导出: {e}"}

        comp_name = getattr(comp, "Name", "Unknown")
        logger.info(f"已导出帧: {comp_name} -> {out_path}")
        return {"status": "exported", "composition": comp_name, "output_path": str(out_path), "format": ext}
    except Exception as e:
        logger.error(f"导出帧失败: {e}")
        return {"error": f"导出帧失败: {e}"}
