"""基于 UI 检测的拟人化操作器。

在 HybridDetector（UI 元素定位）和 HumanHand（拟人化操作）之上，
提供语义化的操作接口，调用者只需指定"点什么""输什么"，
无需关心坐标和底层操作细节。

公开 API：
- click_element(name_or_text) — 通过 UIA/OCR 定位后点击
- type_in_field(label, text) — 找到输入框后输入
- press_button(label) — 找到按钮后点击
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.perception.ui_detector import UIElement

if TYPE_CHECKING:
    from src.perception.hybrid_detector import HybridDetector
    from src.platforms.human_hand import HumanHand

logger = logging.getLogger(__name__)


@dataclass
class SmartOperatorConfig:
    """SmartOperator 配置。"""

    click_timeout: float = 5.0     # 等待元素出现的超时（秒）
    type_delay: float = 0.05       # 默认打字间隔
    retry_interval: float = 0.5    # 重试间隔（秒）
    max_retries: int = 3           # 最大重试次数


class SmartOperator:
    """基于 UI 检测的拟人化操作器。

    职责：
    1. 接收语义化的操作指令（"点击保存按钮"、"在搜索框输入 xxx"）
    2. 通过 HybridDetector 定位 UI 元素
    3. 通过 HumanHand 执行拟人化操作
    4. 返回操作结果（bool），不暴露坐标
    """

    def __init__(
        self,
        detector: HybridDetector,
        hand: HumanHand,
        config: SmartOperatorConfig | None = None,
    ) -> None:
        self._detector = detector
        self._hand = hand
        self._config = config or SmartOperatorConfig()

    # ================================================================
    # 公开 API
    # ================================================================

    async def click_element(
        self,
        name_or_text: str,
        *,
        window_title: str | None = None,
        double_click: bool = False,
        right_click: bool = False,
    ) -> bool:
        """通过名称或文本定位并点击 UI 元素。

        Args:
            name_or_text: 元素的名称/文本/类型关键词
            window_title: 限定窗口标题
            double_click: 是否双击
            right_click: 是否右键点击

        Returns:
            操作是否成功
        """
        try:
            element = await self._find_element(name_or_text, window_title)
            if element is None:
                logger.warning(f"click_element: 未找到元素 '{name_or_text}'")
                return False

            cx, cy = element.center

            if double_click:
                await self._hand.human_double_click(cx, cy)
            elif right_click:
                await self._hand.human_right_click(cx, cy)
            else:
                await self._hand.human_click(cx, cy)

            logger.info(
                f"click_element: 已点击 '{name_or_text}' "
                f"({element.type}, source={element.source})"
            )
            return True

        except Exception as e:
            logger.error(f"click_element 异常: {e}")
            return False

    async def type_in_field(
        self,
        label: str,
        text: str,
        *,
        window_title: str | None = None,
        use_paste: bool = False,
        clear_first: bool = False,
    ) -> bool:
        """在输入框中输入文字。

        自动定位输入框（Edit/Document/ComboBox），先点击聚焦，再输入。

        Args:
            label: 输入框的标签/名称
            text: 要输入的文字
            window_title: 限定窗口标题
            use_paste: 是否使用剪贴板粘贴（适合长文本）
            clear_first: 是否先清空已有内容

        Returns:
            操作是否成功
        """
        try:
            element = await self._find_editable_element(label, window_title)
            if element is None:
                logger.warning(f"type_in_field: 未找到输入框 '{label}'")
                return False

            cx, cy = element.center

            # 1. 点击聚焦
            await self._hand.human_click(cx, cy)
            await asyncio.sleep(0.1)

            # 2. 清空已有内容
            if clear_first:
                await self._hand.human_hotkey("ctrl", "a")
                await asyncio.sleep(0.05)
                await self._hand.human_press_key("delete")
                await asyncio.sleep(0.05)

            # 3. 输入文字
            if use_paste:
                await self._hand.human_paste(text)
            else:
                await self._hand.human_type(text)

            logger.info(
                f"type_in_field: 已在 '{label}' 中输入 "
                f"{'(paste)' if use_paste else ''}"
                f"{'(cleared)' if clear_first else ''}"
            )
            return True

        except Exception as e:
            logger.error(f"type_in_field 异常: {e}")
            return False

    async def press_button(
        self,
        label: str,
        *,
        window_title: str | None = None,
    ) -> bool:
        """点击按钮。

        优先选择 clickable=True 的 Button 控件。

        Args:
            label: 按钮的文本/名称
            window_title: 限定窗口标题

        Returns:
            操作是否成功
        """
        try:
            element = await self._find_clickable_element(label, window_title)
            if element is None:
                logger.warning(f"press_button: 未找到按钮 '{label}'")
                return False

            cx, cy = element.center
            await self._hand.human_click(cx, cy)

            logger.info(
                f"press_button: 已点击 '{label}' "
                f"({element.type})"
            )
            return True

        except Exception as e:
            logger.error(f"press_button 异常: {e}")
            return False

    # ================================================================
    # 元素查找（内部方法）
    # ================================================================

    async def _find_element(
        self,
        name_or_text: str,
        window_title: str | None = None,
    ) -> UIElement | None:
        """查找 UI 元素，返回置信度最高的匹配。

        Args:
            name_or_text: 查询文本
            window_title: 窗口标题

        Returns:
            最佳匹配的 UIElement，找不到返回 None
        """
        elements = self._detector.find(name_or_text, window_title=window_title)
        if not elements:
            return None
        # find 已按置信度降序排序，取第一个
        return elements[0]

    async def _find_editable_element(
        self,
        label: str,
        window_title: str | None = None,
    ) -> UIElement | None:
        """查找可编辑的 UI 元素。

        策略：
        1. 先用 label 精确查找
        2. 结果中优先选 actionable=True 的
        3. 否则退回最佳匹配
        """
        elements = self._detector.find(label, window_title=window_title)
        if not elements:
            return None

        # 优先选择 actionable 元素
        actionable = [e for e in elements if e.actionable]
        if actionable:
            return actionable[0]

        # 退回第一个（置信度最高）
        return elements[0]

    async def _find_clickable_element(
        self,
        label: str,
        window_title: str | None = None,
    ) -> UIElement | None:
        """查找可点击的 UI 元素。

        策略：
        1. 先用 label 查找
        2. 结果中优先选 clickable=True 的
        3. 否则退回最佳匹配
        """
        elements = self._detector.find(label, window_title=window_title)
        if not elements:
            return None

        # 优先选择 clickable 元素
        clickable = [e for e in elements if e.clickable]
        if clickable:
            return clickable[0]

        # 退回第一个（置信度最高）
        return elements[0]

