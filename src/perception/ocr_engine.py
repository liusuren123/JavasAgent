"""OCR 文字识别引擎。

提供本地 OCR 文字识别能力，支持 Tesseract / EasyOCR 后端，
可识别屏幕截图中的文字并定位文字位置。
"""

from __future__ import annotations

import asyncio
import io
from difflib import SequenceMatcher
from pathlib import Path
from typing import Sequence

from loguru import logger

from src.perception.ocr_models import (
    OcrConfig,
    OcrResult,
    TextBlock,
    TextElement,
    TextLocation,
)


# ── 常量 ────────────────────────────────────────────────────

# 模糊匹配阈值
_FUZZY_THRESHOLD = 0.6

# 元素类型推断：宽度较窄、高度适中的文字块更可能是按钮
_BUTTON_WIDTH_RANGE = (40, 400)
_BUTTON_HEIGHT_RANGE = (20, 60)


# ── OcrEngine ──────────────────────────────────────────────


class OcrEngine:
    """本地 OCR 文字识别引擎。

    支持两种后端：
    - tesseract: 使用 pytesseract（Tesseract OCR 的 Python 封装）
    - easyocr: 使用 EasyOCR（备用方案）

    所有同步 OCR 操作通过 ``asyncio.to_thread`` 包装，
    可安全在异步上下文中调用。
    """

    def __init__(self, config: OcrConfig | None = None) -> None:
        """初始化 OCR 引擎。

        Args:
            config: OCR 配置，为 None 时使用默认配置。
        """
        self._config = config or OcrConfig()
        self._available: bool | None = None
        self._engine_type = self._config.engine

        # 延迟加载的后端引用
        self._pytesseract = None  # type: ignore[assignment]
        self._easyocr_reader = None  # type: ignore[assignment]
        self._pil_image = None  # type: ignore[assignment]

    # ── 公共属性 ────────────────────────────────────────────

    @property
    def config(self) -> OcrConfig:
        """当前 OCR 配置。"""
        return self._config

    @property
    def available(self) -> bool:
        """检查 OCR 引擎是否可用。"""
        if self._available is None:
            self._available = self._check_availability()
        return self._available

    # ── 核心方法 ────────────────────────────────────────────

    async def recognize_text(
        self,
        image: bytes,
        lang: str = "",
    ) -> OcrResult:
        """识别图片中的文字。

        Args:
            image: PNG/JPEG 格式的图片 bytes。
            lang: 语言（默认使用配置中的语言）。

        Returns:
            OcrResult 包含识别到的文字和位置信息。
        """
        if not self.available:
            return OcrResult(
                full_text="",
                blocks=[],
                success=False,
                error=f"OCR 引擎 ({self._engine_type}) 不可用，请安装对应依赖",
            )

        effective_lang = lang or self._config.lang

        try:
            blocks = await asyncio.to_thread(
                self._do_recognize, image, effective_lang
            )
            full_text = "\n".join(b.text for b in blocks if b.text.strip())
            logger.debug("OCR 识别完成：共 {} 个文字块", len(blocks))
            return OcrResult(full_text=full_text, blocks=blocks, success=True)

        except Exception as exc:
            logger.error("OCR 识别失败：{}", exc)
            return OcrResult(
                full_text="",
                blocks=[],
                success=False,
                error=str(exc),
            )

    async def recognize_region(
        self,
        image: bytes,
        region: tuple[int, int, int, int],
    ) -> OcrResult:
        """识别图片中指定区域的文字。

        Args:
            image: PNG/JPEG 格式的图片 bytes。
            region: (x, y, width, height) 裁剪区域。

        Returns:
            OcrResult。

        Raises:
            ValueError: region 参数无效时。
        """
        x, y, w, h = region
        if w <= 0 or h <= 0:
            raise ValueError(
                f"无效的 region 参数 (x={x}, y={y}, w={w}, h={h})：宽高必须为正数"
            )
        if x < 0 or y < 0:
            raise ValueError(
                f"无效的 region 参数 (x={x}, y={y}, w={w}, h={h})：坐标不能为负数"
            )

        try:
            cropped = await asyncio.to_thread(self._crop_image, image, region)
        except Exception as exc:
            logger.error("裁剪图片失败：{}", exc)
            return OcrResult(
                full_text="",
                blocks=[],
                success=False,
                error=f"裁剪图片失败：{exc}",
            )

        result = await self.recognize_text(cropped)

        # 将裁剪区域的坐标映射回原图
        if result.success:
            offset_x, offset_y = region[0], region[1]
            mapped_blocks: list[TextBlock] = []
            for block in result.blocks:
                bx, by, bw, bh = block.bbox
                mapped_blocks.append(
                    TextBlock(
                        text=block.text,
                        confidence=block.confidence,
                        bbox=(bx + offset_x, by + offset_y, bw, bh),
                        center=(block.center[0] + offset_x, block.center[1] + offset_y),
                    )
                )
            result = OcrResult(
                full_text=result.full_text,
                blocks=mapped_blocks,
                success=True,
            )

        return result

    async def find_text(
        self,
        image: bytes,
        target: str,
    ) -> list[TextLocation]:
        """在图片中查找指定文字的位置。

        使用模糊匹配以应对 OCR 不是 100% 准确的情况。

        Args:
            image: PNG/JPEG 格式的图片 bytes。
            target: 要查找的文字。

        Returns:
            匹配到的文字位置列表（可能多个）。
        """
        result = await self.recognize_text(image)

        if not result.success:
            logger.warning("find_text：OCR 识别失败，无法查找「{}」", target)
            return []

        return self._fuzzy_find(result.blocks, target)

    async def get_clickable_texts(
        self,
        image: bytes,
    ) -> list[TextElement]:
        """提取图片中所有可点击的文字元素。

        用于辅助 UI 操作，识别按钮、菜单项等文字元素。
        基于文字块的大小、位置、置信度推断元素类型。

        Args:
            image: PNG/JPEG 格式的图片 bytes。

        Returns:
            文字元素列表，包含文字内容和位置。
        """
        result = await self.recognize_text(image)

        if not result.success:
            logger.warning("get_clickable_texts：OCR 识别失败")
            return []

        elements: list[TextElement] = []
        for block in result.blocks:
            if block.confidence < self._config.confidence_threshold:
                continue
            element_type = self._infer_element_type(block)
            elements.append(
                TextElement(
                    text=block.text,
                    bbox=block.bbox,
                    center=block.center,
                    element_type=element_type,
                    confidence=block.confidence,
                )
            )

        logger.debug("提取到 {} 个可交互文字元素", len(elements))
        return elements

    # ── 内部方法：可用性检查 ────────────────────────────────

    def _check_availability(self) -> bool:
        """检查 OCR 引擎依赖是否可用。"""
        if self._engine_type == "tesseract":
            return self._check_tesseract()
        if self._engine_type == "easyocr":
            return self._check_easyocr()

        logger.warning("未知 OCR 引擎类型：{}，尝试 tesseract", self._engine_type)
        self._engine_type = "tesseract"
        return self._check_tesseract()

    def _check_tesseract(self) -> bool:
        """检查 Tesseract 是否可用。"""
        try:
            import pytesseract  # noqa: F401

            self._pytesseract = pytesseract

            # 如果用户指定了 tesseract_cmd，先设置
            if self._config.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self._config.tesseract_cmd

            # 尝试获取 tesseract 版本以验证安装
            pytesseract.get_tesseract_version()
            logger.info("Tesseract OCR 引擎可用")
            return True

        except ImportError:
            logger.info("pytesseract 未安装，尝试 EasyOCR 作为备用")
            return self._check_easyocr()
        except Exception as exc:
            logger.warning("Tesseract 不可用：{}，尝试 EasyOCR 作为备用", exc)
            return self._check_easyocr()

    def _check_easyocr(self) -> bool:
        """检查 EasyOCR 是否可用。"""
        try:
            import easyocr

            # 延迟创建 reader（首次较慢）
            self._easyocr_reader = easyocr.Reader(["ch_sim", "en"], verbose=False)
            self._engine_type = "easyocr"
            logger.info("EasyOCR 引擎可用")
            return True
        except ImportError:
            logger.warning("EasyOCR 也未安装，OCR 功能不可用")
            return False
        except Exception as exc:
            logger.warning("EasyOCR 初始化失败：{}", exc)
            return False

    # ── 内部方法：OCR 执行 ──────────────────────────────────

    def _do_recognize(
        self, image: bytes, lang: str
    ) -> list[TextBlock]:
        """同步执行 OCR 识别（在 to_thread 中调用）。"""
        pil_image = self._load_image(image)

        # 图片预处理
        pil_image = self._preprocess_image(pil_image)

        if self._engine_type == "tesseract" and self._pytesseract is not None:
            return self._recognize_tesseract(pil_image, lang)
        if self._engine_type == "easyocr" and self._easyocr_reader is not None:
            return self._recognize_easyocr(pil_image)

        raise RuntimeError(f"没有可用的 OCR 引擎（尝试过：{self._config.engine}）")

    def _recognize_tesseract(
        self, pil_image: object, lang: str
    ) -> list[TextBlock]:
        """使用 Tesseract 执行 OCR。"""
        import pytesseract

        # 获取详细识别结果（包含位置和置信度）
        data = pytesseract.image_to_data(
            pil_image, lang=lang, output_type=pytesseract.Output.DICT
        )

        blocks: list[TextBlock] = []
        n_boxes = len(data["text"])

        for i in range(n_boxes):
            text = data["text"][i].strip()
            conf = int(data["conf"][i])

            if not text or conf < 0:
                continue

            confidence = conf / 100.0
            x = int(data["left"][i])
            y = int(data["top"][i])
            w = int(data["width"][i])
            h = int(data["height"][i])

            blocks.append(
                TextBlock(
                    text=text,
                    confidence=confidence,
                    bbox=(x, y, w, h),
                    center=(x + w // 2, y + h // 2),
                )
            )

        # 合并相邻文字块（同一行的文字）
        blocks = self._merge_adjacent_blocks(blocks)

        return blocks

    def _recognize_easyocr(
        self, pil_image: object
    ) -> list[TextBlock]:
        """使用 EasyOCR 执行 OCR。"""
        results = self._easyocr_reader.readtext(pil_image)  # type: ignore[union-attr]

        blocks: list[TextBlock] = []
        for bbox_pts, text, confidence in results:
            if not text.strip():
                continue

            # EasyOCR 返回四角坐标 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            xs = [p[0] for p in bbox_pts]
            ys = [p[1] for p in bbox_pts]
            x = int(min(xs))
            y = int(min(ys))
            w = int(max(xs) - x)
            h = int(max(ys) - y)

            blocks.append(
                TextBlock(
                    text=text,
                    confidence=confidence,
                    bbox=(x, y, w, h),
                    center=(x + w // 2, y + h // 2),
                )
            )

        return blocks

    # ── 内部方法：图片处理 ──────────────────────────────────

    @staticmethod
    def _load_image(image: bytes) -> object:
        """从 bytes 加载 PIL Image。"""
        from PIL import Image

        return Image.open(io.BytesIO(image))

    @staticmethod
    def _preprocess_image(pil_image: object) -> object:
        """图片预处理：灰度化、二值化、去噪。

        提升 OCR 识别准确率。

        Args:
            pil_image: PIL.Image 对象。

        Returns:
            预处理后的 PIL.Image 对象。
        """
        from PIL import Image, ImageFilter

        img = pil_image

        # 转灰度
        if img.mode != "L":
            img = img.convert("L")

        # 二值化（自适应阈值）
        threshold = 128
        img = img.point(lambda p: 255 if p > threshold else 0, "1")

        # 去噪
        img = img.filter(ImageFilter.MedianFilter(size=3))

        return img

    @staticmethod
    def _crop_image(
        image: bytes, region: tuple[int, int, int, int]
    ) -> bytes:
        """裁剪图片的指定区域。

        Args:
            image: 原图 bytes。
            region: (x, y, width, height)。

        Returns:
            裁剪后的图片 bytes。
        """
        from PIL import Image

        img = Image.open(io.BytesIO(image))
        x, y, w, h = region
        cropped = img.crop((x, y, x + w, y + h))

        buf = io.BytesIO()
        cropped.save(buf, format="PNG")
        return buf.getvalue()

    # ── 内部方法：文字块合并 ─────────────────────────────────

    @staticmethod
    def _merge_adjacent_blocks(
        blocks: list[TextBlock],
        max_gap: int = 10,
    ) -> list[TextBlock]:
        """合并同一行中相邻的文字块。

        Tesseract 返回的粒度较细（单词级别），合并后更便于定位。

        Args:
            blocks: 原始文字块列表。
            max_gap: 最大间隔像素（小于此值则合并）。

        Returns:
            合并后的文字块列表。
        """
        if not blocks:
            return []

        # 按 y 坐标排序后再按 x 排序
        sorted_blocks = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))

        merged: list[TextBlock] = []
        current = sorted_blocks[0]

        for block in sorted_blocks[1:]:
            # 判断是否在同一行（y 中心接近）且相邻（x 间隔小于阈值）
            same_row = abs(block.center[1] - current.center[1]) < max(
                current.bbox[3], block.bbox[3]
            )
            adjacent = (block.bbox[0] - (current.bbox[0] + current.bbox[2])) < max_gap

            if same_row and adjacent:
                # 合并
                x1 = min(current.bbox[0], block.bbox[0])
                y1 = min(current.bbox[1], block.bbox[1])
                x2 = max(
                    current.bbox[0] + current.bbox[2],
                    block.bbox[0] + block.bbox[2],
                )
                y2 = max(
                    current.bbox[1] + current.bbox[3],
                    block.bbox[1] + block.bbox[3],
                )

                merged_text = current.text + " " + block.text
                merged_conf = max(current.confidence, block.confidence)
                merged_bbox = (x1, y1, x2 - x1, y2 - y1)
                merged_center = (x1 + (x2 - x1) // 2, y1 + (y2 - y1) // 2)

                current = TextBlock(
                    text=merged_text,
                    confidence=merged_conf,
                    bbox=merged_bbox,
                    center=merged_center,
                )
            else:
                merged.append(current)
                current = block

        merged.append(current)
        return merged

    # ── 内部方法：模糊查找 ──────────────────────────────────

    @staticmethod
    def _fuzzy_find(
        blocks: list[TextBlock], target: str
    ) -> list[TextLocation]:
        """在文字块中模糊查找目标文字。

        使用 ``difflib.SequenceMatcher`` 进行模糊匹配，
        以应对 OCR 不是 100% 准确的情况。

        Args:
            blocks: OCR 识别到的文字块。
            target: 要查找的目标文字。

        Returns:
            匹配到的文字位置列表。
        """
        locations: list[TextLocation] = []

        for block in blocks:
            # 完全包含
            if target in block.text:
                locations.append(
                    TextLocation(
                        text=block.text,
                        bbox=block.bbox,
                        center=block.center,
                        confidence=block.confidence,
                    )
                )
                continue

            # 模糊匹配
            ratio = SequenceMatcher(None, target, block.text).ratio()
            if ratio >= _FUZZY_THRESHOLD:
                locations.append(
                    TextLocation(
                        text=block.text,
                        bbox=block.bbox,
                        center=block.center,
                        confidence=block.confidence * ratio,
                    )
                )

        return locations

    # ── 内部方法：元素类型推断 ───────────────────────────────

    @staticmethod
    def _infer_element_type(block: TextBlock) -> str:
        """基于文字块特征推断 UI 元素类型。

        推断规则：
        - 宽度在按钮范围内且高度在按钮范围内 → button
        - 文字较短且居中 → menu_item
        - 带有链接特征（http / www / .com）→ link
        - 较短的单行文字 → label
        - 其他 → text

        Args:
            block: 文字块。

        Returns:
            推断的元素类型字符串。
        """
        text = block.text.strip()
        x, y, w, h = block.bbox

        # 链接检测
        link_indicators = ("http", "www.", ".com", ".cn", ".org", ".net")
        if any(ind in text.lower() for ind in link_indicators):
            return "link"

        # 按钮检测：尺寸在合理范围内
        bw_min, bw_max = _BUTTON_WIDTH_RANGE
        bh_min, bh_max = _BUTTON_HEIGHT_RANGE
        if bw_min <= w <= bw_max and bh_min <= h <= bh_max:
            return "button"

        # 菜单项：较短文字，通常在左侧
        if len(text) <= 20 and h <= 40:
            return "menu_item"

        # 标签：较短文字
        if len(text) <= 10:
            return "label"

        return "text"
