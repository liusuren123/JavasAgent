"""VisionEye 视觉感知器。

整合 ScreenAnalyzer + TargetCache + TargetMatcher 形成统一视觉管线，
提供截图分析、目标查找、元素定位等能力的统一入口。
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field

from loguru import logger

from src.perception.screen_analyzer import ScreenAnalyzer
from src.perception.target_cache import TargetCache, TargetInfo, determine_screen_region
from src.perception.target_matcher import MatchLevel, MatchResult, TargetMatcher
from src.utils.config import PerceptionConfig
from src.utils.llm_client import LLMClient


@dataclass
class VisionFrame:
    """一次视觉感知的结果帧。"""

    frame_id: str  # UUID
    timestamp: float  # time.time()
    description: str  # 屏幕描述
    targets: list[TargetInfo]  # 识别到的所有目标
    width: int  # 屏幕宽度
    height: int  # 屏幕高度


# UI 元素类型关键词映射
_ELEMENT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "button": ["按钮", "按键", "button", "btn"],
    "menu_item": ["菜单", "菜单项", "menu", "选项"],
    "link": ["链接", "超链接", "link"],
    "input": ["输入框", "文本框", "input", "搜索框"],
    "label": ["标签", "标题", "label", "文本"],
    "icon": ["图标", "icon"],
}


class VisionEye:
    """视觉感知器 —— 视觉层的核心协调器。

    整合 ScreenAnalyzer、TargetCache、TargetMatcher，
    提供 capture_and_analyze / find_target / locate_on_screen 统一接口。

    Usage::

        eye = VisionEye(llm_client, config)
        frame = await eye.capture_and_analyze(screenshot_bytes)
        result = await eye.find_target("保存按钮")
        coords = await eye.locate_on_screen(screenshot_bytes, "关闭图标")
    """

    def __init__(self, llm: LLMClient, config: PerceptionConfig) -> None:
        self._analyzer = ScreenAnalyzer(llm, config)
        self._cache = TargetCache()
        self._matcher = TargetMatcher(self._cache)
        self._config = config
        self._frame_count = 0
        self._last_frame: VisionFrame | None = None

    # ── 核心管线 ──────────────────────────────────────

    async def capture_and_analyze(
        self,
        screenshot: bytes,
        screen_width: int = 1920,
        screen_height: int = 1080,
    ) -> VisionFrame:
        """截图分析完整管线：describe → 从描述中提取目标 → 缓存 → 返回 VisionFrame。

        Args:
            screenshot: PNG 格式的截图 bytes
            screen_width: 屏幕宽度
            screen_height: 屏幕高度

        Returns:
            VisionFrame 包含描述、目标列表、屏幕尺寸
        """
        # 如果感知模块被禁用，返回空帧
        if not self._config.enabled:
            frame = VisionFrame(
                frame_id=uuid.uuid4().hex,
                timestamp=time.time(),
                description="",
                targets=[],
                width=screen_width,
                height=screen_height,
            )
            self._frame_count += 1
            self._last_frame = frame
            logger.debug("视觉感知模块已禁用，返回空 VisionFrame")
            return frame

        # 1. 屏幕描述
        description = await self._analyzer.describe(screenshot)

        # 2. 从描述中提取目标
        targets = self._extract_targets_from_description(
            description, screen_width, screen_height
        )

        # 3. 缓存目标
        self._cache.add_batch(targets)

        # 4. 构建 VisionFrame
        frame = VisionFrame(
            frame_id=uuid.uuid4().hex,
            timestamp=time.time(),
            description=description,
            targets=targets,
            width=screen_width,
            height=screen_height,
        )

        self._frame_count += 1
        self._last_frame = frame
        logger.debug(
            f"VisionFrame #{self._frame_count}: "
            f"描述长度={len(description)}, 目标数={len(targets)}"
        )
        return frame

    async def find_target(
        self,
        query: str,
        target_type: str | None = None,
        region: str | None = None,
    ) -> MatchResult | None:
        """在缓存中查找目标（三级匹配：exact → fuzzy → semantic）。

        Args:
            query: 查询文本
            target_type: 可选，按元素类型过滤
            region: 可选，按屏幕区域过滤

        Returns:
            MatchResult 或 None（无匹配时）
        """
        return self._matcher.match(query, target_type=target_type, region=region)

    async def locate_on_screen(
        self, screenshot: bytes, target_desc: str
    ) -> tuple[int, int] | None:
        """在屏幕上定位目标元素（委托给 ScreenAnalyzer.locate）。

        Args:
            screenshot: PNG 格式的截图 bytes
            target_desc: 目标描述

        Returns:
            (x, y) 坐标元组，未找到返回 None
        """
        result = await self._analyzer.locate(screenshot, target_desc)
        if result.found and result.x is not None and result.y is not None:
            return (result.x, result.y)
        return None

    # ── 缓存管理 ──────────────────────────────────────

    def refresh_cache(self) -> int:
        """清理过期目标，返回移除数量。"""
        return self._cache.remove_expired()

    def get_cache_stats(self) -> dict:
        """返回缓存统计信息。"""
        return self._cache.get_statistics()

    # ── 目标提取（从描述文本中）──────────────────────────

    def _extract_targets_from_description(
        self,
        description: str,
        screen_width: int = 1920,
        screen_height: int = 1080,
    ) -> list[TargetInfo]:
        """从屏幕描述中提取 UI 目标信息（启发式解析，不依赖外部 NLP）。

        简单策略：按行分析描述文本，检测括号内的坐标信息如 (x, y, w, h)
        或类似格式，以及检测按钮/菜单/链接等关键词标记的元素类型。
        如果无法提取坐标，使用合理的默认分布。

        Args:
            description: 屏幕描述文本
            screen_width: 屏幕宽度（用于默认坐标和区域计算）
            screen_height: 屏幕高度（用于默认坐标和区域计算）

        Returns:
            提取到的 TargetInfo 列表
        """
        if not description or not description.strip():
            return []

        targets: list[TargetInfo] = []
        lines = description.split("\n")

        # 收集包含 UI 关键词的行
        element_lines: list[tuple[int, str]] = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            # 检测是否包含 UI 元素关键词
            lower = stripped.lower()
            has_keyword = any(
                kw in lower for kws in _ELEMENT_TYPE_KEYWORDS.values() for kw in kws
            )
            if has_keyword:
                element_lines.append((i, stripped))

        # 如果没有检测到明确的 UI 元素行，尝试从每行中提取
        if not element_lines:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped and len(stripped) > 1:
                    element_lines.append((i, stripped))

        total = len(element_lines)
        for idx, (line_idx, text) in enumerate(element_lines):
            # 尝试提取坐标 (x, y, w, h) 或 [x, y, w, h]
            bbox = self._try_extract_bbox(text, idx, total, screen_width, screen_height)

            # 推断元素类型
            element_type = self._infer_element_type(text)

            # 清理文本：移除坐标信息，只保留描述文字
            clean_text = self._clean_element_text(text)

            cx = bbox[0] + bbox[2] // 2
            cy = bbox[1] + bbox[3] // 2
            center = (cx, cy)
            region = determine_screen_region(center, screen_width, screen_height)

            target = TargetInfo(
                target_id=uuid.uuid4().hex,
                text=clean_text,
                bbox=bbox,
                center=center,
                element_type=element_type,
                confidence=0.7,  # 启发式提取默认置信度
                screen_region=region,
                created_at=time.time(),
            )
            targets.append(target)

        return targets

    # ── 属性 ──────────────────────────────────────────

    @property
    def last_frame(self) -> VisionFrame | None:
        """最后一次 capture_and_analyze 的结果帧。"""
        return self._last_frame

    @property
    def cache(self) -> TargetCache:
        """内部 TargetCache 实例。"""
        return self._cache

    @property
    def matcher(self) -> TargetMatcher:
        """内部 TargetMatcher 实例。"""
        return self._matcher

    @property
    def frame_count(self) -> int:
        """已处理的帧数。"""
        return self._frame_count

    # ── 内部工具方法 ──────────────────────────────────

    @staticmethod
    def _try_extract_bbox(
        text: str,
        index: int,
        total: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[int, int, int, int]:
        """尝试从文本中提取 bbox 坐标，失败时使用网格默认分布。

        尝试匹配格式：
        - (x, y, w, h) 或 [x, y, w, h]
        - x:N, y:N, w:N, h:N
        """
        # 模式 1: (x, y, w, h) 或 [x, y, w, h]
        m = re.search(
            r"[\(\[]\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*[\)\]]",
            text,
        )
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))

        # 模式 2: x:N, y:N, w:N, h:N
        xm = re.search(r"x\s*[:=]\s*(\d+)", text, re.IGNORECASE)
        ym = re.search(r"y\s*[:=]\s*(\d+)", text, re.IGNORECASE)
        wm = re.search(r"w(?:idth)?\s*[:=]\s*(\d+)", text, re.IGNORECASE)
        hm = re.search(r"h(?:eight)?\s*[:=]\s*(\d+)", text, re.IGNORECASE)
        if xm and ym and wm and hm:
            return (
                int(xm.group(1)),
                int(ym.group(1)),
                int(wm.group(1)),
                int(hm.group(1)),
            )

        # 默认分布：在屏幕上按行列网格排列
        cols = min(3, max(1, total))
        row = index // cols
        col = index % cols
        cell_w = screen_width // cols
        rows_needed = (total + cols - 1) // cols
        cell_h = screen_height // max(1, rows_needed)

        x = col * cell_w + cell_w // 4
        y = row * cell_h + cell_h // 4
        w = cell_w // 2
        h = 40  # 默认 UI 元素高度
        return (x, y, w, h)

    @staticmethod
    def _infer_element_type(text: str) -> str:
        """根据文本内容推断元素类型。"""
        lower = text.lower()
        for etype, keywords in _ELEMENT_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in lower:
                    return etype
        return "text"

    @staticmethod
    def _clean_element_text(text: str) -> str:
        """清理元素文本，移除坐标和标记符号。"""
        # 移除 (x, y, w, h) 格式的坐标
        cleaned = re.sub(
            r"[\(\[]\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*[\)\]]",
            "",
            text,
        )
        # 移除 x:N, y:N 类型的坐标
        cleaned = re.sub(
            r"[,;]?\s*(x|y|w(?:idth)?|h(?:eight)?)\s*[:=]\s*\d+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        # 移除行首的列表标记
        cleaned = re.sub(r"^[\s\d\.\-\*•#]+", "", cleaned).strip()
        # 移除多余空白
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned if cleaned else text.strip()
