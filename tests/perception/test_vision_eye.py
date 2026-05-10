"""VisionEye 视觉感知器测试。"""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.perception.target_cache import TargetCache, TargetInfo, determine_screen_region
from src.perception.target_matcher import MatchLevel, MatchResult, TargetMatcher
from src.perception.vision_eye import VisionEye, VisionFrame
from src.utils.config import PerceptionConfig


# ── 测试工具 ──────────────────────────────────────────


def _make_config(**overrides) -> PerceptionConfig:
    defaults = {
        "enabled": True,
        "provider": None,
        "describe_max_tokens": 512,
        "locate_max_tokens": 256,
        "analyze_max_tokens": 1024,
        "image_detail": "auto",
    }
    defaults.update(overrides)
    return PerceptionConfig(**defaults)


# 一个最小的 1x1 白色 PNG，用于测试
_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_target(
    text: str = "测试按钮",
    element_type: str = "button",
    bbox: tuple[int, int, int, int] = (100, 100, 80, 30),
    created_at: float | None = None,
) -> TargetInfo:
    """快速创建 TargetInfo 用于测试。"""
    cx = bbox[0] + bbox[2] // 2
    cy = bbox[1] + bbox[3] // 2
    return TargetInfo(
        target_id=uuid.uuid4().hex,
        text=text,
        bbox=bbox,
        center=(cx, cy),
        element_type=element_type,
        confidence=0.9,
        screen_region=determine_screen_region((cx, cy)),
        created_at=created_at or time.time(),
    )


# ── 测试类 ────────────────────────────────────────────


class TestVisionFrameCreation:
    """1. 验证 VisionFrame 数据类能正确创建，字段完整。"""

    def test_vision_frame_creation(self) -> None:
        targets = [_make_target("按钮A"), _make_target("菜单B")]
        frame = VisionFrame(
            frame_id="abc123",
            timestamp=1700000000.0,
            description="屏幕上有按钮和菜单",
            targets=targets,
            width=1920,
            height=1080,
        )
        assert frame.frame_id == "abc123"
        assert frame.timestamp == 1700000000.0
        assert frame.description == "屏幕上有按钮和菜单"
        assert len(frame.targets) == 2
        assert frame.targets[0].text == "按钮A"
        assert frame.targets[1].text == "菜单B"
        assert frame.width == 1920
        assert frame.height == 1080


class TestVisionEyeInit:
    """2. 验证 VisionEye 初始化时内部组件正确创建。"""

    def test_vision_eye_init(self) -> None:
        llm = MagicMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        assert eye.cache is not None
        assert isinstance(eye.cache, TargetCache)
        assert eye.matcher is not None
        assert isinstance(eye.matcher, TargetMatcher)
        assert eye.last_frame is None
        assert eye.frame_count == 0


