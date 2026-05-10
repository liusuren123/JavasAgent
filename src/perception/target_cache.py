"""目标缓存模块。

缓存屏幕上识别到的 UI 目标（按钮、文字、图标等），
支持按区域/类型/内容/位置查询，具有过期淘汰机制。
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass


@dataclass
class TargetInfo:
    """缓存中的目标信息。"""

    target_id: str  # 唯一标识（UUID）
    text: str  # 目标文字内容
    bbox: tuple[int, int, int, int]  # (x, y, w, h)
    center: tuple[int, int]  # (cx, cy)
    element_type: str  # "button", "menu_item", "label", "link", "text", "icon"
    confidence: float  # 识别置信度
    screen_region: str  # "top_left", "top_right", "bottom_left", "bottom_right", "center"
    created_at: float  # 创建时间戳
    source_area: tuple[int, int, int, int] | None = None  # 来源截图区域


def determine_screen_region(
    center: tuple[int, int],
    screen_width: int = 1920,
    screen_height: int = 1080,
) -> str:
    """根据目标中心坐标判断屏幕区域。

    将屏幕分成 5 个区域（四角 + 中心），返回区域名称。

    Args:
        center: 目标中心坐标 (cx, cy)
        screen_width: 屏幕宽度
        screen_height: 屏幕高度

    Returns:
        区域名称字符串
    """
    cx, cy = center
    half_w = screen_width / 2
    half_h = screen_height / 2
    # 中心区域：中间 1/4 的矩形
    center_x_min = screen_width * 0.25
    center_x_max = screen_width * 0.75
    center_y_min = screen_height * 0.25
    center_y_max = screen_height * 0.75

    if center_x_min <= cx <= center_x_max and center_y_min <= cy <= center_y_max:
        return "center"

    if cx < half_w:
        return "top_left" if cy < half_h else "bottom_left"
    else:
        return "top_right" if cy < half_h else "bottom_right"


class TargetCache:
    """屏幕目标缓存。

    支持按 ID / 文字 / 类型 / 区域 / 位置查询，
    具有 TTL 过期和容量淘汰机制。
    """

    def __init__(self, max_size: int = 500, ttl_seconds: float = 30.0) -> None:
        """初始化缓存。

        Args:
            max_size: 最大缓存条目数
            ttl_seconds: 缓存过期时间（秒）
        """
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._targets: dict[str, TargetInfo] = {}
        self._insertion_order: list[str] = []  # 按插入顺序排列的 target_id
        self._hits = 0
        self._misses = 0

    # ── 写入 ──────────────────────────────────────────

    def add(self, target: TargetInfo) -> None:
        """添加一个目标到缓存。

        如果超过 max_size，移除最旧的条目。
        如果 target_id 已存在则更新。
        """
        tid = target.target_id
        if tid in self._targets:
            # 更新已有条目
            self._targets[tid] = target
            return

        # 容量淘汰
        while len(self._targets) >= self._max_size and self._insertion_order:
            oldest_id = self._insertion_order.pop(0)
            self._targets.pop(oldest_id, None)

        self._targets[tid] = target
        self._insertion_order.append(tid)

    def add_batch(self, targets: list[TargetInfo]) -> None:
        """批量添加目标。"""
        for t in targets:
            self.add(t)

    # ── 查询 ──────────────────────────────────────────

    def get_by_id(self, target_id: str) -> TargetInfo | None:
        """按 ID 获取目标。"""
        target = self._targets.get(target_id)
        if target is None:
            self._misses += 1
            return None
        self._hits += 1
        return target

    def find_by_text(self, text: str, exact: bool = False) -> list[TargetInfo]:
        """按文字查找目标。

        Args:
            text: 搜索关键词
            exact: True 精确匹配，False 包含匹配
        """
        results: list[TargetInfo] = []
        for t in self._targets.values():
            if exact:
                if t.text == text:
                    results.append(t)
            else:
                if text in t.text:
                    results.append(t)
        return results

    def find_by_type(self, element_type: str) -> list[TargetInfo]:
        """按元素类型查找。"""
        return [t for t in self._targets.values() if t.element_type == element_type]

    def find_by_region(self, region: str) -> list[TargetInfo]:
        """按屏幕区域查找。"""
        return [t for t in self._targets.values() if t.screen_region == region]

    def find_by_bbox(
        self,
        bbox: tuple[int, int, int, int],
        tolerance: int = 10,
    ) -> list[TargetInfo]:
        """按位置区域查找。

        匹配条件：目标的 bbox 中心与给定 bbox 中心的距离在 tolerance 以内。

        Args:
            bbox: 目标位置 (x, y, w, h)
            tolerance: 像素容差
        """
        bx, by, bw, bh = bbox
        query_cx = bx + bw / 2
        query_cy = by + bh / 2

        results: list[TargetInfo] = []
        for t in self._targets.values():
            dist = math.hypot(t.center[0] - query_cx, t.center[1] - query_cy)
            if dist <= tolerance:
                results.append(t)
        return results

    def find_nearest(
        self,
        x: int,
        y: int,
        element_type: str | None = None,
    ) -> TargetInfo | None:
        """找到距离 (x, y) 最近的目标。

        Args:
            x: 查询点 x 坐标
            y: 查询点 y 坐标
            element_type: 可选，只在该类型中查找

        Returns:
            最近的目标，无结果返回 None
        """
        best: TargetInfo | None = None
        best_dist = float("inf")
        for t in self._targets.values():
            if element_type is not None and t.element_type != element_type:
                continue
            dist = math.hypot(t.center[0] - x, t.center[1] - y)
            if dist < best_dist:
                best_dist = dist
                best = t
        return best

    # ── 维护 ──────────────────────────────────────────

    def remove_expired(self) -> int:
        """移除过期目标，返回移除数量。"""
        now = time.time()
        expired_ids = [
            tid
            for tid, t in self._targets.items()
            if (now - t.created_at) > self._ttl_seconds
        ]
        for tid in expired_ids:
            del self._targets[tid]
            if tid in self._insertion_order:
                self._insertion_order.remove(tid)
        return len(expired_ids)

    def clear(self) -> None:
        """清空缓存。"""
        self._targets.clear()
        self._insertion_order.clear()
        self._hits = 0
        self._misses = 0

    # ── 属性 / 统计 ───────────────────────────────────

    @property
    def size(self) -> int:
        """当前缓存数量。"""
        return len(self._targets)

    def get_statistics(self) -> dict:
        """返回缓存统计信息。

        包含总数、各类型数量、各区域数量、命中率等。
        """
        total = self.size

        # 按类型统计
        type_counts: dict[str, int] = {}
        for t in self._targets.values():
            type_counts[t.element_type] = type_counts.get(t.element_type, 0) + 1

        # 按区域统计
        region_counts: dict[str, int] = {}
        for t in self._targets.values():
            region_counts[t.screen_region] = region_counts.get(t.screen_region, 0) + 1

        total_queries = self._hits + self._misses
        hit_rate = self._hits / total_queries if total_queries > 0 else 0.0

        return {
            "total": total,
            "type_counts": type_counts,
            "region_counts": region_counts,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
        }
