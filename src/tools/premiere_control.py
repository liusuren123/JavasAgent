"""Premiere Pro 脚本控制工具。

通过 Windows COM 接口 (win32com) 驱动 Adobe Premiere Pro，提供项目操作、
素材导入、时间线剪辑、视频导出等能力。仅在 Windows 上可用。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.path_safety import PathSafetyError, safe_resolve_path

_EXPORT_PRESETS: dict[str, str] = {
    "h264": "System preset: H.264 Blu-ray",
    "h264_web": "System preset: H.264 Web",
    "prores": "System preset: Apple ProRes 422",
    "mp4": "System preset: H.264",
    "mp4_1080p": "System preset: H.264 1080p",
    "mp4_720p": "System preset: H.264 720p",
    "mp4_4k": "System preset: H.264 4K",
}


class PremiereControl:
    """Premiere Pro 脚本控制工具。

    通过 COM 接口控制 Premiere Pro。如果 Premiere 未安装或未运行，
    所有操作将返回友好的错误提示，不会导致 agent 崩溃。
    """

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = Path(workspace) if workspace else Path.cwd()
        self._app: Any = None
        self._connected = False

    # ------------------------------------------------------------------
    # COM 连接管理
    # ------------------------------------------------------------------

    def _get_app(self) -> Any:
        """获取 Premiere Pro COM 对象，支持延迟连接和缓存。"""
        if self._connected and self._app is not None:
            return self._app

        if sys.platform != "win32":
            raise RuntimeError("Premiere Pro 控制仅支持 Windows 平台。")

        try:
            import win32com.client
        except ImportError:
            raise RuntimeError("pywin32 未安装，请运行: pip install pywin32") from None

        try:
            app = win32com.client.GetActiveObject("Premiere.Pro.Application")
            self._app = app
            self._connected = True
            logger.info("已连接到 Premiere Pro COM 对象")
            return app
        except Exception as e:
            self._connected = False
            logger.warning(f"无法连接 Premiere Pro: {e}")
            raise RuntimeError(
                "无法连接到 Premiere Pro。请确保 Premiere Pro 已安装并正在运行。"
            ) from e

    def _ensure_connected(self) -> Any:
        """确保已连接到 Premiere Pro，返回 COM 对象或抛出异常。"""
        return self._get_app()

    # ------------------------------------------------------------------
    # 统一入口
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行 Premiere Pro 操作。"""
        handlers: dict[str, Any] = {
            "open_project": self._open_project,
            "get_project_info": self._get_project_info,
            "import_media": self._import_media,
            "add_clip_to_timeline": self._add_clip_to_timeline,
            "export_video": self._export_video,
            "get_sequence_info": self._get_sequence_info,
        }

        handler = handlers.get(action)
        if handler is None:
            logger.error(f"未知的 Premiere Pro 操作: {action}")
            return {
                "error": f"未知操作: {action}",
                "available_actions": sorted(handlers.keys()),
            }

        logger.debug(f"Premiere Pro 操作: {action}, 参数: {params}")
        return await handler(params)

    # ------------------------------------------------------------------
    # 路径安全
    # ------------------------------------------------------------------

    def _safe_path(self, user_path: str, *, allow_create_parents: bool = False) -> Path:
        """安全解析用户路径，防止路径遍历。"""
        return safe_resolve_path(self._workspace, user_path, allow_create_parents=allow_create_parents)

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
    # 操作实现
    # ------------------------------------------------------------------

    async def _open_project(self, params: dict[str, Any]) -> dict[str, Any]:
        """打开 Premiere Pro 项目文件 (.prproj)。"""
        raw_path = params.get("path")
        if not raw_path:
            return {"error": "请指定要打开的项目文件路径 (path)"}

        try:
            path = self._safe_path_or_absolute(raw_path)
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"项目文件不存在: {path}"}
        if path.suffix.lower() != ".prproj":
            return {"error": f"仅支持 .prproj 项目文件，收到: {path.suffix}"}

        try:
            app = self._ensure_connected()
            project = app.OpenProject(str(path))
            if project:
                name = project.Name if hasattr(project, "Name") else path.name
                logger.info(f"已打开项目: {name}")
                return {"status": "opened", "project_name": name, "path": str(path)}
            return {"error": "打开项目失败，Premiere 返回空对象"}
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"打开项目失败: {e}")
            return {"error": f"打开项目失败: {e}"}

    async def _get_project_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取当前项目信息（序列列表、素材列表等）。"""
        try:
            app = self._ensure_connected()
            project = app.ProjectManager.CurrentProject
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"无法获取当前项目: {e}"}

        if project is None:
            return {"error": "当前没有打开的项目"}

        try:
            info: dict[str, Any] = {"name": "", "path": "", "sequences": [], "media_count": 0, "media_items": []}
            try:
                info["name"] = project.Name
            except Exception:
                pass
            try:
                info["path"] = project.Path
            except Exception:
                pass

            # 序列列表
            try:
                seqs = project.Sequences
                info["sequences"] = [
                    {"name": getattr(seqs[i], "Name", f"Sequence {i}"), "id": getattr(seqs[i], "SequenceID", i)}
                    for i in range(seqs.Count)
                ]
            except Exception as e:
                logger.debug(f"获取序列列表时出错: {e}")

            # 素材列表
            try:
                mi = project.MediaItems
                items = [
                    {"name": getattr(mi[j], "Name", f"Media {j}"), "type": str(getattr(mi[j], "MediaType", "unknown"))}
                    for j in range(min(mi.Count, 50))
                ]
                info["media_count"] = mi.Count
                info["media_items"] = items
            except Exception as e:
                logger.debug(f"获取素材列表时出错: {e}")

            logger.info(f"获取项目信息: {info.get('name', 'unknown')}")
            return info
        except Exception as e:
            logger.error(f"获取项目信息失败: {e}")
            return {"error": f"获取项目信息失败: {e}"}

    async def _import_media(self, params: dict[str, Any]) -> dict[str, Any]:
        """导入媒体文件到项目。"""
        raw_paths = params.get("paths")
        if not raw_paths or not isinstance(raw_paths, list):
            return {"error": "请指定要导入的媒体文件路径列表 (paths)"}
        if len(raw_paths) > 50:
            return {"error": f"单次最多导入 50 个文件，收到 {len(raw_paths)} 个"}

        resolved_paths: list[str] = []
        not_found: list[str] = []
        for rp in raw_paths:
            try:
                path = self._safe_path_or_absolute(rp)
                if path.exists():
                    resolved_paths.append(str(path))
                else:
                    not_found.append(rp)
            except PathSafetyError:
                not_found.append(rp)

        if not resolved_paths:
            return {"error": "没有找到可导入的文件", "not_found": not_found}

        try:
            app = self._ensure_connected()
            project = app.ProjectManager.CurrentProject
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"无法获取当前项目: {e}"}

        if project is None:
            return {"error": "当前没有打开的项目"}

        try:
            suppress_warnings = params.get("suppress_warnings", True)
            imported = []
            for fp in resolved_paths:
                try:
                    result = project.ImportMedia(fp, suppressWarnings=suppress_warnings)
                    imported.append({"path": fp, "name": Path(fp).name, "success": result is not None})
                except Exception as e:
                    imported.append({"path": fp, "success": False, "error": str(e)})

            success_count = sum(1 for it in imported if it["success"])
            logger.info(f"导入完成: {success_count}/{len(imported)} 成功")
            result: dict[str, Any] = {"status": "imported", "imported_count": success_count, "total": len(imported), "details": imported}
            if not_found:
                result["not_found"] = not_found
            return result
        except Exception as e:
            logger.error(f"导入媒体失败: {e}")
            return {"error": f"导入媒体失败: {e}"}

    async def _add_clip_to_timeline(self, params: dict[str, Any]) -> dict[str, Any]:
        """将素材添加到时间线。"""
        media_name = params.get("media_name")
        if not media_name:
            return {"error": "请指定要添加的素材名称 (media_name)"}

        track_index = int(params.get("track_index", 0))
        time_offset = float(params.get("time_offset", 0.0))
        if track_index < 0:
            return {"error": "轨道索引不能为负数"}
        if time_offset < 0:
            return {"error": "时间偏移不能为负数"}

        try:
            app = self._ensure_connected()
            project = app.ProjectManager.CurrentProject
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"无法获取当前项目: {e}"}

        if project is None:
            return {"error": "当前没有打开的项目"}

        try:
            # 查找素材
            target_media = None
            try:
                mi = project.MediaItems
                for i in range(mi.Count):
                    item = mi[i]
                    if hasattr(item, "Name") and item.Name == media_name:
                        target_media = item
                        break
            except Exception:
                pass

            if target_media is None:
                return {"error": f"未找到素材: {media_name}", "hint": "请先通过 import_media 导入素材"}

            # 获取序列
            target_sequence = None
            sequence_name = params.get("sequence_name")
            try:
                seqs = project.Sequences
                if seqs.Count == 0:
                    return {"error": "项目中没有序列，请先创建序列"}
                if sequence_name:
                    for i in range(seqs.Count):
                        if hasattr(seqs[i], "Name") and seqs[i].Name == sequence_name:
                            target_sequence = seqs[i]
                            break
                if target_sequence is None:
                    target_sequence = seqs[0]
            except Exception as e:
                return {"error": f"无法获取序列: {e}"}

            # 添加到时间线
            try:
                target_sequence.AddClip(target_media, trackIndex=track_index, timeOffset=time_offset)
            except AttributeError:
                try:
                    target_sequence.SetTimelineClip(target_media, track_index, time_offset)
                except Exception:
                    return {"error": "当前 Premiere 版本不支持此操作"}

            seq_name = getattr(target_sequence, "Name", "unknown")
            logger.info(f"已添加素材 '{media_name}' 到时间线 (序列: {seq_name})")
            return {"status": "clip_added", "media_name": media_name, "sequence": seq_name, "track_index": track_index, "time_offset": time_offset}
        except Exception as e:
            logger.error(f"添加素材到时间线失败: {e}")
            return {"error": f"添加素材到时间线失败: {e}"}

    async def _export_video(self, params: dict[str, Any]) -> dict[str, Any]:
        """导出视频（使用预设）。"""
        raw_path = params.get("output_path")
        if not raw_path:
            return {"error": "请指定输出路径 (output_path)"}

        preset_key = params.get("preset", "h264").lower()
        preset_name = _EXPORT_PRESETS.get(preset_key)
        if not preset_name:
            return {"error": f"不支持的导出预设: {preset_key}", "available_presets": sorted(_EXPORT_PRESETS.keys())}

        try:
            out_path = self._safe_path(raw_path, allow_create_parents=True)
        except PathSafetyError as e:
            return {"error": str(e)}
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            app = self._ensure_connected()
            project = app.ProjectManager.CurrentProject
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"无法获取当前项目: {e}"}

        if project is None:
            return {"error": "当前没有打开的项目"}

        try:
            # 查找序列
            target_sequence = None
            sequence_name = params.get("sequence_name")
            try:
                seqs = project.Sequences
                if seqs.Count == 0:
                    return {"error": "项目中没有序列可导出"}
                if sequence_name:
                    for i in range(seqs.Count):
                        if hasattr(seqs[i], "Name") and seqs[i].Name == sequence_name:
                            target_sequence = seqs[i]
                            break
                if target_sequence is None:
                    target_sequence = seqs[0]
            except Exception as e:
                return {"error": f"无法获取序列: {e}"}

            # 执行导出
            try:
                export_params = {"outputFilePath": str(out_path), "presetPath": preset_name}
                range_start = params.get("range_start")
                range_end = params.get("range_end")
                if range_start is not None and range_end is not None:
                    export_params["rangeStart"] = float(range_start)
                    export_params["rangeEnd"] = float(range_end)
                target_sequence.Export(**export_params)
            except AttributeError:
                try:
                    project.ExportTimeline(str(out_path), preset=preset_name)
                except Exception:
                    return {"error": "当前 Premiere 版本不支持此导出操作"}

            logger.info(f"已开始导出: {out_path} (预设: {preset_key})")
            return {"status": "exporting", "output_path": str(out_path), "preset": preset_key, "note": "导出在 Premiere 后台进行，请等待完成"}
        except Exception as e:
            logger.error(f"导出视频失败: {e}")
            return {"error": f"导出视频失败: {e}"}

    async def _get_sequence_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取当前序列信息。"""
        try:
            app = self._ensure_connected()
            project = app.ProjectManager.CurrentProject
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"无法获取当前项目: {e}"}

        if project is None:
            return {"error": "当前没有打开的项目"}

        try:
            target_sequence = None
            sequence_name = params.get("sequence_name")

            try:
                seqs = project.Sequences
                if seqs.Count == 0:
                    return {"error": "项目中没有序列"}
                if sequence_name:
                    for i in range(seqs.Count):
                        if hasattr(seqs[i], "Name") and seqs[i].Name == sequence_name:
                            target_sequence = seqs[i]
                            break
                    if target_sequence is None:
                        avail = [getattr(seqs[i], "Name", f"Sequence {i}") for i in range(seqs.Count)]
                        return {"error": f"未找到序列: {sequence_name}", "available_sequences": avail}
                else:
                    try:
                        target_sequence = app.ProjectManager.ActiveSequence
                    except Exception:
                        target_sequence = seqs[0]
            except Exception as e:
                return {"error": f"无法获取序列: {e}"}

            info: dict[str, Any] = {"name": "", "width": 0, "height": 0}
            try:
                info["name"] = target_sequence.Name
            except Exception:
                pass
            try:
                info["id"] = target_sequence.SequenceID
            except Exception:
                pass

            try:
                s = target_sequence.Settings
                info["width"] = getattr(s, "VideoWidth", 0)
                info["height"] = getattr(s, "VideoHeight", 0)
                info["frame_rate"] = getattr(s, "VideoFrameRate", 0)
                info["audio_sample_rate"] = getattr(s, "AudioSampleRate", 0)
            except Exception:
                pass

            try:
                info["video_track_count"] = getattr(target_sequence.VideoTracks, "Count", 0)
                info["audio_track_count"] = getattr(target_sequence.AudioTracks, "Count", 0)
            except Exception:
                pass

            try:
                info["duration_seconds"] = getattr(target_sequence, "Duration", 0)
                info["end"] = getattr(target_sequence, "End", 0)
            except Exception:
                pass

            logger.info(f"获取序列信息: {info.get('name', 'unknown')}")
            return info
        except Exception as e:
            logger.error(f"获取序列信息失败: {e}")
            return {"error": f"获取序列信息失败: {e}"}
