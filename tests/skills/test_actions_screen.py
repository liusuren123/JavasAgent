# -*- coding: utf-8 -*-
"""截屏原语测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.skills.actions.screen import exec_screenshot
from src.skills.context import SkillContext


class TestScreenshot:
    @pytest.mark.asyncio
    async def test_screenshot_stores_in_context(self):
        platform = MagicMock()
        platform.screenshot = AsyncMock(return_value=b"\x89PNG\r\n" + b"\x00" * 50)
        ctx = SkillContext()
        step = {"action": "screenshot"}
        result = await exec_screenshot(step, ctx, platform)
        assert result["success"] is True
        assert result["captured"] is True
        assert len(ctx.screenshots) == 1

    @pytest.mark.asyncio
    async def test_screenshot_no_platform(self):
        ctx = SkillContext()
        step = {"action": "screenshot"}
        result = await exec_screenshot(step, ctx, None)
        assert result["success"] is True
        assert result["captured"] is False

    @pytest.mark.asyncio
    async def test_screenshot_empty_data(self):
        platform = MagicMock()
        platform.screenshot = AsyncMock(return_value=b"")
        ctx = SkillContext()
        step = {"action": "screenshot"}
        result = await exec_screenshot(step, ctx, platform)
        assert result["success"] is True
        assert result["captured"] is False
