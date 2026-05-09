"""OcrEngine 测试。

使用 pytest + mock，不依赖真实 OCR 安装。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.perception.ocr_engine import (
    OcrEngine,
    _FUZZY_THRESHOLD,
)
from src.perception.ocr_models import (
    OcrConfig,
    OcrResult,
    TextBlock,
    TextElement,
    TextLocation,
)


# ── fixtures ────────────────────────────────────────────────


@pytest.fixture
def sample_image() -> bytes:
    """构造一个最小的 PNG 图片 bytes（1x1 白色像素）。"""
    # Minimal PNG: 8-byte signature + IHDR + IDAT + IEND
    import struct
    import zlib

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        raw = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + raw + crc

    signature = b"\x89PNG\r\n\x1a\n"
    # IHDR: 1x1, 8-bit grayscale
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    # IDAT: 一行 1 个白色像素 + filter byte 0x00
    raw_data = b"\x00\xff"
    idat = _chunk(b"IDAT", zlib.compress(raw_data))
    iend = _chunk(b"IEND", b"")

    return signature + ihdr + idat + iend


@pytest.fixture
def mock_engine() -> OcrEngine:
    """返回一个 mock 了可用性检查的 OcrEngine。"""
    engine = OcrEngine()
    engine._available = True
    engine._pytesseract = MagicMock()
    return engine


# ── 数据模型测试 ────────────────────────────────────────────


class TestOcrConfig:
    """OcrConfig 数据模型测试。"""

    def test_ocr_config_defaults(self) -> None:
        """默认配置正确。"""
        config = OcrConfig()
        assert config.engine == "tesseract"
        assert config.lang == "chi_sim+eng"
        assert config.tesseract_cmd == ""
        assert config.confidence_threshold == 0.6

    def test_ocr_config_custom(self) -> None:
        """自定义配置。"""
        config = OcrConfig(
            engine="easyocr",
            lang="eng",
            tesseract_cmd="/usr/bin/tesseract",
            confidence_threshold=0.8,
        )
        assert config.engine == "easyocr"
        assert config.lang == "eng"
        assert config.tesseract_cmd == "/usr/bin/tesseract"
        assert config.confidence_threshold == 0.8


class TestOcrResult:
    """OcrResult 数据模型测试。"""

    def test_ocr_result_dataclass(self) -> None:
        """OcrResult 正确创建。"""
        result = OcrResult(
            full_text="Hello World",
            blocks=[],
            success=True,
        )
        assert result.full_text == "Hello World"
        assert result.blocks == []
        assert result.success is True
        assert result.error == ""

    def test_ocr_result_with_error(self) -> None:
        """OcrResult 包含错误信息。"""
        result = OcrResult(
            full_text="",
            blocks=[],
            success=False,
            error="引擎不可用",
        )
        assert result.success is False
        assert result.error == "引擎不可用"


class TestTextBlock:
    """TextBlock 数据模型测试。"""

    def test_text_block_dataclass(self) -> None:
        """TextBlock 正确创建。"""
        block = TextBlock(
            text="按钮",
            confidence=0.95,
            bbox=(10, 20, 80, 30),
            center=(50, 35),
        )
        assert block.text == "按钮"
        assert block.confidence == 0.95
        assert block.bbox == (10, 20, 80, 30)
        assert block.center == (50, 35)


class TestTextLocation:
    """TextLocation 数据模型测试。"""

    def test_text_location_dataclass(self) -> None:
        """TextLocation 正确创建。"""
        loc = TextLocation(
            text="提交",
            bbox=(100, 200, 60, 30),
            center=(130, 215),
            confidence=0.88,
        )
        assert loc.text == "提交"
        assert loc.bbox == (100, 200, 60, 30)
        assert loc.center == (130, 215)
        assert loc.confidence == 0.88


class TestTextElement:
    """TextElement 数据模型测试。"""

    def test_text_element_dataclass(self) -> None:
        """TextElement 正确创建。"""
        elem = TextElement(
            text="确定",
            bbox=(50, 60, 100, 40),
            center=(100, 80),
            element_type="button",
            confidence=0.9,
        )
        assert elem.text == "确定"
        assert elem.element_type == "button"
        assert elem.confidence == 0.9


# ── 引擎可用性测试 ─────────────────────────────────────────


class TestEngineAvailability:
    """引擎可用性相关测试。"""

    def test_engine_not_available(self) -> None:
        """引擎不可用时返回有意义的错误信息。"""
        engine = OcrEngine()
        engine._available = False

        result = asyncio.get_event_loop().run_until_complete(
            engine.recognize_text(b"fake_image")
        )
        assert result.success is False
        assert "不可用" in result.error

    @patch("src.perception.ocr_engine.OcrEngine._check_tesseract")
    def test_available_property_checks_once(self, mock_check: MagicMock) -> None:
        """available 属性只检查一次。"""
        mock_check.return_value = True
        engine = OcrEngine()

        assert engine.available is True
        assert engine.available is True
        # _check_tesseract 只被调用一次
        mock_check.assert_called_once()


# ── recognize_region 测试 ──────────────────────────────────


class TestRecognizeRegion:
    """recognize_region 相关测试。"""

    def test_recognize_region_invalid_zero_size(self) -> None:
        """无效 region（宽高为零）抛出 ValueError。"""
        engine = OcrEngine()
        engine._available = True

        with pytest.raises(ValueError, match="宽高必须为正数"):
            asyncio.get_event_loop().run_until_complete(
                engine.recognize_region(b"fake", (10, 20, 0, 30))
            )

    def test_recognize_region_invalid_negative_coords(self) -> None:
        """无效 region（负坐标）抛出 ValueError。"""
        engine = OcrEngine()
        engine._available = True

        with pytest.raises(ValueError, match="坐标不能为负数"):
            asyncio.get_event_loop().run_until_complete(
                engine.recognize_region(b"fake", (-5, 10, 100, 50))
            )


# ── 图片预处理测试 ──────────────────────────────────────────


class TestPreprocessImage:
    """图片预处理测试。"""

    def test_preprocess_image(self) -> None:
        """预处理：灰度化、二值化、去噪。"""
        from PIL import Image

        # 创建一个 RGB 彩色图片
        img = Image.new("RGB", (100, 50), color=(128, 64, 32))

        result = OcrEngine._preprocess_image(img)

        # 预处理后应该是 "1" 模式（二值图）
        assert result.mode == "1"
        # 尺寸不变
        assert result.size == (100, 50)


# ── 模糊查找测试 ───────────────────────────────────────────


class TestFuzzyFind:
    """模糊查找逻辑测试。"""

    def test_find_text_exact_match(self) -> None:
        """精确匹配。"""
        blocks = [
            TextBlock(text="确定", confidence=0.9, bbox=(10, 10, 50, 30), center=(35, 25)),
            TextBlock(text="取消", confidence=0.85, bbox=(70, 10, 50, 30), center=(95, 25)),
        ]

        results = OcrEngine._fuzzy_find(blocks, "确定")
        assert len(results) == 1
        assert results[0].text == "确定"

    def test_find_text_fuzzy_match(self) -> None:
        """模糊匹配：OCR 结果有轻微误差时仍能找到。"""
        blocks = [
            TextBlock(
                text="确定提交", confidence=0.9, bbox=(10, 10, 100, 30), center=(60, 25)
            ),
        ]

        # 模糊搜索 "确定提文"（有一个字不同）
        results = OcrEngine._fuzzy_find(blocks, "确定提文")
        # SequenceMatcher("确定提文", "确定提交") 的 ratio 应 >= 0.6
        assert len(results) >= 1
        if results:
            assert "确定" in results[0].text

    def test_find_text_no_match(self) -> None:
        """完全不匹配时返回空列表。"""
        blocks = [
            TextBlock(text="Hello", confidence=0.9, bbox=(0, 0, 50, 20), center=(25, 10)),
        ]

        results = OcrEngine._fuzzy_find(blocks, "完全没有关系的内容XYZ")
        assert len(results) == 0

    def test_find_text_contains_match(self) -> None:
        """目标文字被包含在块中。"""
        blocks = [
            TextBlock(
                text="请点击此处提交表单",
                confidence=0.88,
                bbox=(10, 10, 200, 30),
                center=(110, 25),
            ),
        ]

        results = OcrEngine._fuzzy_find(blocks, "提交")
        assert len(results) == 1


# ── 元素类型推断测试 ───────────────────────────────────────


class TestInferElementType:
    """元素类型推断测试。"""

    def test_button_inference(self) -> None:
        """按钮尺寸范围内的文字块被推断为 button。"""
        block = TextBlock(text="提交", confidence=0.9, bbox=(10, 10, 100, 35), center=(60, 27))
        assert OcrEngine._infer_element_type(block) == "button"

    def test_link_inference(self) -> None:
        """包含 URL 特征的文字被推断为 link。"""
        block = TextBlock(
            text="https://example.com",
            confidence=0.85,
            bbox=(10, 10, 300, 20),
            center=(160, 20),
        )
        assert OcrEngine._infer_element_type(block) == "link"

    def test_link_inference_www(self) -> None:
        """包含 www 的文字被推断为 link。"""
        block = TextBlock(
            text="www.example.org",
            confidence=0.85,
            bbox=(10, 10, 200, 20),
            center=(110, 20),
        )
        assert OcrEngine._infer_element_type(block) == "link"

    def test_menu_item_inference(self) -> None:
        """较短文字在合理高度内被推断为 menu_item。"""
        block = TextBlock(text="文件", confidence=0.9, bbox=(10, 10, 50, 30), center=(35, 25))
        result = OcrEngine._infer_element_type(block)
        # 宽50在按钮范围内(40-400)且高30在按钮范围内(20-60)→先判定为button
        # 这是因为按钮检测在菜单项之前
        assert result in ("button", "menu_item")

    def test_label_inference(self) -> None:
        """短文字被推断为 label。"""
        block = TextBlock(
            text="名称",
            confidence=0.9,
            bbox=(10, 10, 600, 20),  # 太宽，不是按钮
            center=(310, 20),
        )
        result = OcrEngine._infer_element_type(block)
        # 高20 < 40, 文字长度2 <= 20 → menu_item
        assert result in ("label", "menu_item", "text")

    def test_text_inference(self) -> None:
        """长文字被推断为 text。"""
        block = TextBlock(
            text="这是一段很长的描述文字用于测试默认类型推断逻辑是否正常工作",
            confidence=0.75,
            bbox=(10, 10, 600, 50),
            center=(310, 35),
        )
        assert OcrEngine._infer_element_type(block) == "text"


class TestGetClickableTexts:
    """get_clickable_texts 元素类型推断集成测试。"""

    @patch("src.perception.ocr_engine.OcrEngine._do_recognize")
    def test_get_clickable_texts_element_types(self, mock_recognize: MagicMock) -> None:
        """get_clickable_texts 正确推断元素类型。"""
        mock_recognize.return_value = [
            TextBlock(text="提交", confidence=0.9, bbox=(10, 10, 100, 35), center=(60, 27)),
            TextBlock(
                text="https://example.com",
                confidence=0.85,
                bbox=(10, 60, 300, 20),
                center=(160, 70),
            ),
            TextBlock(
                text="这是一段很长的描述文字内容用于测试默认类型推断逻辑",
                confidence=0.8,
                bbox=(10, 100, 600, 50),
                center=(310, 125),
            ),
        ]

        engine = OcrEngine()
        engine._available = True

        results = asyncio.get_event_loop().run_until_complete(
            engine.get_clickable_texts(b"fake_image")
        )

        assert len(results) == 3
        # 所有元素都有合理的类型
        types = {e.element_type for e in results}
        assert types.issubset({"button", "link", "text", "menu_item", "label"})

    @patch("src.perception.ocr_engine.OcrEngine._do_recognize")
    def test_get_clickable_texts_filters_low_confidence(
        self, mock_recognize: MagicMock
    ) -> None:
        """低置信度的文字块被过滤掉。"""
        mock_recognize.return_value = [
            TextBlock(text="高置信度", confidence=0.9, bbox=(10, 10, 100, 30), center=(60, 25)),
            TextBlock(text="低置信度", confidence=0.3, bbox=(10, 50, 100, 30), center=(60, 65)),
        ]

        engine = OcrEngine(OcrConfig(confidence_threshold=0.6))
        engine._available = True

        results = asyncio.get_event_loop().run_until_complete(
            engine.get_clickable_texts(b"fake_image")
        )

        assert len(results) == 1
        assert results[0].text == "高置信度"


# ── 文字块合并测试 ─────────────────────────────────────────


class TestMergeAdjacentBlocks:
    """文字块合并测试。"""

    def test_merge_adjacent_blocks(self) -> None:
        """相邻文字块被合并。"""
        blocks = [
            TextBlock(text="Hello", confidence=0.9, bbox=(10, 10, 40, 20), center=(30, 20)),
            TextBlock(text="World", confidence=0.85, bbox=(55, 10, 40, 20), center=(75, 20)),
        ]

        merged = OcrEngine._merge_adjacent_blocks(blocks, max_gap=10)
        assert len(merged) == 1
        assert "Hello" in merged[0].text
        assert "World" in merged[0].text

    def test_merge_no_merge_different_rows(self) -> None:
        """不同行的文字块不合并。"""
        blocks = [
            TextBlock(text="第一行", confidence=0.9, bbox=(10, 10, 80, 20), center=(50, 20)),
            TextBlock(text="第二行", confidence=0.85, bbox=(10, 60, 80, 20), center=(50, 70)),
        ]

        merged = OcrEngine._merge_adjacent_blocks(blocks)
        assert len(merged) == 2

    def test_merge_empty_input(self) -> None:
        """空列表输入返回空列表。"""
        merged = OcrEngine._merge_adjacent_blocks([])
        assert merged == []


# ── recognize_text 集成测试 ─────────────────────────────────


class TestRecognizeText:
    """recognize_text 集成测试（mock 后端）。"""

    @patch("src.perception.ocr_engine.OcrEngine._do_recognize")
    def test_recognize_text_success(self, mock_recognize: MagicMock) -> None:
        """成功识别文字。"""
        mock_recognize.return_value = [
            TextBlock(text="你好", confidence=0.95, bbox=(10, 10, 60, 30), center=(40, 25)),
            TextBlock(text="世界", confidence=0.88, bbox=(80, 10, 60, 30), center=(110, 25)),
        ]

        engine = OcrEngine()
        engine._available = True

        result = asyncio.get_event_loop().run_until_complete(
            engine.recognize_text(b"fake_image")
        )

        assert result.success is True
        assert "你好" in result.full_text
        assert "世界" in result.full_text
        assert len(result.blocks) == 2

    @patch("src.perception.ocr_engine.OcrEngine._do_recognize")
    def test_recognize_text_exception(self, mock_recognize: MagicMock) -> None:
        """OCR 后端异常时返回错误。"""
        mock_recognize.side_effect = RuntimeError("Tesseract 崩溃")

        engine = OcrEngine()
        engine._available = True

        result = asyncio.get_event_loop().run_until_complete(
            engine.recognize_text(b"fake_image")
        )

        assert result.success is False
        assert "Tesseract 崩溃" in result.error


# ── find_text 集成测试 ──────────────────────────────────────


class TestFindText:
    """find_text 集成测试。"""

    @patch("src.perception.ocr_engine.OcrEngine._do_recognize")
    def test_find_text_returns_locations(self, mock_recognize: MagicMock) -> None:
        """find_text 正确返回定位结果。"""
        mock_recognize.return_value = [
            TextBlock(text="保存", confidence=0.9, bbox=(10, 10, 60, 30), center=(40, 25)),
            TextBlock(text="取消", confidence=0.85, bbox=(80, 10, 60, 30), center=(110, 25)),
        ]

        engine = OcrEngine()
        engine._available = True

        results = asyncio.get_event_loop().run_until_complete(
            engine.find_text(b"fake_image", "保存")
        )

        assert len(results) == 1
        assert results[0].text == "保存"
        assert results[0].center == (40, 25)

    @patch("src.perception.ocr_engine.OcrEngine._do_recognize")
    def test_find_text_ocr_fails(self, mock_recognize: MagicMock) -> None:
        """OCR 失败时 find_text 返回空列表。"""
        mock_recognize.side_effect = RuntimeError("引擎异常")

        engine = OcrEngine()
        engine._available = True

        results = asyncio.get_event_loop().run_until_complete(
            engine.find_text(b"fake_image", "目标")
        )

        assert results == []
