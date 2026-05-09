"""ImageOps 图片处理工具测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.tools.image_ops import ImageOps


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def image_ops(tmp_path: Path) -> ImageOps:
    """创建使用临时目录作为 workspace 的 ImageOps 实例。"""
    return ImageOps(workspace=str(tmp_path))


@pytest.fixture
def test_image(tmp_path: Path) -> Path:
    """生成一张 200x100 的 PNG 测试图片。"""
    from PIL import Image

    img = Image.new("RGB", (200, 100), color=(255, 0, 0))
    p = tmp_path / "test.png"
    img.save(str(p), format="PNG")
    return p


@pytest.fixture
def test_image_rgba(tmp_path: Path) -> Path:
    """生成一张 200x100 的 RGBA 测试图片（带透明通道）。"""
    from PIL import Image

    img = Image.new("RGBA", (200, 100), color=(0, 128, 255, 200))
    p = tmp_path / "test_rgba.png"
    img.save(str(p), format="PNG")
    return p


# ======================================================================
# 通用 / 错误处理
# ======================================================================


class TestImageOpsCommon:
    """通用功能和错误处理测试。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, image_ops: ImageOps) -> None:
        """未知操作应返回错误和可用操作列表。"""
        result = await image_ops.execute("nonexistent", {})
        assert "error" in result
        assert "available_actions" in result
        assert isinstance(result["available_actions"], list)

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, image_ops: ImageOps) -> None:
        """路径遍历攻击应被阻止。"""
        result = await image_ops.execute("get_info", {"path": "../../etc/passwd"})
        assert "error" in result
        assert "路径" in result["error"] or "遍历" in result["error"]

    @pytest.mark.asyncio
    async def test_file_not_found(self, image_ops: ImageOps) -> None:
        """不存在的文件应返回明确错误。"""
        result = await image_ops.execute("get_info", {"path": "not_exist.png"})
        assert "error" in result
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_pillow_not_installed(self, tmp_path: Path) -> None:
        """Pillow 未安装时应优雅降级。"""
        ops = ImageOps(workspace=str(tmp_path))
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            # 强制让 import PIL.Image 失败
            import builtins

            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "PIL" or name.startswith("PIL."):
                    raise ImportError("No module named 'PIL'")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = await ops.execute("get_info", {"path": "test.png"})
                assert "error" in result
                assert "Pillow" in result["error"]


# ======================================================================
# get_info — 获取图片信息
# ======================================================================


class TestGetInfo:
    """图片信息获取测试。"""

    @pytest.mark.asyncio
    async def test_get_info(self, image_ops: ImageOps, test_image: Path) -> None:
        """获取图片基本信息。"""
        result = await image_ops.execute("get_info", {"path": "test.png"})
        assert "error" not in result
        assert result["width"] == 200
        assert result["height"] == 100
        assert result["format"] == "PNG"
        assert result["mode"] == "RGB"
        assert result["file_size"] > 0
        assert "file_size_human" in result


# ======================================================================
# resize — 缩放图片
# ======================================================================


