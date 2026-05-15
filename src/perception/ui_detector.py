"""UIA 基础封装 — UI 元素检测与查找。

提供 UIElement 数据模型、UIDetector 抽象基类和 UIADetector 实现，
基于 Windows UI Automation API 进行控件树扫描和元素定位。

屏幕 DPI：3840×2160，UIA 返回的坐标为物理像素坐标。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Sequence

import uiautomation as auto

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class UIElement:
    """UI 元素数据模型。

    Attributes:
        bbox: 边界矩形 (left, top, right, bottom)，物理像素坐标。
        type: 控件类型名，如 "ButtonControl"、"EditControl"。
        text: 控件的 Name 属性文本。
        confidence: 检测置信度 0.0~1.0。UIA 来源默认为 1.0。
        source: 来源标识，如 "uia"、"ocr"、"model"。
        clickable: 是否可点击。
        actionable: 是否可交互（接受输入等）。
        element_id: 自动化 ID（AutomationId）。
    """

    bbox: tuple[int, int, int, int]
    type: str
    text: str
    confidence: float
    source: str
    clickable: bool = False
    actionable: bool = False
    element_id: str = ""

    # ---- 派生属性 ----

    @property
    def center(self) -> tuple[int, int]:
        """元素中心点坐标。"""
        left, top, right, bottom = self.bbox
        return ((left + right) // 2, (top + bottom) // 2)

    @property
    def area(self) -> int:
        """元素面积（像素²）。"""
        left, top, right, bottom = self.bbox
        return (right - left) * (bottom - top)

    @property
    def width(self) -> int:
        left, _, right, _ = self.bbox
        return right - left

    @property
    def height(self) -> int:
        _, top, _, bottom = self.bbox
        return bottom - top

    def is_on_screen(self, screen_w: int = 3840, screen_h: int = 2160) -> bool:
        """判断元素是否在屏幕可见区域内。"""
        left, top, right, bottom = self.bbox
        return left < screen_w and top < screen_h and right > 0 and bottom > 0

    def contains_point(self, x: int, y: int) -> bool:
        """判断点 (x, y) 是否在元素区域内。"""
        left, top, right, bottom = self.bbox
        return left <= x <= right and top <= y <= bottom


# ---------------------------------------------------------------------------
# 可点击 / 可交互的控件类型集合
# ---------------------------------------------------------------------------

_CLICKABLE_TYPES = frozenset({
    "ButtonControl",
    "HyperlinkControl",
    "ListItemControl",
    "MenuItemControl",
    "TabItemControl",
    "TreeItemControl",
    "CheckBoxControl",
    "RadioButtonControl",
    "SplitButtonControl",
    "ThumbControl",
    "ScrollBarControl",
    "SliderControl",
})

_ACTIONABLE_TYPES = frozenset({
    "EditControl",
    "DocumentControl",
    "ComboBoxControl",
    "SpinnerControl",
    "DataItemControl",
})

# 控件类型名 → 可点击 + 可交互
_INTERACTABLE_TYPES = _CLICKABLE_TYPES | _ACTIONABLE_TYPES


# ---------------------------------------------------------------------------
# UIDetector 抽象基类
# ---------------------------------------------------------------------------


class UIDetector(ABC):
    """UI 元素检测器抽象基类。

    子类需要实现 scan() 方法来提供具体的扫描逻辑。
    所有查找方法（find_by_*）都有默认实现，基于 scan() 结果。
    """

    @abstractmethod
    def scan(self, window_title: str | None = None) -> list[UIElement]:
        """扫描 UI 元素。

        Args:
            window_title: 窗口标题关键词。为 None 时扫描全桌面。

        Returns:
            检测到的 UIElement 列表。
        """

    # ---- 通用查找方法（基于 scan 结果） ----

    def find_by_name(
        self, name: str, exact: bool = False, window_title: str | None = None
    ) -> list[UIElement]:
        """按名称查找元素。

        Args:
            name: 要查找的名称文本。
            exact: True 为精确匹配，False 为包含匹配（模糊）。
            window_title: 限定窗口标题。

        Returns:
            匹配的 UIElement 列表。
        """
        elements = self.scan(window_title=window_title)
        if exact:
            return [e for e in elements if e.text == name]
        return [e for e in elements if name in e.text]

    def find_by_type(
        self, control_type: str, window_title: str | None = None
    ) -> list[UIElement]:
        """按控件类型查找元素。

        Args:
            control_type: 控件类型名，如 "ButtonControl"、"EditControl"。
            window_title: 限定窗口标题。

        Returns:
            匹配的 UIElement 列表。
        """
        elements = self.scan(window_title=window_title)
        return [e for e in elements if e.type == control_type]

    def find_by_text(
        self, text: str, window_title: str | None = None
    ) -> list[UIElement]:
        """按文本内容查找元素。

        Args:
            text: 要查找的文本（包含匹配）。
            window_title: 限定窗口标题。

        Returns:
            匹配的 UIElement 列表。
        """
        elements = self.scan(window_title=window_title)
        return [e for e in elements if text in e.text]

    def find_by_automation_id(
        self, automation_id: str, window_title: str | None = None
    ) -> list[UIElement]:
        """按 AutomationId 查找元素。

        Args:
            automation_id: 自动化 ID。
            window_title: 限定窗口标题。

        Returns:
            匹配的 UIElement 列表。
        """
        elements = self.scan(window_title=window_title)
        return [e for e in elements if e.element_id == automation_id]

    def find_in_area(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        window_title: str | None = None,
    ) -> list[UIElement]:
        """查找指定区域内的元素。

        以元素中心点是否在区域内来判断。

        Args:
            x1, y1: 区域左上角坐标。
            x2, y2: 区域右下角坐标。
            window_title: 限定窗口标题。

        Returns:
            中心点在区域内的 UIElement 列表。
        """
        elements = self.scan(window_title=window_title)
        results: list[UIElement] = []
        for elem in elements:
            cx, cy = elem.center
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                results.append(elem)
        return results


# ---------------------------------------------------------------------------
# UIADetector — 基于 Windows UI Automation 的实现
# ---------------------------------------------------------------------------


class UIADetector(UIDetector):
    """基于 Windows UI Automation API 的 UI 元素检测器。

    使用 uiautomation 库遍历控件树，提取元素信息。
    自动过滤 IsOffscreen=True 的不可见元素。
    """

    def __init__(self, max_depth: int = 15, max_elements: int = 2000) -> None:
        """初始化。

        Args:
            max_depth: 控件树最大遍历深度。
            max_elements: 单次扫描最大返回元素数。
        """
        self.max_depth = max_depth
        self.max_elements = max_elements

    def scan(self, window_title: str | None = None) -> list[UIElement]:
        """扫描 UI 元素。

        Args:
            window_title: 窗口标题关键词。为 None 时扫描全桌面。
                         使用包含匹配来定位窗口。

        Returns:
            检测到的 UIElement 列表。
        """
        if window_title:
            return self._scan_window(window_title)
        return self._scan_desktop()

    def _scan_desktop(self) -> list[UIElement]:
        """扫描全桌面的 UI 元素。"""
        root = auto.GetRootControl()
        results: list[UIElement] = []

        for win in root.GetChildren():
            self._collect_elements(win, results, depth=1)
            if len(results) >= self.max_elements:
                logger.warning(
                    "扫描元素数达到上限 %d，截断", self.max_elements
                )
                break

        logger.debug("桌面扫描完成，共 %d 个元素", len(results))
        return results

    def _scan_window(self, title: str) -> list[UIElement]:
        """扫描指定标题窗口的 UI 元素。"""
        root = auto.GetRootControl()
        results: list[UIElement] = []

        for win in root.GetChildren():
            win_name = win.Name or ""
            if title.lower() in win_name.lower():
                self._collect_elements(win, results, depth=1)
                if len(results) >= self.max_elements:
                    break

        logger.debug("窗口扫描[%s]完成，共 %d 个元素", title, len(results))
        return results

    def _collect_elements(
        self,
        control: auto.Control,
        results: list[UIElement],
        depth: int,
    ) -> None:
        """递归遍历控件树，收集元素。

        Args:
            control: 当前控件。
            results: 收集结果的列表。
            depth: 当前深度。
        """
        if len(results) >= self.max_elements:
            return

        if depth > self.max_depth:
            return

        # 跳过不可见元素
        try:
            if control.IsOffscreen:
                return
        except Exception:
            # 某些控件不支持此属性，跳过检查
            pass

        # 提取元素信息
        elem = self._control_to_element(control)
        if elem is not None:
            results.append(elem)

        # 递归子控件
        try:
            for child in control.GetChildren():
                self._collect_elements(child, results, depth + 1)
                if len(results) >= self.max_elements:
                    return
        except Exception:
            # 某些控件不支持 GetChildren，跳过
            pass

    @staticmethod
    def _control_to_element(control: auto.Control) -> UIElement | None:
        """将 uiautomation Control 转换为 UIElement。

        Args:
            control: uiautomation 控件对象。

        Returns:
            UIElement 或 None（如果控件信息无效）。
        """
        try:
            rect = control.BoundingRectangle
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            return None

        # 跳过空 bbox — 面积为 0 的控件无定位价值
        if bbox == (0, 0, 0, 0):
            return None

        control_type = control.ControlTypeName or ""
        name = control.Name or ""
        try:
            automation_id = control.AutomationId or ""
        except Exception:
            automation_id = ""

        # 判断是否可点击 / 可交互
        clickable = control_type in _CLICKABLE_TYPES
        actionable = control_type in _ACTIONABLE_TYPES

        return UIElement(
            bbox=bbox,
            type=control_type,
            text=name,
            confidence=1.0,
            source="uia",
            clickable=clickable,
            actionable=actionable,
            element_id=automation_id,
        )
