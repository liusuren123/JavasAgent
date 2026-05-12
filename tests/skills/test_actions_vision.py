# -*- coding: utf-8 -*-
"""视觉原语测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.skills.actions.vision import exec_click_icon, exec_assert_text, exec_assert_screen
from src.skills.context import SkillContext


@pytest.fixture
def platform():
    p = MagicMock()
    p.click = AsyncMock()
    p.screenshot = AsyncMock(return_value=b"\x00" * 100)
    return p


@pytest.fixture
def perception():
    p = MagicMock()
    p.find_object = AsyncMock()
    p.get_screen_text = AsyncMock(return_value="")
    return p


class TestClickIcon:
    @pytest.mark.asyncio
    async def test_click_icon_found(self, platform, perception):
        perception.find_object.return_value = [100, 200, 200, 300]
        ctx = SkillContext()
        step = {"action": "click_icon", "description": "保存按钮"}
        result = await exec_click_icon(step, ctx, platform, perception)
        assert result["success"] is True
        assert result["x"] == 150  # (100+200)//2
        assert result["y"] == 250  # (200+300)//2
        platform.click.assert_called_once_with(150, 250)

    @pytest.mark.asyncio
    async def test_click_icon_not_found(self, platform, perception):
        perception.find_object.return_value = None
        ctx = SkillContext()
        step = {"action": "click_icon", "description": "不存在按钮"}
        result = await exec_click_icon(step, ctx, platform, perception)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_click_icon_no_description(self, platform, perception):
        ctx = SkillContext()
        step = {"action": "click_icon"}
        result = await exec_click_icon(step, ctx, platform, perception)
        assert result["success"] is False


class TestAssertText:
    @pytest.mark.asyncio
    async def test_assert_text_found(self, platform, perception):
        perception.get_screen_text.return_value = "保存成功！文件已导出"
        ctx = SkillContext()
        step = {"action": "assert_text", "text": "保存成功|已完成"}
        result = await exec_assert_text(step, ctx, perception)
        assert result["passed"] is True
        assert result["found"] == "保存成功"

    @pytest.mark.asyncio
    async def test_assert_text_second_match(self, platform, perception):
        perception.get_screen_text.return_value = "操作已完成 100%"
        ctx = SkillContext()
        step = {"action": "assert_text", "text": "保存成功|已完成"}
        result = await exec_assert_text(step, ctx, perception)
        assert result["passed"] is True
        assert result["found"] == "已完成"

    @pytest.mark.asyncio
    async def test_assert_text_not_found(self, platform, perception):
        perception.get_screen_text.return_value = "正在处理中..."
        ctx = SkillContext()
        step = {"action": "assert_text", "text": "保存成功|已完成"}
        result = await exec_assert_text(step, ctx, perception)
        assert result["passed"] is False

    @pytest.mark.asyncio
    async def test_assert_text_empty(self, platform, perception):
        ctx = SkillContext()
        step = {"action": "assert_text", "text": ""}
        result = await exec_assert_text(step, ctx, perception)
        assert result["passed"] is True


class TestAssertScreen:
    @pytest.mark.asyncio
    async def test_assert_screen_first_screenshot(self, platform):
        ctx = SkillContext()
        step = {"action": "assert_screen", "min_change": 0.01}
        result = await exec_assert_screen(step, ctx, platform)
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_assert_screen_change_detected(self, platform):
        # 第一次截图
        platform.screenshot.return_value = b"\x00" * 100
        ctx = SkillContext()
        ctx.screenshots.append(b"\x00" * 100)
        # 第二次截图（不同）
        platform.screenshot.return_value = b"\xFF" * 100
        step = {"action": "assert_screen", "min_change": 0.01}
        result = await exec_assert_screen(step, ctx, platform)
        assert result["passed"] is True
        assert result["change_ratio"] > 0.5

    @pytest.mark.asyncio
    async def test_assert_screen_no_change(self, platform):
        same_img = b"\xAA" * 100
        ctx = SkillContext()
        ctx.screenshots.append(same_img)
        platform.screenshot.return_value = same_img
        step = {"action": "assert_screen", "min_change": 0.01}
        result = await exec_assert_screen(step, ctx, platform)
        assert result["passed"] is False
