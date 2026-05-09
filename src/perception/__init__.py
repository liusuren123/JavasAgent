"""视觉感知模块。

提供屏幕内容分析、UI 元素定位、OCR 文字识别和用户场景感知能力。
"""

from src.perception.context_detectors import ActivityDetector, SceneClassifier
from src.perception.context_engine import ContextEngine, TimePatternTracker
from src.perception.context_models import (
    ActivityInfo,
    ContextSnapshot,
    SceneType,
    SuggestedAction,
    TimeSlot,
)
from src.perception.ocr_engine import OcrEngine
from src.perception.ocr_models import (
    OcrConfig,
    OcrResult,
    TextBlock,
    TextElement,
    TextLocation,
)
from src.perception.screen_analyzer import ScreenAnalyzer
from src.perception.window_manager import WindowInfo, WindowManager

__all__ = [
    "ActivityDetector",
    "ActivityInfo",
    "ContextEngine",
    "ContextSnapshot",
    "OcrConfig",
    "OcrEngine",
    "OcrResult",
    "SceneClassifier",
    "SceneType",
    "ScreenAnalyzer",
    "SuggestedAction",
    "TextBlock",
    "TextElement",
    "TextLocation",
    "TimePatternTracker",
    "TimeSlot",
    "WindowInfo",
    "WindowManager",
]