class TestResize:
    """图片缩放测试。"""

    @pytest.mark.asyncio
    async def test_resize_by_width_height(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """指定宽高缩放。"""
        result = await image_ops.execute(
            "resize", {"path": "test.png", "width": 100, "height": 50}
        )
        assert "error" not in result
        assert result["new_size"] == [100, 50]
        assert Path(result["output_path"]).exists()

    @pytest.mark.asyncio
    async def test_resize_by_percent(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """百分比缩放。"""
        result = await image_ops.execute(
            "resize", {"path": "test.png", "percent": 50}
        )
        assert "error" not in result
        assert result["new_size"] == [100, 50]

    @pytest.mark.asyncio
    async def test_resize_keep_ratio_width_only(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """仅指定宽度，保持比例。"""
        result = await image_ops.execute(
            "resize", {"path": "test.png", "width": 100}
        )
        assert "error" not in result
        assert result["new_size"] == [100, 50]

    @pytest.mark.asyncio
    async def test_resize_no_params(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """缺少参数时应报错。"""
        result = await image_ops.execute("resize", {"path": "test.png"})
        assert "error" in result


# ======================================================================
# crop — 裁剪图片
# ======================================================================


class TestCrop:
    """图片裁剪测试。"""

    @pytest.mark.asyncio
    async def test_crop(self, image_ops: ImageOps, test_image: Path) -> None:
        """裁剪图片到指定区域。"""
        result = await image_ops.execute(
            "crop", {"path": "test.png", "left": 10, "top": 10, "right": 110, "bottom": 60}
        )
        assert "error" not in result
        assert result["new_size"] == [100, 50]
        assert Path(result["output_path"]).exists()

    @pytest.mark.asyncio
    async def test_crop_missing_coords(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """缺少坐标参数应报错。"""
        result = await image_ops.execute("crop", {"path": "test.png", "left": 0})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_crop_out_of_bounds(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """裁剪区域超出图片范围应报错。"""
        result = await image_ops.execute(
            "crop", {"path": "test.png", "left": 0, "top": 0, "right": 999, "bottom": 999}
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_crop_invalid_box(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """裁剪区域 left>=right 应报错。"""
        result = await image_ops.execute(
            "crop", {"path": "test.png", "left": 100, "top": 0, "right": 50, "bottom": 50}
        )
        assert "error" in result


# ======================================================================
# rotate — 旋转图片
# ======================================================================


class TestRotate:
    """图片旋转测试。"""

    @pytest.mark.asyncio
    async def test_rotate_90(self, image_ops: ImageOps, test_image: Path) -> None:
        """旋转 90 度（expand=True 时宽高互换）。"""
        result = await image_ops.execute(
            "rotate", {"path": "test.png", "angle": 90, "expand": True}
        )
        assert "error" not in result
        assert result["angle"] == 90.0
        assert Path(result["output_path"]).exists()

    @pytest.mark.asyncio
    async def test_rotate_no_expand(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """不扩展画布旋转时尺寸不变。"""
        result = await image_ops.execute(
            "rotate", {"path": "test.png", "angle": 45, "expand": False}
        )
        assert "error" not in result
        assert result["new_size"] == result["original_size"]

    @pytest.mark.asyncio
    async def test_rotate_missing_angle(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """缺少角度参数应报错。"""
        result = await image_ops.execute("rotate", {"path": "test.png"})
        assert "error" in result


# ======================================================================
# convert — 格式转换
# ======================================================================


class TestConvert:
    """格式转换测试。"""

    @pytest.mark.asyncio
    async def test_convert_png_to_jpg(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """PNG 转 JPG。"""
        result = await image_ops.execute(
            "convert", {"path": "test.png", "target_format": "jpg"}
        )
        assert "error" not in result
        assert result["target_format"] == "JPG"
        output = Path(result["output_path"])
        assert output.suffix == ".jpg"
        assert output.exists()

    @pytest.mark.asyncio
    async def test_convert_png_to_webp(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """PNG 转 WEBP。"""
        result = await image_ops.execute(
            "convert", {"path": "test.png", "target_format": "webp"}
        )
        assert "error" not in result
        assert result["target_format"] == "WEBP"
        assert Path(result["output_path"]).exists()

    @pytest.mark.asyncio
    async def test_convert_rgba_to_jpg(
        self, image_ops: ImageOps, test_image_rgba: Path
    ) -> None:
        """RGBA 图片转 JPG（应自动转 RGB）。"""
        result = await image_ops.execute(
            "convert", {"path": "test_rgba.png", "target_format": "jpg"}
        )
        assert "error" not in result
        assert Path(result["output_path"]).exists()

    @pytest.mark.asyncio
    async def test_convert_unsupported_format(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """不支持的格式应报错。"""
        result = await image_ops.execute(
            "convert", {"path": "test.png", "target_format": "tiff"}
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_convert_missing_format(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """缺少目标格式应报错。"""
        result = await image_ops.execute("convert", {"path": "test.png"})
        assert "error" in result


# ======================================================================
# adjust_brightness — 调整亮度
# ======================================================================


class TestAdjustBrightness:
    """亮度调整测试。"""

    @pytest.mark.asyncio
    async def test_brightness_increase(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """增加亮度。"""
        result = await image_ops.execute(
            "adjust_brightness", {"path": "test.png", "factor": 1.5}
        )
        assert "error" not in result
        assert result["factor"] == 1.5
        assert Path(result["output_path"]).exists()

    @pytest.mark.asyncio
    async def test_brightness_decrease(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """降低亮度。"""
        result = await image_ops.execute(
            "adjust_brightness", {"path": "test.png", "factor": 0.5}
        )
        assert "error" not in result
        assert result["factor"] == 0.5

    @pytest.mark.asyncio
    async def test_brightness_missing_factor(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """缺少 factor 应报错。"""
        result = await image_ops.execute("adjust_brightness", {"path": "test.png"})
        assert "error" in result


# ======================================================================
# adjust_contrast — 调整对比度
# ======================================================================


class TestAdjustContrast:
    """对比度调整测试。"""

    @pytest.mark.asyncio
    async def test_contrast_increase(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """增加对比度。"""
        result = await image_ops.execute(
            "adjust_contrast", {"path": "test.png", "factor": 2.0}
        )
        assert "error" not in result
        assert result["factor"] == 2.0
        assert Path(result["output_path"]).exists()


# ======================================================================
# add_text_watermark — 添加文字水印
# ======================================================================


class TestAddTextWatermark:
    """文字水印测试。"""

    @pytest.mark.asyncio
    async def test_watermark_center(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """居中水印。"""
        result = await image_ops.execute(
            "add_text_watermark",
            {"path": "test.png", "text": "WATERMARK", "position": "center"},
        )
        assert "error" not in result
        assert result["text"] == "WATERMARK"
        assert result["position"] == "center"
        assert Path(result["output_path"]).exists()

    @pytest.mark.asyncio
    async def test_watermark_bottom_right(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """右下角水印。"""
        result = await image_ops.execute(
            "add_text_watermark",
            {
                "path": "test.png",
                "text": "© 2026",
                "position": "bottom-right",
                "font_size": 24,
                "opacity": 200,
            },
        )
        assert "error" not in result
        assert result["position"] == "bottom-right"

    @pytest.mark.asyncio
    async def test_watermark_missing_text(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """缺少文字应报错。"""
        result = await image_ops.execute("add_text_watermark", {"path": "test.png"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_watermark_on_rgba(
        self, image_ops: ImageOps, test_image_rgba: Path
    ) -> None:
        """在 RGBA 图片上添加水印。"""
        result = await image_ops.execute(
            "add_text_watermark",
            {"path": "test_rgba.png", "text": "TEST"},
        )
        assert "error" not in result
        assert Path(result["output_path"]).exists()


# ======================================================================
# flip — 翻转
# ======================================================================


class TestFlip:
    """图片翻转测试。"""

    @pytest.mark.asyncio
    async def test_flip_horizontal(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """水平翻转。"""
        result = await image_ops.execute(
            "flip", {"path": "test.png", "direction": "horizontal"}
        )
        assert "error" not in result
        assert result["direction"] == "horizontal"
        assert result["size"] == [200, 100]
        assert Path(result["output_path"]).exists()

    @pytest.mark.asyncio
    async def test_flip_vertical(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """垂直翻转。"""
        result = await image_ops.execute(
            "flip", {"path": "test.png", "direction": "vertical"}
        )
        assert "error" not in result
        assert result["direction"] == "vertical"
        assert result["size"] == [200, 100]

    @pytest.mark.asyncio
    async def test_flip_default_horizontal(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """默认翻转方向为水平。"""
        result = await image_ops.execute("flip", {"path": "test.png"})
        assert "error" not in result
        assert result["direction"] == "horizontal"


# ======================================================================
# thumbnail — 缩略图
# ======================================================================


class TestThumbnail:
    """缩略图生成测试。"""

    @pytest.mark.asyncio
    async def test_thumbnail_default_size(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """默认最大尺寸 200x200 生成缩略图。"""
        result = await image_ops.execute("thumbnail", {"path": "test.png"})
        assert "error" not in result
        # 200x100 图片，max=200x200，应保持 200x100（不放大）
        assert result["thumbnail_size"] == [200, 100]
        assert Path(result["output_path"]).exists()

    @pytest.mark.asyncio
    async def test_thumbnail_custom_size(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """自定义最大尺寸生成缩略图。"""
        result = await image_ops.execute(
            "thumbnail", {"path": "test.png", "max_width": 100, "max_height": 100}
        )
        assert "error" not in result
        # 200x100 缩放到 100x50
        assert result["thumbnail_size"] == [100, 50]

    @pytest.mark.asyncio
    async def test_thumbnail_suffix(
        self, image_ops: ImageOps, test_image: Path
    ) -> None:
        """缩略图输出文件名使用 _thumb 后缀。"""
        result = await image_ops.execute(
            "thumbnail", {"path": "test.png", "max_width": 50, "max_height": 50}
        )
        assert "error" not in result
        output = Path(result["output_path"])
        assert "_thumb" in output.name
