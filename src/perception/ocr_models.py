"""OCR 数据模型。

包含 OCR 引擎使用的配置和数据类。
从 ocr_engine.py 拆分出来以控制文件大小。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OcrConfig:
    """OCR 配置。"""

    engine: str = "tesseract"  # tesseract | easyocr
    lang: str = "chi_sim+eng"
    tesseract_cmd: str = ""  # tesseract 可执行文件路径（空则自动查找）
    confidence_threshold: float = 0.6  # 置信度阈值


@dataclass
class TextBlock:
    """识别到的文字块。"""

    text: str
    confidence: float
    bbox: tuple[int, int, int, int]  # (x, y, w, h)
    center: tuple[int, int]  # (cx, cy)


@dataclass
class OcrResult:
    """OCR 识别结果。"""

    full_text: str
    blocks: list[TextBlock]
    success: bool
    error: str = ""


@dataclass
class TextLocation:
    """文字定位结果。"""

    text: str
    bbox: tuple[int, int, int, int]
    center: tuple[int, int]
    confidence: float


@dataclass
class TextElement:
    """可交互文字元素。"""

    text: str
    bbox: tuple[int, int, int, int]
    center: tuple[int, int]
    element_type: str  # "button", "menu_item", "label", "link", "text"
    confidence: float
