"""图片水印和高级操作模块。

提供 ImageOps 的文字水印、缩略图生成等高级功能。
从 image_ops.py 拆分而来，通过混入（Mixin）方式组合到 ImageOps。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.path_safety import PathSafetyError, safe_resolve_path


class ImageWatermarkMixin:
    """图片水印与高级操作混入类。

    要求宿主类具有以下属性/方法：
        _workspace: Path 工作目录
        _safe_path(): 安全路径解析方法
        _resolve_output_path(): 输出路径解析方法
    """

    async def _add_text_watermark(self, params: dict) -> dict[str, Any]:
        """添加文字水印。

        Params:
            path: 图片文件路径
            text: 水印文字
            position: 水印位置（center / top-left / top-right /
                bottom-left / bottom-right），默认 center
            font_size: 字体大小（默认 36）
            color: 文字颜色（RGB 元组如 [255,255,255]，默认白色）
            opacity: 透明度（0-255，默认 128）
            output_path: 输出路径（可选）

        Returns:
            包含水印文字、位置和输出路径
        """
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        try:
            text = params.get("text")
            if not text:
                return {"error": "请指定水印文字 (text)"}

            from PIL import Image, ImageDraw, ImageFont

            with Image.open(str(path)) as img:
                # 确保为 RGBA 以支持透明度
                base = img.convert("RGBA")

                # 创建水印层
                watermark_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(watermark_layer)

                # 字体
                font_size = params.get("font_size", 36)
                try:
                    font = ImageFont.truetype("arial.ttf", font_size)
                except (OSError, IOError):
                    font = ImageFont.load_default()

                # 颜色和透明度
                color = params.get("color", [255, 255, 255])
                opacity = params.get("opacity", 128)
                fill_color = (
                    int(color[0]),
                    int(color[1]),
                    int(color[2]),
                    int(opacity),
                )

                # 计算文字尺寸
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]

                # 计算位置
                position = params.get("position", "center")
                margin = 20
                positions = {
                    "center": ((base.width - text_w) // 2, (base.height - text_h) // 2),
                    "top-left": (margin, margin),
                    "top-right": (base.width - text_w - margin, margin),
                    "bottom-left": (margin, base.height - text_h - margin),
                    "bottom-right": (base.width - text_w - margin, base.height - text_h - margin),
                }
                pos = positions.get(position, positions["center"])

                draw.text(pos, text, fill=fill_color, font=font)

                # 合成水印
                watermarked = Image.alpha_composite(base, watermark_layer)

                # 保存时转回 RGB（如果源是 RGB 模式）
                output = self._resolve_output_path(path, params)
                output.parent.mkdir(parents=True, exist_ok=True)

                if img.mode != "RGBA":
                    watermarked = watermarked.convert("RGB")
                    # 保持原始格式保存
                    fmt = img.format or "PNG"
                    watermarked.save(str(output), format=fmt)
                else:
                    watermarked.save(str(output))

                logger.info(f"添加水印: text='{text}', position={position}")
                return {
                    "path": str(path),
                    "output_path": str(output),
                    "text": text,
                    "position": position,
                    "font_size": font_size,
                    "opacity": opacity,
                }
        except Exception as e:
            logger.error(f"添加水印失败: {e}")
            return {"error": f"水印添加失败: {e}"}

    async def _thumbnail(self, params: dict) -> dict[str, Any]:
        """生成缩略图。

        将图片缩放到指定最大尺寸内，保持原始比例。
        不会放大比目标尺寸小的图片。

        Params:
            path: 图片文件路径
            max_width: 最大宽度（默认 200）
            max_height: 最大高度（默认 200）
            output_path: 输出路径（可选）

        Returns:
            包含缩略图尺寸和输出路径
        """
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        try:
            max_w = params.get("max_width", 200)
            max_h = params.get("max_height", 200)

            from PIL import Image

            with Image.open(str(path)) as img:
                orig_w, orig_h = img.size
                thumb = img.copy()
                thumb.thumbnail((int(max_w), int(max_h)), Image.LANCZOS)

                output = self._resolve_output_path(path, params, suffix="_thumb")
                output.parent.mkdir(parents=True, exist_ok=True)
                thumb.save(str(output))

                logger.info(
                    f"生成缩略图: {orig_w}x{orig_h} -> {thumb.width}x{thumb.height}"
                )
                return {
                    "path": str(path),
                    "output_path": str(output),
                    "original_size": [orig_w, orig_h],
                    "thumbnail_size": [thumb.width, thumb.height],
                }
        except Exception as e:
            logger.error(f"生成缩略图失败: {e}")
            return {"error": f"缩略图生成失败: {e}"}
