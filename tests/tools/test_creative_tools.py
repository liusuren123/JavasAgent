"""CreativeTools 测试。

验证占位实现的正确行为（返回未实现提示）。
"""

from __future__ import annotations

import pytest

from src.tools.creative_tools import CreativeTools


@pytest.fixture
def creative() -> CreativeTools:
    """创建 CreativeTools 实例。"""
    return CreativeTools()


class TestCreativeToolsPlaceholder:
    """占位实现的测试。"""

    @pytest.mark.asyncio
    async def test_execute_returns_not_implemented(self, creative: CreativeTools) -> None:
        """任何 action 都应返回未实现提示。"""
        result = await creative.execute("photoshop_open", {"path": "image.psd"})
        assert "error" in result
        assert "尚未实现" in result["error"]
        assert result["action"] == "photoshop_open"

    @pytest.mark.asyncio
    async def test_execute_premiere_action(self, creative: CreativeTools) -> None:
        """Premiere 操作同样返回未实现提示。"""
        result = await creative.execute("premiere_export", {"format": "mp4"})
        assert "error" in result
        assert "尚未实现" in result["error"]
        assert result["action"] == "premiere_export"

    @pytest.mark.asyncio
    async def test_execute_after_effects_action(self, creative: CreativeTools) -> None:
        """After Effects 操作同样返回未实现提示。"""
        result = await creative.execute("ae_compose", {"project": "demo.aep"})
        assert "error" in result
        assert "尚未实现" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_illustrator_action(self, creative: CreativeTools) -> None:
        """Illustrator 操作同样返回未实现提示。"""
        result = await creative.execute("illustrator_export", {"format": "svg"})
        assert "error" in result
        assert "尚未实现" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_unknown_action(self, creative: CreativeTools) -> None:
        """未知 action 也返回占位提示（不崩溃）。"""
        result = await creative.execute("random_action", {})
        assert "error" in result
        assert result["action"] == "random_action"

    @pytest.mark.asyncio
    async def test_execute_with_workspace(self) -> None:
        """带 workspace 参数的构造。"""
        tool = CreativeTools(workspace="/tmp/test_workspace")
        result = await tool.execute("test", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_execute_preserves_action_name(self, creative: CreativeTools) -> None:
        """结果中保留原始 action 名称。"""
        for action in ["ps_edit", "pr_cut", "ae_render", "ai_draw"]:
            result = await creative.execute(action, {"param": "value"})
            assert result["action"] == action