class TestCaptureAndAnalyze:
    """3. mock ScreenAnalyzer.describe 返回文本，验证 VisionFrame 生成、目标提取、缓存更新。"""

    @pytest.mark.asyncio
    async def test_capture_and_analyze(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = (
            "屏幕上显示了以下 UI 元素：\n"
            "1. 保存按钮\n"
            "2. 关闭按钮\n"
            "3. 搜索输入框"
        )

        config = _make_config()
        eye = VisionEye(llm, config)

        frame = await eye.capture_and_analyze(_MINI_PNG, 1920, 1080)

        assert isinstance(frame, VisionFrame)
        assert frame.frame_id  # 非空
        assert frame.timestamp > 0
        assert "按钮" in frame.description
        assert len(frame.targets) > 0
        assert frame.width == 1920
        assert frame.height == 1080
        # 缓存中应该有目标
        assert eye.cache.size > 0


class TestCaptureAndAnalyzeDisabled:
    """4. config.enabled=False 时返回空描述和空目标列表。"""

    @pytest.mark.asyncio
    async def test_capture_and_analyze_disabled(self) -> None:
        llm = AsyncMock()
        config = _make_config(enabled=False)
        eye = VisionEye(llm, config)

        frame = await eye.capture_and_analyze(_MINI_PNG)

        assert frame.description == ""
        assert frame.targets == []
        llm.chat_with_image.assert_not_called()


class TestFindTargetExact:
    """5. 缓存中存在精确匹配目标时，find_target 返回 EXACT 级别结果。"""

    @pytest.mark.asyncio
    async def test_find_target_exact(self) -> None:
        llm = AsyncMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        # 手动添加一个目标到缓存
        target = _make_target("保存")
        eye.cache.add(target)

        result = await eye.find_target("保存")
        assert result is not None
        assert result.level == MatchLevel.EXACT
        assert result.target.text == "保存"


class TestFindTargetFuzzy:
    """6. 缓存中存在模糊匹配目标时，find_target 返回 FUZZY 级别结果。"""

    @pytest.mark.asyncio
    async def test_find_target_fuzzy(self) -> None:
        llm = AsyncMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        # 添加一个目标，模糊查询
        target = _make_target("保存文件")
        eye.cache.add(target)

        result = await eye.find_target("保存文")
        assert result is not None
        assert result.level == MatchLevel.FUZZY


class TestFindTargetSemantic:
    """7. 缓存中存在语义匹配目标时，find_target 返回 SEMANTIC 级别结果。"""

    @pytest.mark.asyncio
    async def test_find_target_semantic(self) -> None:
        llm = AsyncMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        # "删除按键" vs "移除按钮" — 编辑距离比 < 0.6（不命中精确/模糊），
        # 但 "删除"/"移除" 和 "按键"/"按钮" 都是同义词，命中语义匹配
        target = _make_target("移除按钮")
        eye.cache.add(target)

        result = await eye.find_target("删除按键")
        assert result is not None
        assert result.level == MatchLevel.SEMANTIC


class TestFindTargetNoMatch:
    """8. 缓存中没有匹配时，find_target 返回 None。"""

    @pytest.mark.asyncio
    async def test_find_target_no_match(self) -> None:
        llm = AsyncMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        # 空缓存
        result = await eye.find_target("不存在的东西xyz")
        assert result is None


class TestLocateOnScreenFound:
    """9. mock ScreenAnalyzer.locate 返回 found=True，验证返回坐标元组。"""

    @pytest.mark.asyncio
    async def test_locate_on_screen_found(self) -> None:
        llm = AsyncMock()
        # describe 和 locate 都可能被调用，但 locate 返回 found
        llm.chat_with_image.return_value = (
            '{"found": true, "x": 500, "y": 300, "description": "保存按钮"}'
        )

        config = _make_config()
        eye = VisionEye(llm, config)

        coords = await eye.locate_on_screen(_MINI_PNG, "保存按钮")
        assert coords is not None
        assert coords == (500, 300)


class TestLocateOnScreenNotFound:
    """10. mock ScreenAnalyzer.locate 返回 found=False，验证返回 None。"""

    @pytest.mark.asyncio
    async def test_locate_on_screen_not_found(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = (
            '{"found": false, "x": null, "y": null, "description": "未找到"}'
        )

        config = _make_config()
        eye = VisionEye(llm, config)

        coords = await eye.locate_on_screen(_MINI_PNG, "不存在的元素")
        assert coords is None


class TestRefreshCache:
    """11. 添加目标后手动修改时间戳使其过期，验证 refresh_cache 正确移除。"""

    def test_refresh_cache(self) -> None:
        llm = MagicMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        # 添加目标，设置 created_at 为很久以前（已过期）
        expired_target = _make_target("过期按钮", created_at=time.time() - 100)
        eye.cache.add(expired_target)

        assert eye.cache.size == 1
        removed = eye.refresh_cache()
        assert removed == 1
        assert eye.cache.size == 0


class TestGetCacheStats:
    """12. 添加若干目标后验证统计信息。"""

    def test_get_cache_stats(self) -> None:
        llm = MagicMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        eye.cache.add(_make_target("按钮A", element_type="button"))
        eye.cache.add(_make_target("按钮B", element_type="button"))
        eye.cache.add(_make_target("菜单项C", element_type="menu_item"))

        stats = eye.get_cache_stats()
        assert stats["total"] == 3
        assert stats["type_counts"]["button"] == 2
        assert stats["type_counts"]["menu_item"] == 1


class TestExtractTargetsFromDescription:
    """13. 验证从描述文本中提取目标列表，包括元素类型识别。"""

    def test_extract_targets_from_description(self) -> None:
        llm = MagicMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        description = (
            "屏幕上有以下元素：\n"
            "1. 保存按钮\n"
            "2. 文件菜单\n"
            "3. 搜索输入框\n"
            "4. 关闭图标"
        )

        targets = eye._extract_targets_from_description(description, 1920, 1080)
        assert len(targets) > 0

        # 检查元素类型识别
        types = {t.element_type for t in targets}
        # 至少应该识别出 button 和 icon
        assert "button" in types or "menu_item" in types or "input" in types or "icon" in types

    def test_extract_targets_with_coordinates(self) -> None:
        """测试从带坐标信息的文本中提取。"""
        llm = MagicMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        description = "保存按钮 (100, 200, 80, 30)\n关闭按钮 [300, 400, 60, 25]"
        targets = eye._extract_targets_from_description(description, 1920, 1080)
        assert len(targets) == 2
        # 第一个 bbox 来自文本 (100, 200, 80, 30)
        assert targets[0].bbox == (100, 200, 80, 30)
        # 第二个 bbox 来自文本 [300, 400, 60, 25]
        assert targets[1].bbox == (300, 400, 60, 25)


class TestExtractTargetsEmptyDescription:
    """14. 空描述返回空列表。"""

    def test_extract_targets_empty_description(self) -> None:
        llm = MagicMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        # 空字符串
        assert eye._extract_targets_from_description("", 1920, 1080) == []
        # 只有空格
        assert eye._extract_targets_from_description("   \n  ", 1920, 1080) == []


class TestLastFrameProperty:
    """15. capture_and_analyze 后 last_frame 正确更新。"""

    @pytest.mark.asyncio
    async def test_last_frame_property(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = "屏幕显示了保存按钮"

        config = _make_config()
        eye = VisionEye(llm, config)

        assert eye.last_frame is None
        await eye.capture_and_analyze(_MINI_PNG)
        assert eye.last_frame is not None
        assert "保存按钮" in eye.last_frame.description


class TestCacheProperty:
    """16. 验证 cache 属性返回内部 TargetCache 实例。"""

    def test_cache_property(self) -> None:
        llm = MagicMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        assert isinstance(eye.cache, TargetCache)
        # 多次访问返回同一个实例
        assert eye.cache is eye.cache


class TestMatcherProperty:
    """17. 验证 matcher 属性返回内部 TargetMatcher 实例。"""

    def test_matcher_property(self) -> None:
        llm = MagicMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        assert isinstance(eye.matcher, TargetMatcher)
        # 多次访问返回同一个实例
        assert eye.matcher is eye.matcher


class TestMultipleCapturesAccumulate:
    """18. 多次 capture_and_analyze 累积目标到缓存。"""

    @pytest.mark.asyncio
    async def test_multiple_captures_accumulate(self) -> None:
        llm = AsyncMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        # 第一次 capture
        llm.chat_with_image.return_value = "屏幕上有保存按钮"
        await eye.capture_and_analyze(_MINI_PNG)
        count1 = eye.cache.size

        # 第二次 capture，返回不同的描述
        llm.chat_with_image.return_value = "屏幕上有关闭按钮和菜单"
        await eye.capture_and_analyze(_MINI_PNG)
        count2 = eye.cache.size

        # 第二次应该累积更多目标
        assert count2 >= count1


class TestCaptureUpdatesFrameCount:
    """19. 多次 capture 后 frame_count 递增。"""

    @pytest.mark.asyncio
    async def test_capture_updates_frame_count(self) -> None:
        llm = AsyncMock()
        llm.chat_with_image.return_value = "屏幕内容描述"

        config = _make_config()
        eye = VisionEye(llm, config)

        assert eye.frame_count == 0
        await eye.capture_and_analyze(_MINI_PNG)
        assert eye.frame_count == 1
        await eye.capture_and_analyze(_MINI_PNG)
        assert eye.frame_count == 2
        await eye.capture_and_analyze(_MINI_PNG)
        assert eye.frame_count == 3


class TestFindTargetWithTypeFilter:
    """20. 按 target_type 过滤查找目标。"""

    @pytest.mark.asyncio
    async def test_find_target_with_type_filter(self) -> None:
        llm = AsyncMock()
        config = _make_config()
        eye = VisionEye(llm, config)

        # 添加不同类型的目标
        btn_target = _make_target("保存", element_type="button")
        menu_target = _make_target("保存", element_type="menu_item")
        eye.cache.add(btn_target)
        eye.cache.add(menu_target)

        # 过滤 button 类型
        result = await eye.find_target("保存", target_type="button")
        assert result is not None
        assert result.target.element_type == "button"

        # 过滤 menu_item 类型
        result = await eye.find_target("保存", target_type="menu_item")
        assert result is not None
        assert result.target.element_type == "menu_item"

        # 过滤不存在的类型
        result = await eye.find_target("保存", target_type="icon")
        assert result is None
