"""TargetCache 目标缓存测试。"""

from __future__ import annotations

import time
import uuid

import pytest

from src.perception.target_cache import TargetCache, TargetInfo, determine_screen_region


# ── fixture ────────────────────────────────────────────


def _make_target(
    *,
    text: str = "按钮",
    bbox: tuple[int, int, int, int] = (100, 100, 80, 40),
    center: tuple[int, int] = (140, 120),
    element_type: str = "button",
    confidence: float = 0.95,
    screen_region: str = "center",
    created_at: float | None = None,
) -> TargetInfo:
    """快速构造 TargetInfo 用于测试。"""
    return TargetInfo(
        target_id=str(uuid.uuid4()),
        text=text,
        bbox=bbox,
        center=center,
        element_type=element_type,
        confidence=confidence,
        screen_region=screen_region,
        created_at=created_at or time.time(),
    )


@pytest.fixture
def cache() -> TargetCache:
    """默认缓存实例。"""
    return TargetCache(max_size=50, ttl_seconds=30.0)


@pytest.fixture
def small_cache() -> TargetCache:
    """容量为 3 的小缓存，用于测试淘汰。"""
    return TargetCache(max_size=3, ttl_seconds=30.0)


@pytest.fixture
def sample_targets() -> list[TargetInfo]:
    """一组样本目标。"""
    return [
        _make_target(text="保存", center=(200, 300), element_type="button", screen_region="top_left"),
        _make_target(text="取消", center=(400, 300), element_type="button", screen_region="top_right"),
        _make_target(text="文件菜单", center=(100, 600), element_type="menu_item", screen_region="bottom_left"),
        _make_target(text="帮助链接", center=(1700, 800), element_type="link", screen_region="bottom_right"),
        _make_target(text="用户名", center=(960, 540), element_type="label", screen_region="center"),
    ]


# ── TargetInfo 数据类 ──────────────────────────────────


def test_target_info_creation() -> None:
    """验证 TargetInfo 数据类能正确创建，字段值正确。"""
    now = time.time()
    t = TargetInfo(
        target_id="test-id-123",
        text="确认",
        bbox=(10, 20, 100, 50),
        center=(60, 45),
        element_type="button",
        confidence=0.88,
        screen_region="top_left",
        created_at=now,
        source_area=(0, 0, 500, 500),
    )
    assert t.target_id == "test-id-123"
    assert t.text == "确认"
    assert t.bbox == (10, 20, 100, 50)
    assert t.center == (60, 45)
    assert t.element_type == "button"
    assert t.confidence == 0.88
    assert t.screen_region == "top_left"
    assert t.created_at == now
    assert t.source_area == (0, 0, 500, 500)


def test_target_info_default_source_area() -> None:
    """source_area 默认为 None。"""
    t = _make_target()
    assert t.source_area is None


# ── determine_screen_region ────────────────────────────


def test_determine_screen_region_center() -> None:
    """中心区域判断。"""
    # 正中心
    assert determine_screen_region((960, 540)) == "center"
    # 中心边界内
    assert determine_screen_region((500, 300)) == "center"
    assert determine_screen_region((1400, 700)) == "center"


def test_determine_screen_region_corners() -> None:
    """四角区域判断。"""
    assert determine_screen_region((100, 100)) == "top_left"
    assert determine_screen_region((1800, 100)) == "top_right"
    assert determine_screen_region((100, 1000)) == "bottom_left"
    assert determine_screen_region((1800, 1000)) == "bottom_right"


# ── 基本增删查 ──────────────────────────────────────────


def test_cache_add_and_get_by_id(cache: TargetCache) -> None:
    """添加后能按 ID 获取。"""
    t = _make_target(text="测试按钮")
    cache.add(t)
    assert cache.size == 1
    got = cache.get_by_id(t.target_id)
    assert got is not None
    assert got.text == "测试按钮"
    assert got.target_id == t.target_id


def test_cache_add_exceeds_max_size(small_cache: TargetCache) -> None:
    """超过 max_size 时自动移除最旧的。"""
    targets = [_make_target(text=f"T{i}") for i in range(5)]
    for t in targets:
        small_cache.add(t)
    # max_size=3，所以只保留最后 3 个
    assert small_cache.size == 3
    # 最旧的 2 个应该被移除
    assert small_cache.get_by_id(targets[0].target_id) is None
    assert small_cache.get_by_id(targets[1].target_id) is None
    # 最新的 3 个保留
    assert small_cache.get_by_id(targets[2].target_id) is not None
    assert small_cache.get_by_id(targets[3].target_id) is not None
    assert small_cache.get_by_id(targets[4].target_id) is not None


def test_cache_add_batch(cache: TargetCache) -> None:
    """批量添加正常工作。"""
    targets = [_make_target(text=f"B{i}") for i in range(10)]
    cache.add_batch(targets)
    assert cache.size == 10
    for t in targets:
        assert cache.get_by_id(t.target_id) is not None


# ── 按文字查找 ──────────────────────────────────────────


def test_find_by_text_exact(cache: TargetCache) -> None:
    """精确文字查找。"""
    cache.add_batch([
        _make_target(text="保存"),
        _make_target(text="另存为"),
        _make_target(text="保存文件"),
    ])
    results = cache.find_by_text("保存", exact=True)
    assert len(results) == 1
    assert results[0].text == "保存"


