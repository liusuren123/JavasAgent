# -*- coding: utf-8 -*-
"""鼠标原语测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.skills.actions.mouse import (
    exec_click, exec_double_click, exec_right_click,
    exec_drag, exec_scroll,
)
from src.skills.context import SkillContext


@pytest.fixture
def ctx():
    return SkillContext()


@pytest.fixture
def platform():
    p = MagicMock()
    p.click = AsyncMock()
    p.double_click = AsyncMock()
    p.right_click = AsyncMock()
    p.drag = AsyncMock()
    p.scroll = AsyncMock()
    return p


class TestClick:
    @pytest.mark.asyncio
    async def test_click_coordinates(self, ctx, platform):
        step = {"action": "click", "x": 100, "y": 200}
        result = await exec_click(step, ctx, platform)
        assert result["success"] is True
        assert result["x"] == 100
        assert result["y"] == 200
        platform.click.assert_called_once_with(100, 200)

    @pytest.mark.asyncio
    async def test_click_template_variables(self, platform):
        ctx = SkillContext(variables={"tx": 50, "ty": 80})
        step = {"action": "click", "x": "{{variables.tx}}", "y": "{{variables.ty}}"}
        result = await exec_click(step, ctx, platform)
        assert result["success"] is True


class TestDoubleClick:
    @pytest.mark.asyncio
    async def test_double_click(self, ctx, platform):
        step = {"action": "double_click", "x": 150, "y": 250}
        result = await exec_double_click(step, ctx, platform)
        assert result["success"] is True
        platform.double_click.assert_called_once_with(150, 250)


class TestRightClick:
    @pytest.mark.asyncio
    async def test_right_click(self, ctx, platform):
        step = {"action": "right_click", "x": 300, "y": 400}
        result = await exec_right_click(step, ctx, platform)
        assert result["success"] is True
        platform.right_click.assert_called_once_with(300, 400)


class TestDrag:
    @pytest.mark.asyncio
    async def test_drag(self, ctx, platform):
        step = {"action": "drag", "start_x": 10, "start_y": 20, "end_x": 100, "end_y": 200}
        result = await exec_drag(step, ctx, platform)
        assert result["success"] is True
        assert result["start"] == [10, 20]
        assert result["end"] == [100, 200]
        platform.drag.assert_called_once_with(10, 20, 100, 200)


class TestScroll:
    @pytest.mark.asyncio
    async def test_scroll_up(self, ctx, platform):
        step = {"action": "scroll", "amount": 5}
        result = await exec_scroll(step, ctx, platform)
        assert result["success"] is True
        platform.scroll.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_scroll_down(self, ctx, platform):
        step = {"action": "scroll", "amount": -3}
        result = await exec_scroll(step, ctx, platform)
        assert result["success"] is True
        platform.scroll.assert_called_once_with(-3)
