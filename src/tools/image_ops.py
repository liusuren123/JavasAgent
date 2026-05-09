"""图片处理工具集。

提供图片信息获取、缩放、裁剪、旋转、格式转换等基础图片处理能力。
亮度/对比度调整在 image_filters 模块中，水印/缩略图在 image_watermark 模块中。
基于 Pillow 库实现。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from loguru import logger

from src.tools.image_filters import ImageFilterMixin
from src.tools.image_watermark import ImageWatermarkMixin
from src.utils.path_safety import PathSafetyError, safe_resolve_path


class ImageOps(ImageFilterMixin, ImageWatermarkMixin):
    """图片处理工具集。

    支持常见图片格式（PNG/JPG/WEBP/BMP）的读取、处理和保存。
    所有文件操作均在 workspace 范围内进行，防止路径遍历攻击。

    基础操作（info/resize/crop/rotate/convert/flip）在本类中实现；
    滤镜调整来自 ImageFilterMixin；水印/缩略图来自 ImageWatermarkMixin。

    Usage::

        img = ImageOps(workspace="/path/to/workspace")
        # 获取图片信息
        result = await img.execute("get_info", {"path": "photo.jpg"})
        # 缩放图片
        result = await img.execute("resize", {
            "path": "photo.jpg",
            "width": 800,
            "height": 600,
        })
    """

    # 支持的输出格式
    _SUPPORTED_FORMATS = {"png", "jpg", "jpeg", "webp", "bmp"}

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = Path(workspace) if workspace else Path.cwd()

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行图片处理操作。

        Args:
            action: 操作类型，支持 get_info / resize / crop / rotate /
                convert / adjust_brightness / adjust_contrast /
                add_text_watermark / flip / thumbnail
            params: 操作参数，不同操作需要不同参数

        Returns:
            操作结果字典。成功时包含操作信息，失败时包含 error 字段。
        """
        try:
            from PIL import Image  # noqa: F401 — 检查 Pillow 可用性
        except ImportError:
            return {"error": "Pillow 未安装，请运行: pip install Pillow"}

        handlers = {
            "get_info": self._get_info,
            "resize": self._resize,
            "crop": self._crop,
            "rotate": self._rotate,
            "convert": self._convert,
            "flip": self._flip,
            # 来自 ImageFilterMixin
            "adjust_brightness": self._adjust_brightness,
            "adjust_contrast": self._adjust_contrast,
            # 来自 ImageWatermarkMixin
            "add_text_watermark": self._add_text_watermark,
            "thumbnail": self._thumbnail,
        }

        handler = handlers.get(action)
        if handler is None:
            logger.error(f"未知操作: {action}")
            return {
                "error": f"未知操作: {action}",
                "available_actions": sorted(handlers.keys()),
            }

        return await handler(params)

    def _safe_path(self, user_path: str, *, allow_create_parents: bool = False) -> Path:
        """安全解析用户路径，防止路径遍历。

        Args:
            user_path: 用户提供的相对路径
            allow_create_parents: 是否允许创建不存在的父目录

        Returns:
            解析后的安全绝对路径

        Raises:
            PathSafetyError: 路径超出工作目录范围
        """
        return safe_resolve_path(
            self._workspace,
            user_path,
            allow_create_parents=allow_create_parents,
        )

    def _resolve_output_path(
        self,
        source: Path,
        params: dict[str, Any],
        suffix: str = "_processed",
    ) -> Path:
        """解析输出路径。

        如果用户指定了 output_path，则使用该路径；否则在源文件同目录
        生成带 ``_processed`` 后缀的文件名。

        Args:
            source: 源文件路径
            params: 参数字典，可能包含 output_path
            suffix: 默认输出文件名后缀

        Returns:
            输出文件的绝对路径
        """
        output = params.get("output_path")
        if output:
            return self._safe_path(output, allow_create_parents=True)

        stem = source.stem + suffix
        return source.with_name(stem + source.suffix)

    # ------------------------------------------------------------------
    # get_info — 获取图片基本信息
    # ------------------------------------------------------------------

    async def _get_info(self, params: dict) -> dict[str, Any]:
        """获取图片基本信息。

        Params:
            path: 图片文件路径

        Returns:
            包含 width / height / format / mode / file_size 等字段
        """
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        try:
            from PIL import Image

            with Image.open(str(path)) as img:
                info = {
                    "path": str(path),
                    "width": img.width,
                    "height": img.height,
                    "format": img.format,
                    "mode": img.mode,
                    "file_size": os.path.getsize(str(path)),
                    "file_size_human": _human_size(os.path.getsize(str(path))),
                }
                # EXIF 方向
                if hasattr(img, "_getexif") and img._getexif():
                    info["has_exif"] = True

                logger.info(f"获取图片信息: {path} ({img.width}x{img.height})")
                return info
        except Exception as e:
            logger.error(f"获取图片信息失败: {e}")
            return {"error": f"读取图片失败: {e}"}

    # ------------------------------------------------------------------
    # resize — 缩放图片
    # ------------------------------------------------------------------

    async def _resize(self, params: dict) -> dict[str, Any]:
        """缩放图片。

        支持三种模式：
        1. 指定宽高 (width + height)
        2. 指定百分比 (percent)
        3. 指定宽度或高度其中一个，保持比例 (width 或 height)

        Params:
            path: 图片文件路径
            width: 目标宽度（可选）
            height: 目标高度（可选）
            percent: 缩放百分比，如 50 表示缩小到 50%（可选）
            output_path: 输出路径（可选，默认加 _processed 后缀）

        Returns:
            包含新尺寸和输出路径
        """
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        try:
            from PIL import Image

            with Image.open(str(path)) as img:
                orig_w, orig_h = img.size
                percent = params.get("percent")
                width = params.get("width")
                height = params.get("height")

                if percent is not None:
                    scale = float(percent) / 100.0
                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))
                elif width is not None and height is not None:
                    new_w = max(1, int(width))
                    new_h = max(1, int(height))
                elif width is not None:
                    new_w = max(1, int(width))
                    new_h = max(1, int(orig_h * (new_w / orig_w)))
                elif height is not None:
                    new_h = max(1, int(height))
                    new_w = max(1, int(orig_w * (new_h / orig_h)))
                else:
                    return {"error": "请指定 width、height 或 percent 中的至少一个"}

                resized = img.resize((new_w, new_h), Image.LANCZOS)
                output = self._resolve_output_path(path, params)
                output.parent.mkdir(parents=True, exist_ok=True)
                resized.save(str(output))

                logger.info(f"缩放图片: {orig_w}x{orig_h} -> {new_w}x{new_h}")
                return {
                    "path": str(path),
                    "output_path": str(output),
                    "original_size": [orig_w, orig_h],
                    "new_size": [new_w, new_h],
                }
        except Exception as e:
            logger.error(f"缩放图片失败: {e}")
            return {"error": f"缩放失败: {e}"}

    # ------------------------------------------------------------------
    # crop — 裁剪图片
    # ------------------------------------------------------------------

    async def _crop(self, params: dict) -> dict[str, Any]:
        """裁剪图片。

        Params:
            path: 图片文件路径
            left: 左边界像素坐标
            top: 上边界像素坐标
            right: 右边界像素坐标
            bottom: 下边界像素坐标
            output_path: 输出路径（可选）

        Returns:
            包含裁剪后尺寸和输出路径
        """
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        try:
            left = params.get("left")
            top = params.get("top")
            right = params.get("right")
            bottom = params.get("bottom")

            if any(v is None for v in (left, top, right, bottom)):
                return {"error": "裁剪需要指定 left / top / right / bottom 四个坐标"}

            box = (int(left), int(top), int(right), int(bottom))

            from PIL import Image

            with Image.open(str(path)) as img:
                # 校验边界
                if box[0] < 0 or box[1] < 0 or box[2] > img.width or box[3] > img.height:
                    return {
                        "error": (
                            f"裁剪区域 ({box}) 超出图片范围 "
                            f"(0, 0, {img.width}, {img.height})"
                        )
                    }
                if box[2] <= box[0] or box[3] <= box[1]:
                    return {"error": f"裁剪区域无效: right 必须大于 left, bottom 必须大于 top"}

                cropped = img.crop(box)
                output = self._resolve_output_path(path, params)
                output.parent.mkdir(parents=True, exist_ok=True)
                cropped.save(str(output))

                logger.info(f"裁剪图片: {img.size} -> box={box}")
                return {
                    "path": str(path),
                    "output_path": str(output),
                    "crop_box": list(box),
                    "new_size": [cropped.width, cropped.height],
                }
        except Exception as e:
            logger.error(f"裁剪图片失败: {e}")
            return {"error": f"裁剪失败: {e}"}

    # ------------------------------------------------------------------
    # rotate — 旋转图片
    # ------------------------------------------------------------------

    async def _rotate(self, params: dict) -> dict[str, Any]:
        """旋转图片。

        Params:
            path: 图片文件路径
            angle: 旋转角度（正数顺时针，负数逆时针）
            expand: 是否扩展画布以容纳完整图片（默认 True）
            output_path: 输出路径（可选）

        Returns:
            包含旋转角度和新尺寸
        """
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        try:
            angle = params.get("angle")
            if angle is None:
                return {"error": "请指定旋转角度 (angle)"}

            expand = params.get("expand", True)

            from PIL import Image

            with Image.open(str(path)) as img:
                rotated = img.rotate(float(angle), expand=bool(expand))
                output = self._resolve_output_path(path, params)
                output.parent.mkdir(parents=True, exist_ok=True)
                rotated.save(str(output))

                logger.info(f"旋转图片: {angle}°, expand={expand}")
                return {
                    "path": str(path),
                    "output_path": str(output),
                    "angle": float(angle),
                    "original_size": list(img.size),
                    "new_size": [rotated.width, rotated.height],
                }
        except Exception as e:
            logger.error(f"旋转图片失败: {e}")
            return {"error": f"旋转失败: {e}"}

    # ------------------------------------------------------------------
    # convert — 格式转换
    # ------------------------------------------------------------------

    async def _convert(self, params: dict) -> dict[str, Any]:
        """格式转换。

        支持 PNG / JPG / WEBP / BMP 之间互转。

        Params:
            path: 图片文件路径
            target_format: 目标格式（png / jpg / webp / bmp）
            output_path: 输出路径（可选，默认根据目标格式自动生成）

        Returns:
            包含源格式、目标格式和输出路径
        """
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        target_format = params.get("target_format", "").lower()
        if not target_format:
            return {"error": "请指定目标格式 (target_format)"}
        if target_format not in self._SUPPORTED_FORMATS:
            return {
                "error": f"不支持的目标格式: {target_format}",
                "supported": sorted(self._SUPPORTED_FORMATS),
            }

        try:
            from PIL import Image

            with Image.open(str(path)) as img:
                src_format = img.format or path.suffix.lstrip(".").upper()

                # 如果用户指定了 output_path 则用用户的
                output = params.get("output_path")
                if output:
                    output = self._safe_path(output, allow_create_parents=True)
                else:
                    # 自动更换后缀
                    ext = target_format if target_format != "jpg" else "jpg"
                    stem = path.stem + "_processed"
                    output = path.with_name(f"{stem}.{ext}")

                output.parent.mkdir(parents=True, exist_ok=True)

                # RGBA -> RGB 转换（JPEG 不支持透明通道）
                save_img = img
                if target_format in ("jpg", "jpeg", "bmp") and img.mode in ("RGBA", "LA", "P"):
                    save_img = img.convert("RGB")

                save_kwargs: dict[str, Any] = {}
                if target_format in ("jpg", "jpeg"):
                    save_kwargs["quality"] = params.get("quality", 95)

                # Pillow 使用 "JPEG" 而非 "JPG"
                pillow_format = "JPEG" if target_format in ("jpg", "jpeg") else target_format.upper()
                save_img.save(str(output), format=pillow_format, **save_kwargs)

                logger.info(f"格式转换: {src_format} -> {target_format.upper()}")
                return {
                    "path": str(path),
                    "output_path": str(output),
                    "source_format": src_format,
                    "target_format": target_format.upper(),
                }
        except Exception as e:
            logger.error(f"格式转换失败: {e}")
            return {"error": f"格式转换失败: {e}"}

    # ------------------------------------------------------------------
    # flip — 翻转
    # ------------------------------------------------------------------

    async def _flip(self, params: dict) -> dict[str, Any]:
        """翻转图片。

        Params:
            path: 图片文件路径
            direction: 翻转方向（horizontal / vertical），默认 horizontal
            output_path: 输出路径（可选）

        Returns:
            包含翻转方向和输出路径
        """
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        try:
            direction = params.get("direction", "horizontal")

            from PIL import Image

            with Image.open(str(path)) as img:
                if direction == "vertical":
                    flipped = img.transpose(Image.FLIP_TOP_BOTTOM)
                else:
                    flipped = img.transpose(Image.FLIP_LEFT_RIGHT)

                output = self._resolve_output_path(path, params)
                output.parent.mkdir(parents=True, exist_ok=True)
                flipped.save(str(output))

                logger.info(f"翻转图片: direction={direction}")
                return {
                    "path": str(path),
                    "output_path": str(output),
                    "direction": direction,
                    "size": [flipped.width, flipped.height],
                }
        except Exception as e:
            logger.error(f"翻转图片失败: {e}")
            return {"error": f"翻转失败: {e}"}


def _human_size(size_bytes: int) -> str:
    """将字节数转换为人类可读的大小字符串。

    Args:
        size_bytes: 文件大小（字节）

    Returns:
        人类可读的大小字符串，如 "1.23 MB"
    """
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} TB"
