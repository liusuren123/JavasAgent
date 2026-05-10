"""TargetMatcher 三级匹配器测试。"""

import pytest
import time

from src.perception.target_cache import TargetCache, TargetInfo
from src.perception.target_matcher import MatchLevel, MatchResult, TargetMatcher


# ── 测试辅助 ──────────────────────────────────────────


def _make_target(
    text: str,
    element_type: str = "button",
    region: str = "center",
    target_id: str | None = None,
) -> TargetInfo:
    """创建测试用 TargetInfo。"""
    return TargetInfo(
        target_id=target_id or f"id_{text}",
        text=text,
        bbox=(100, 100, 50, 30),
        center=(125, 115),
        element_type=element_type,
        confidence=0.9,
        screen_region=region,
        created_at=time.time(),
    )


def _populated_cache(*targets: TargetInfo) -> TargetCache:
    """创建并填充缓存。"""
    cache = TargetCache()
    cache.add_batch(list(targets))
    return cache


# ── 1. MatchResult 数据类 ─────────────────────────────


def test_match_result_creation():
    """MatchResult 数据类创建和字段验证。"""
    t = _make_target("保存")
    result = MatchResult(
        target=t,
        level=MatchLevel.EXACT,
        score=1.0,
        confidence=1.0,
    )
    assert result.target is t
    assert result.level is MatchLevel.EXACT
    assert result.score == 1.0
    assert result.confidence == 1.0


# ── 2. MatchLevel 枚举 ───────────────────────────────


def test_match_level_enum():
    """MatchLevel 枚举值正确性。"""
    assert MatchLevel.EXACT.value == "exact"
    assert MatchLevel.FUZZY.value == "fuzzy"
    assert MatchLevel.SEMANTIC.value == "semantic"
    # 确保只有三个成员
    assert len(MatchLevel) == 3


# ── 3-6. 精确匹配 ────────────────────────────────────


def test_exact_match_identical():
    """完全相同的文本精确匹配成功。"""
    cache = _populated_cache(_make_target("保存"))
    matcher = TargetMatcher(cache)
    result = matcher.exact_match("保存")
    assert result is not None
    assert result.level is MatchLevel.EXACT
    assert result.score == 1.0


def test_exact_match_case_insensitive():
    """忽略大小写的精确匹配。"""
    cache = _populated_cache(_make_target("Save"))
    matcher = TargetMatcher(cache)
    result = matcher.exact_match("save")
    assert result is not None
    assert result.level is MatchLevel.EXACT


def test_exact_match_trim_whitespace():
    """忽略首尾空格的精确匹配。"""
    cache = _populated_cache(_make_target("保存"))
    matcher = TargetMatcher(cache)
    result = matcher.exact_match("  保存  ")
    assert result is not None
    assert result.level is MatchLevel.EXACT


def test_exact_match_not_found():
    """不匹配时返回 None。"""
    cache = _populated_cache(_make_target("保存"))
    matcher = TargetMatcher(cache)
    result = matcher.exact_match("删除")
    assert result is None


# ── 7-8. 模糊匹配 ────────────────────────────────────


def test_fuzzy_match_similar_text():
    """相似文本模糊匹配成功。"""
    cache = _populated_cache(_make_target("保存文件"))
    matcher = TargetMatcher(cache)
    result = matcher.fuzzy_match("保存文")  # 差一个字
    assert result is not None
    assert result.level is MatchLevel.FUZZY
    assert result.score >= 0.6


def test_fuzzy_match_below_threshold():
    """低于阈值的模糊匹配返回 None。"""
    cache = _populated_cache(_make_target("这是一个很长的按钮文字"))
    matcher = TargetMatcher(cache, fuzzy_threshold=0.9)
    result = matcher.fuzzy_match("完全不同的文字")
    assert result is None


# ── 9-10. Levenshtein ────────────────────────────────


def test_levenshtein_ratio_identical():
    """相同字符串比率为 1.0。"""
    assert TargetMatcher._levenshtein_ratio("hello", "hello") == 1.0
    assert TargetMatcher._levenshtein_ratio("", "") == 1.0


def test_levenshtein_ratio_completely_different():
    """完全不同字符串比率接近 0.0。"""
    ratio = TargetMatcher._levenshtein_ratio("abc", "xyz")
    assert ratio == 0.0  # 完全不同，编辑距离 = 3，max = 3


# ── 11-13. 语义匹配 ──────────────────────────────────


