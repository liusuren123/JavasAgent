"""创意工具集。

提供 Photoshop、Premiere 等 Adobe 软件的脚本控制能力。
Photoshop 和 Premiere 操作已实现真实 COM 接口控制。
"""

from __future__ import annotations

from typing import Any

from loguru import logger


class CreativeTools:
    """创意工具集。

    Photoshop 操作通过 COM 接口（Windows）驱动。
    Premiere / After Effects / Illustrator 等仍为占位。

    Usage::

        creative = CreativeTools()
        result = await creative.execute("photoshop_open", {"path": "image.psd"})
    """

    # Photoshop action 前缀到 PhotoshopControl action 的映射
    _PS_ACTION_MAP: dict[str, str] = {
        "photoshop_open": "open_document",
        "photoshop_save": "save_document",
        "photoshop_export": "export_image",
        "photoshop_action": "run_action",
        "photoshop_filter": "apply_filter",
        "photoshop_resize": "resize",
        "photoshop_info": "get_document_info",
        "photoshop_close": "close_document",
    }

    # Premiere action 前缀到 PremiereControl action 的映射
    _PR_ACTION_MAP: dict[str, str] = {
        "premiere_open_project": "open_project",
        "premiere_get_project_info": "get_project_info",
        "premiere_import_media": "import_media",
        "premiere_add_clip": "add_clip_to_timeline",
        "premiere_export_video": "export_video",
        "premiere_get_sequence_info": "get_sequence_info",
    }

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = workspace
        self._ps_control: Any = None
        self._pr_control: Any = None

    def _get_ps_control(self) -> Any:
        """延迟初始化 PhotoshopControl。"""
        if self._ps_control is None:
            from src.tools.photoshop_control import PhotoshopControl

            self._ps_control = PhotoshopControl(workspace=self._workspace)
        return self._ps_control

    def _get_pr_control(self) -> Any:
        """延迟初始化 PremiereControl。"""
        if self._pr_control is None:
            from src.tools.premiere_control import PremiereControl

            self._pr_control = PremiereControl(workspace=self._workspace)
        return self._pr_control

    async def execute(self, action: str, params: dict[str, Any]) -> Any:
        """执行创意工具操作。

        Photoshop 类操作委托给 PhotoshopControl，其余返回占位提示。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            操作结果字典
        """
        # 检查是否为 Photoshop 操作
        ps_action = self._PS_ACTION_MAP.get(action)
        if ps_action is not None:
            try:
                ps = self._get_ps_control()
                return await ps.execute(ps_action, params)
            except Exception as e:
                logger.error(f"Photoshop 操作失败: {e}")
                return {"error": f"Photoshop 操作失败: {e}", "action": action}

        # 检查是否为 Premiere 操作
        pr_action = self._PR_ACTION_MAP.get(action)
        if pr_action is not None:
            try:
                pr = self._get_pr_control()
                return await pr.execute(pr_action, params)
            except Exception as e:
                logger.error(f"Premiere 操作失败: {e}")
                return {"error": f"Premiere 操作失败: {e}", "action": action}

        logger.warning(f"创意工具集尚未实现: {action}")
        return {
            "error": "创意工具集尚未实现，将在后续版本中启用",
            "action": action,
        }
