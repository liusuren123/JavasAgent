"""图片滤镜调整模块。

提供 BrowserControl 的亮度、对比度等滤镜调整方法。
从 image_ops.py 拆分而来，通过混入（Mixin）方式组合到 ImageOps。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.path_safety import PathSafetyError, safe_resolve_path


class ImageFilterMixin:
    """图片滤镜调整混入类。

    要求宿主类具有以下属性/方法：
        _workspace: Path 工作目录
        _safe_path(): 安全路径解析方法
        _resolve_output_path(): 输出路径解析方法
    """

    async def _adjust_brightness(self, params: dict) -> dict[str, Any]:
        """调整图片亮度。

        Params:
            path: 图片文件路径
            factor: 亮度因子（> 1 变亮，< 1 变暗，1 为原始亮度）
            output_path: 输出路径（可选）

        Returns:
            包含亮度因子和输出路径
        """
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        try:
            factor = params.get("factor")
            if factor is None:
                return {"error": "请指定亮度因子 (factor)"}

            from PIL import Image, ImageEnhance

            with Image.open(str(path)) as img:
                enhanced = ImageEnhance.Brightness(img).enhance(float(factor))
                output = self._resolve_output_path(path, params)
                output.parent.mkdir(parents=True, exist_ok=True)
                enhanced.save(str(output))

                logger.info(f"调整亮度: factor={factor}")
                return {
                    "path": str(path),
                    "output_path": str(output),
                    "factor": float(factor),
                }
        except Exception as e:
            logger.error(f"调整亮度失败: {e}")
            return {"error": f"亮度调整失败: {e}"}

    async def _adjust_contrast(self, params: dict) -> dict[str, Any]:
        """调整图片对比度。

        Params:
            path: 图片文件路径
            factor: 对比度因子（> 1 增加对比度，< 1 降低对比度）
            output_path: 输出路径（可选）

        Returns:
            包含对比度因子和输出路径
        """
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        try:
            factor = params.get("factor")
            if factor is None:
                return {"error": "请指定对比度因子 (factor)"}

            from PIL import Image, ImageEnhance

            with Image.open(str(path)) as img:
                enhanced = ImageEnhance.Contrast(img).enhance(float(factor))
                output = self._resolve_output_path(path, params)
                output.parent.mkdir(parents=True, exist_ok=True)
                enhanced.save(str(output))

                logger.info(f"调整对比度: factor={factor}")
                return {
                    "path": str(path),
                    "output_path": str(output),
                    "factor": float(factor),
                }
        except Exception as e:
            logger.error(f"调整对比度失败: {e}")
            return {"error": f"对比度调整失败: {e}"}