def test_semantic_match_with_synonyms():
    """同义词语义匹配成功。"""
    # "单击" 和 "点击" 是同义词，但 "单击" 本身不是 target text
    # 我们测试 query "单击" 能匹配到 text "点击按钮"
    cache = _populated_cache(_make_target("点击按钮"))
    matcher = TargetMatcher(cache, semantic_threshold=0.3)
    result = matcher.semantic_match("单击按钮")
    assert result is not None
    assert result.level is MatchLevel.SEMANTIC


def test_semantic_match_keyword_contained():
    """关键词包含匹配成功。"""
    cache = _populated_cache(_make_target("保存文件到桌面"))
    matcher = TargetMatcher(cache, semantic_threshold=0.3)
    result = matcher.semantic_match("保存文件")
    assert result is not None
    assert result.level is MatchLevel.SEMANTIC


def test_semantic_match_below_threshold():
    """低于语义阈值的返回 None。"""
    cache = _populated_cache(_make_target("彻底不相关的文字xyz"))
    matcher = TargetMatcher(cache, semantic_threshold=0.9)
    result = matcher.semantic_match("完全没有任何关联abc")
    assert result is None


# ── 14-17. match() 方法 ──────────────────────────────


def test_match_exact_first():
    """match() 方法优先返回精确匹配结果。"""
    # 同时有精确匹配和模糊匹配候选
    cache = _populated_cache(
        _make_target("保存", target_id="1"),
        _make_target("保存文件", target_id="2"),
    )
    matcher = TargetMatcher(cache)
    result = matcher.match("保存")
    assert result is not None
    assert result.level is MatchLevel.EXACT
    assert result.target.text == "保存"


def test_match_fuzzy_fallback():
    """无精确匹配时回退到模糊匹配。"""
    cache = _populated_cache(_make_target("保存文件"))
    matcher = TargetMatcher(cache)
    result = matcher.match("保存文")  # 差一个字，不精确但相似
    assert result is not None
    assert result.level is MatchLevel.FUZZY


def test_match_semantic_fallback():
    """无精确和模糊匹配时回退到语义匹配。"""
    cache = _populated_cache(_make_target("点击确认"))
    matcher = TargetMatcher(cache, fuzzy_threshold=0.99)
    result = matcher.match("单击确认")  # "单击" ≈ "点击"，但编辑距离高
    assert result is not None
    assert result.level is MatchLevel.SEMANTIC


def test_match_no_result():
    """所有级别都不匹配时返回 None。"""
    cache = _populated_cache(_make_target("abc"))
    matcher = TargetMatcher(cache, fuzzy_threshold=0.99, semantic_threshold=0.99)
    result = matcher.match("xyz")
    assert result is None


# ── 18. match_all() ──────────────────────────────────


def test_match_all_returns_sorted():
    """match_all() 返回按 score 降序排列的结果。"""
    cache = _populated_cache(
        _make_target("保存", target_id="1"),
        _make_target("保存文件", target_id="2"),
        _make_target("彻底不相关", target_id="3"),
    )
    matcher = TargetMatcher(cache, semantic_threshold=0.3)
    results = matcher.match_all("保存")
    assert len(results) >= 2  # 至少精确 + 模糊
    # 验证降序
    for i in range(len(results) - 1):
        assert results[i].score >= results[i + 1].score


# ── 19. 类型过滤 ──────────────────────────────────────


def test_match_with_type_filter():
    """通过 target_type 过滤匹配结果。"""
    cache = _populated_cache(
        _make_target("保存", element_type="button", target_id="btn1"),
        _make_target("保存", element_type="label", target_id="lbl1"),
    )
    matcher = TargetMatcher(cache)
    result = matcher.exact_match("保存", target_type="button")
    assert result is not None
    assert result.target.element_type == "button"


# ── 20. 置信度衰减 ────────────────────────────────────


def test_compute_confidence_levels():
    """验证三种匹配等级的置信度衰减系数。"""
    score = 0.8

    c_exact = TargetMatcher._compute_confidence(MatchLevel.EXACT, score)
    c_fuzzy = TargetMatcher._compute_confidence(MatchLevel.FUZZY, score)
    c_semantic = TargetMatcher._compute_confidence(MatchLevel.SEMANTIC, score)

    assert c_exact == pytest.approx(0.8)  # 0.8 * 1.0
    assert c_fuzzy == pytest.approx(0.64)  # 0.8 * 0.8
    assert c_semantic == pytest.approx(0.48)  # 0.8 * 0.6

    # EXACT > FUZZY > SEMANTIC
    assert c_exact > c_fuzzy > c_semantic
