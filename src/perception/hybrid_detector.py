"""混合 UI 元素检测器。

融合 UIA（精确但覆盖率有限）和 AI（覆盖率高但精度一般）的检测结果，
提供最优的 UI 元素检测能力。

策略：UIA 优先 → AI 补充 → 去重合并
"""

from __future__ import annotations

import logging
from typing import Sequence

from PIL import ImageGrab

from src.perception.ai_detector import AIDetector
from src.perception.ui_detector import UIADetector, UIElement

logger = logging.getLogger(__name__)

# 重叠阈值：两个元素重叠面积占较小元素面积的比例超过此值则视为重复
OVERLAP_THRESHOLD = 0.5


class HybridDetector:
    """混合 UI 元素检测器：UIA + AI 融合。"""

    def __init__(self) -> None:
        self.uia_detector = UIADetector()
        self.ai_detector = AIDetector()

    def detect(
        self,
        window_title: str | None = None,
        use_ai: bool = True,
    ) -> list[UIElement]:
        """检测 UI 元素，UIA 优先 + AI 补充。

        Args:
            window_title: 目标窗口标题（None 则扫描全桌面）
            use_ai: 是否启用 AI 补充检测

        Returns:
            合并去重后的 UIElement 列表
        """
        # 阶段 1：UIA 检测
        uia_elements: list[UIElement] = []
        try:
            uia_elements = self.uia_detector.scan(window_title)
            logger.info(f"UIA 检测到 {len(uia_elements)} 个元素")
        except Exception as e:
            logger.warning(f"UIA 检测失败: {e}")

        if not use_ai:
            return uia_elements

        # 阶段 2：截图 + AI 检测
        ai_elements: list[UIElement] = []
        try:
            screenshot = ImageGrab.grab()
            ai_elements = self.ai_detector.detect(screenshot)
            logger.info(f"AI 检测到 {len(ai_elements)} 个元素")
        except Exception as e:
            logger.warning(f"AI 检测失败: {e}")

        # 阶段 3：融合去重
        merged = self._merge(uia_elements, ai_elements)
        logger.info(f"合并后共 {len(merged)} 个元素")
        return merged

    def find(
        self,
        query: str,
        window_title: str | None = None,
    ) -> list[UIElement]:
        """自然语言查找 UI 元素。

        支持的查询模式：
        - "输入框" / "input" → 查找 Edit/Document 类型
        - "按钮" / "button" → 查找 Button 类型
        - "保存" → 按名称查找含"保存"的元素
        - 其他 → 同时按名称和类型模糊匹配

        Args:
            query: 查询文本
            window_title: 目标窗口

        Returns:
            匹配的 UIElement 列表
        """
        elements = self.detect(window_title)

        query_lower = query.lower().strip()

        # 类型映射
        type_mapping = {
            "输入框": "edit", "input": "edit", "textbox": "edit",
            "编辑": "edit", "搜索框": "edit",
            "按钮": "button", "button": "button",
            "链接": "hyperlink", "link": "hyperlink",
            "复选框": "checkbox", "checkbox": "checkbox",
            "下拉": "combobox", "dropdown": "combobox", "select": "combobox",
            "标签": "text", "label": "text", "text": "text",
            "菜单": "menu", "menu": "menu",
            "标签页": "tab", "tab": "tab",
            "表格": "table", "table": "table",
            "图片": "image", "image": "image",
        }

        target_type = type_mapping.get(query_lower)
        results: list[UIElement] = []

        for elem in elements:
            matched = False

            # 按类型匹配
            if target_type and target_type in elem.type.lower():
                matched = True

            # 按名称/文本匹配
            if query_lower in elem.text.lower():
                matched = True

            # 按类型名称匹配（模糊）
            if query_lower in elem.type.lower():
                matched = True

            if matched:
                results.append(elem)

        # 按置信度排序
        results.sort(key=lambda e: e.confidence, reverse=True)
        return results

    def find_in_area(
        self,
        x1: int, y1: int, x2: int, y2: int,
        window_title: str | None = None,
    ) -> list[UIElement]:
        """查找指定区域内的 UI 元素。

        Args:
            x1, y1, x2, y2: 区域坐标
            window_title: 目标窗口

        Returns:
            在指定区域内的 UIElement 列表
        """
        elements = self.detect(window_title)
        results = []
        for elem in elements:
            if elem.is_on_screen:
                ex1, ey1, ex2, ey2 = elem.bbox
                # 检查元素中心是否在区域内
                cx, cy = elem.center
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    results.append(elem)
        return results

    # -----------------------------------------------------------------------
    # 融合逻辑
    # -----------------------------------------------------------------------

    def _merge(
        self,
        uia_elements: list[UIElement],
        ai_elements: list[UIElement],
    ) -> list[UIElement]:
        """融合 UIA 和 AI 检测结果。

        规则：
        1. UIA 结果全部保留（坐标精确）
        2. AI 结果与 UIA 重叠 >50% 的丢弃
        3. AI 独有的结果保留，但置信度降低
        """
        merged = list(uia_elements)

        for ai_elem in ai_elements:
            is_duplicate = False
            for uia_elem in uia_elements:
                overlap = self._calc_overlap(ai_elem.bbox, uia_elem.bbox)
                if overlap > OVERLAP_THRESHOLD:
                    is_duplicate = True
                    break

            if not is_duplicate:
                # AI 独有的元素，降低置信度
                ai_elem.confidence *= 0.7
                merged.append(ai_elem)

        return merged

    @staticmethod
    def _calc_overlap(
        bbox1: tuple[int, int, int, int],
        bbox2: tuple[int, int, int, int],
    ) -> float:
        """计算两个 bbox 的重叠比例（IoU-like）。

        返回重叠面积占较小 bbox 面积的比例。
        """
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])

        if x1 >= x2 or y1 >= y2:
            return 0.0

        overlap_area = (x2 - x1) * (y2 - y1)
        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
        smaller_area = min(area1, area2)

        if smaller_area == 0:
            return 0.0

        return overlap_area / smaller_area