def test_find_by_text_contains(cache: TargetCache) -> None:
    """包含文字查找。"""
    cache.add_batch([
        _make_target(text="保存"),
        _make_target(text="另存为"),
        _make_target(text="保存文件"),
        _make_target(text="关闭"),
    ])
    results = cache.find_by_text("保存", exact=False)
    assert len(results) == 2
    texts = {r.text for r in results}
    assert texts == {"保存", "保存文件"}


# ── 按类型查找 ──────────────────────────────────────────


def test_find_by_type(cache: TargetCache, sample_targets: list[TargetInfo]) -> None:
    """按元素类型查找。"""
    cache.add_batch(sample_targets)
    buttons = cache.find_by_type("button")
    assert len(buttons) == 2
    for b in buttons:
        assert b.element_type == "button"


# ── 按区域查找 ──────────────────────────────────────────


def test_find_by_region(cache: TargetCache, sample_targets: list[TargetInfo]) -> None:
    """按屏幕区域查找。"""
    cache.add_batch(sample_targets)
    tl = cache.find_by_region("top_left")
    assert len(tl) == 1
    assert tl[0].text == "保存"

    br = cache.find_by_region("bottom_right")
    assert len(br) == 1
    assert br[0].text == "帮助链接"


# ── 按位置查找 ──────────────────────────────────────────


def test_find_by_bbox(cache: TargetCache) -> None:
    """按位置查找（含容差）。"""
    cache.add_batch([
        _make_target(text="A", center=(100, 100)),
        _make_target(text="B", center=(500, 500)),
        _make_target(text="C", center=(105, 105)),
    ])
    # 查询 bbox 中心在 (100, 100)，容差 15
    results = cache.find_by_bbox((80, 80, 40, 40), tolerance=15)
    texts = {r.text for r in results}
    assert "A" in texts
    assert "C" in texts
    assert "B" not in texts


# ── 最近目标 ────────────────────────────────────────────


def test_find_nearest(cache: TargetCache) -> None:
    """找最近目标。"""
    cache.add_batch([
        _make_target(text="远", center=(1000, 1000)),
        _make_target(text="近", center=(110, 115)),
        _make_target(text="中", center=(500, 500)),
    ])
    nearest = cache.find_nearest(100, 100)
    assert nearest is not None
    assert nearest.text == "近"


def test_find_nearest_with_type_filter(cache: TargetCache) -> None:
    """带类型过滤的最近目标查找。"""
    cache.add_batch([
        _make_target(text="按钮A", center=(105, 105), element_type="button"),
        _make_target(text="文字B", center=(110, 110), element_type="text"),
        _make_target(text="按钮C", center=(900, 900), element_type="button"),
    ])
    nearest = cache.find_nearest(100, 100, element_type="button")
    assert nearest is not None
    assert nearest.text == "按钮A"
    assert nearest.element_type == "button"


# ── 过期清理 ────────────────────────────────────────────


def test_remove_expired() -> None:
    """过期清理。"""
    short_cache = TargetCache(max_size=50, ttl_seconds=0.5)
    now = time.time()
    short_cache.add(_make_target(text="旧的", created_at=now - 1.0))
    short_cache.add(_make_target(text="新的", created_at=now))
    assert short_cache.size == 2

    removed = short_cache.remove_expired()
    assert removed == 1
    assert short_cache.size == 1
    assert short_cache.find_by_text("新的", exact=True)[0].text == "新的"


# ── 清空 ────────────────────────────────────────────────


def test_clear(cache: TargetCache) -> None:
    """清空缓存。"""
    cache.add_batch([_make_target(text=f"T{i}") for i in range(5)])
    assert cache.size == 5
    cache.clear()
    assert cache.size == 0


# ── size 属性 ───────────────────────────────────────────


def test_size_property(cache: TargetCache) -> None:
    """size 属性正确。"""
    assert cache.size == 0
    cache.add(_make_target())
    assert cache.size == 1
    cache.add(_make_target())
    assert cache.size == 2


# ── 统计信息 ────────────────────────────────────────────


def test_get_statistics(cache: TargetCache, sample_targets: list[TargetInfo]) -> None:
    """统计信息正确返回各维度数据。"""
    cache.add_batch(sample_targets)

    # 产生一些命中和未命中
    cache.get_by_id(sample_targets[0].target_id)  # hit
    cache.get_by_id(sample_targets[1].target_id)  # hit
    cache.get_by_id("nonexistent-id")  # miss

    stats = cache.get_statistics()
    assert stats["total"] == 5
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["hit_rate"] == pytest.approx(2 / 3)

    # 类型统计
    assert stats["type_counts"]["button"] == 2
    assert stats["type_counts"]["menu_item"] == 1
    assert stats["type_counts"]["link"] == 1
    assert stats["type_counts"]["label"] == 1

    # 区域统计
    assert stats["region_counts"]["top_left"] == 1
    assert stats["region_counts"]["top_right"] == 1
    assert stats["region_counts"]["bottom_left"] == 1
    assert stats["region_counts"]["bottom_right"] == 1
    assert stats["region_counts"]["center"] == 1
