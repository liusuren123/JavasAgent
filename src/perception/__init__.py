"""视觉感知模块。

提供屏幕内容分析和 UI 元素定位能力。
"""

from src.perception.screen_analyzer import ScreenAnalyzer
from src.perception.window_manager import WindowInfo, WindowManager

__all__ = ["ScreenAnalyzer", "WindowInfo", "WindowManager"]
