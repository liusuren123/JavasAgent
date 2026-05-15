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
from src.perception.vision_eye import VisionEye, VisionFrame
from src.perception.ui_detector import UIADetector, UIDetector, UIElement
from src.perception.ui_operator import (
    UIAOperator,
    UIAOperationError,
    ElementValidationError,
    OperationResult,
    OpStatus,
    PatternNotSupportedError,
)
from src.perception.ai_detector import AIDetector
from src.perception.hybrid_detector import HybridDetector
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
    "VisionEye",
    "VisionFrame",
    "TextBlock",
    "TextElement",
    "TextLocation",
    "UIADetector",
    "UIDetector",
    "UIElement",
    "UIAOperator",
    "UIAOperationError",
    "ElementValidationError",
    "OperationResult",
    "OpStatus",
    "PatternNotSupportedError",
    "AIDetector",
    "HybridDetector",
    "TimePatternTracker",
    "TimeSlot",
    "WindowInfo",
    "WindowManager",
]
