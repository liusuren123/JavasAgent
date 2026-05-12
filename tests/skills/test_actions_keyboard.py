# -*- coding: utf-8 -*-
"""键盘原语测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.skills.actions.keyboard import exec_key_combo, exec_key_type
from src.skills.context import SkillContext


@pytest.fixture
def ctx():
    return SkillContext()


@pytest.fixture
def platform():
    p = MagicMock()
    p.key_combo = AsyncMock()
    p.type_key = AsyncMock()
    return p


class TestKeyCombo:
    @pytest.mark.asyncio
    async def test_key_combo_calls_platform(self, ctx, platform):
        step = {"action": "key_combo", "keys": "ctrl+s"}
        result = await exec_key_combo(step, ctx, platform)
        assert result["success"] is True
        platform.key_combo.assert_called_once_with("ctrl+s")

    @pytest.mark.asyncio
    async def test_key_combo_empty_keys(self, ctx, platform):
        step = {"action": "key_combo", "keys": ""}
        result = await exec_key_combo(step, ctx, platform)
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_key_combo_no_keys_field(self, ctx, platform):
        step = {"action": "key_combo"}
        result = await exec_key_combo(step, ctx, platform)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_key_combo_template_variable(self, platform):
        ctx = SkillContext(parameters={"shortcut": "alt+f4"})
        step = {"action": "key_combo", "keys": "{{parameters.shortcut}}"}
        result = await exec_key_combo(step, ctx, platform)
        assert result["success"] is True
        assert result["keys"] == "alt+f4"


class TestKeyType:
    @pytest.mark.asyncio
    async def test_key_type_calls_platform(self, ctx, platform):
        step = {"action": "key_type", "keys": "enter"}
        result = await exec_key_type(step, ctx, platform)
        assert result["success"] is True
        platform.type_key.assert_called_once_with("enter")

    @pytest.mark.asyncio
    async def test_key_type_empty_keys(self, ctx, platform):
        step = {"action": "key_type", "keys": ""}
        result = await exec_key_type(step, ctx, platform)
        assert result["success"] is False
