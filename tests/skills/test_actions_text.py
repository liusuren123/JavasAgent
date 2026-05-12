# -*- coding: utf-8 -*-
"""文字原语测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.skills.actions.text import exec_type_text, exec_click_text
from src.skills.context import SkillContext


@pytest.fixture
def platform():
    p = MagicMock()
    p.click = AsyncMock()
    p.type_text = AsyncMock()
    return p


@pytest.fixture
def humanhand():
    h = MagicMock()
    h.type_text = AsyncMock()
    return h


@pytest.fixture
def perception():
    p = MagicMock()
    p.find_text = AsyncMock()
    return p


class TestTypeText:
    @pytest.mark.asyncio
    async def test_type_text_calls_humanhand(self, platform, humanhand, perception):
        ctx = SkillContext()
        step = {"action": "type_text", "text": "hello", "speed": "fast"}
        result = await exec_type_text(step, ctx, platform, humanhand)
        assert result["success"] is True
        humanhand.type_text.assert_called_once_with("hello", "fast")

    @pytest.mark.asyncio
    async def test_type_text_template_variable(self, platform, humanhand):
        ctx = SkillContext(parameters={"name": "world"})
        step = {"action": "type_text", "text": "{{parameters.name}}"}
        result = await exec_type_text(step, ctx, platform, humanhand)
        assert result["success"] is True
        assert result["text"] == "world"

    @pytest.mark.asyncio
    async def test_type_text_empty(self, platform, humanhand):
        ctx = SkillContext()
        step = {"action": "type_text", "text": ""}
        result = await exec_type_text(step, ctx, platform, humanhand)
        assert result["success"] is False


class TestClickText:
    @pytest.mark.asyncio
    async def test_click_text_found(self, platform, perception):
        perception.find_text.return_value = (400, 300)
        ctx = SkillContext()
        step = {"action": "click_text", "text": "保存", "timeout": 2.0}
        result = await exec_click_text(step, ctx, platform, perception)
        assert result["success"] is True
        assert result["x"] == 400
        assert result["y"] == 300
        platform.click.assert_called_once_with(400, 300)

    @pytest.mark.asyncio
    async def test_click_text_with_offset(self, platform, perception):
        perception.find_text.return_value = (100, 200)
        ctx = SkillContext()
        step = {"action": "click_text", "text": "文件类型", "offset_x": 50, "offset_y": 10}
        result = await exec_click_text(step, ctx, platform, perception)
        assert result["success"] is True
        assert result["x"] == 150
        assert result["y"] == 210
        platform.click.assert_called_once_with(150, 210)

    @pytest.mark.asyncio
    async def test_click_text_not_found(self, platform, perception):
        perception.find_text.return_value = None
        ctx = SkillContext()
        step = {"action": "click_text", "text": "不存在"}
        result = await exec_click_text(step, ctx, platform, perception)
        assert result["success"] is False
        assert "未找到文字" in result["error"]

    @pytest.mark.asyncio
    async def test_click_text_no_perception(self, platform):
        ctx = SkillContext()
        step = {"action": "click_text", "text": "test"}
        result = await exec_click_text(step, ctx, platform, None)
        assert result["success"] is False
