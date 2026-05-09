"""视觉感知模块。

提供屏幕内容分析、UI 元素定位和 OCR 文字识别能力。
"""

from src.perception.ocr_engine import (
    OcrConfig,
    OcrEngine,
    OcrResult,
    TextBlock,
    TextElement,
    TextLocation,
)
from src.perception.screen_analyzer import ScreenAnalyzer
from src.perception.window_manager import WindowInfo, WindowManager

__all__ = [
    "OcrConfig",
    "OcrEngine",
    "OcrResult",
    "ScreenAnalyzer",
    "TextBlock",
    "TextElement",
    "TextLocation",
    "WindowInfo",
    "WindowManager",
]
