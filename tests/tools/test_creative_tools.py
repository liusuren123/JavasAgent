"""CreativeTools 测试。

验证 Photoshop 委托和非 Photoshop 操作的占位行为。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.creative_tools import CreativeTools


@pytest.fixture
def creative() -> CreativeTools:
    """创建 CreativeTools 实例。"""
    return CreativeTools()


class TestCreativeToolsPhotoshopDelegation:
    """Photoshop 操作委托测试。"""

    @pytest.mark.asyncio
    async def test_photoshop_open_delegates(self, creative: CreativeTools) -> None:
        """photoshop_open 应委托给 PhotoshopControl。"""
        mock_ps = MagicMock()
        mock_ps.execute = AsyncMock(return_value={"status": "opened", "document_name": "test.psd"})

        with patch.object(creative, "_get_ps_control", return_value=mock_ps):
            result = await creative.execute("photoshop_open", {"path": "test.psd"})

        assert result["status"] == "opened"
        mock_ps.execute.assert_called_once_with("open_document", {"path": "test.psd"})

    @pytest.mark.asyncio
    async def test_photoshop_save_delegates(self, creative: CreativeTools) -> None:
        """photoshop_save 应委托给 PhotoshopControl。"""
        mock_ps = MagicMock()
        mock_ps.execute = AsyncMock(return_value={"status": "saved"})

        with patch.object(creative, "_get_ps_control", return_value=mock_ps):
            result = await creative.execute("photoshop_save", {"path": "output.psd"})

        assert result["status"] == "saved"
        mock_ps.execute.assert_called_once_with("save_document", {"path": "output.psd"})

    @pytest.mark.asyncio
    async def test_photoshop_export_delegates(self, creative: CreativeTools) -> None:
        """photoshop_export 应委托。"""
        mock_ps = MagicMock()
        mock_ps.execute = AsyncMock(return_value={"status": "exported"})

        with patch.object(creative, "_get_ps_control", return_value=mock_ps):
            result = await creative.execute("photoshop_export", {"path": "out.png", "format": "png"})

        assert result["status"] == "exported"

    @pytest.mark.asyncio
    async def test_photoshop_action_delegates(self, creative: CreativeTools) -> None:
        """photoshop_action 应委托。"""
        mock_ps = MagicMock()
        mock_ps.execute = AsyncMock(return_value={"status": "action_executed"})

        with patch.object(creative, "_get_ps_control", return_value=mock_ps):
            result = await creative.execute("photoshop_action", {"action_name": "Test"})

        assert result["status"] == "action_executed"

    @pytest.mark.asyncio
    async def test_photoshop_filter_delegates(self, creative: CreativeTools) -> None:
        """photoshop_filter 应委托。"""
        mock_ps = MagicMock()
        mock_ps.execute = AsyncMock(return_value={"status": "filter_applied"})

        with patch.object(creative, "_get_ps_control", return_value=mock_ps):
            result = await creative.execute("photoshop_filter", {"filter_name": "blur"})

        assert result["status"] == "filter_applied"

    @pytest.mark.asyncio
    async def test_photoshop_resize_delegates(self, creative: CreativeTools) -> None:
        """photoshop_resize 应委托。"""
        mock_ps = MagicMock()
        mock_ps.execute = AsyncMock(return_value={"status": "resized"})

        with patch.object(creative, "_get_ps_control", return_value=mock_ps):
            result = await creative.execute("photoshop_resize", {"width": 800, "height": 600})

        assert result["status"] == "resized"

    @pytest.mark.asyncio
    async def test_photoshop_info_delegates(self, creative: CreativeTools) -> None:
        """photoshop_info 应委托。"""
        mock_ps = MagicMock()
        mock_ps.execute = AsyncMock(return_value={"name": "test.psd", "width": 1920})

        with patch.object(creative, "_get_ps_control", return_value=mock_ps):
            result = await creative.execute("photoshop_info", {})

        assert result["name"] == "test.psd"

    @pytest.mark.asyncio
    async def test_photoshop_close_delegates(self, creative: CreativeTools) -> None:
        """photoshop_close 应委托。"""
        mock_ps = MagicMock()
        mock_ps.execute = AsyncMock(return_value={"status": "closed"})

        with patch.object(creative, "_get_ps_control", return_value=mock_ps):
            result = await creative.execute("photoshop_close", {"save": True})

        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_photoshop_control_exception_handled(self, creative: CreativeTools) -> None:
        """PhotoshopControl 执行异常应被捕获。"""
        mock_ps = MagicMock()
        mock_ps.execute = AsyncMock(side_effect=RuntimeError("PS not running"))

        with patch.object(creative, "_get_ps_control", return_value=mock_ps):
            result = await creative.execute("photoshop_open", {"path": "test.psd"})

        assert "error" in result
        assert "action" in result


class TestCreativeToolsPlaceholder:
    """非 Photoshop 操作的占位行为测试。"""

    @pytest.mark.asyncio
    async def test_premiere_action_placeholder(self, creative: CreativeTools) -> None:
        """Premiere 操作仍返回未实现提示。"""
        result = await creative.execute("premiere_export", {"format": "mp4"})
        assert "error" in result
        assert "尚未实现" in result["error"]
        assert result["action"] == "premiere_export"

    @pytest.mark.asyncio
    async def test_after_effects_action_placeholder(self, creative: CreativeTools) -> None:
        """After Effects 操作仍返回未实现提示。"""
        result = await creative.execute("ae_compose", {"project": "demo.aep"})
        assert "error" in result
        assert "尚未实现" in result["error"]

    @pytest.mark.asyncio
    async def test_illustrator_action_placeholder(self, creative: CreativeTools) -> None:
        """Illustrator 操作仍返回未实现提示。"""
        result = await creative.execute("illustrator_export", {"format": "svg"})
        assert "error" in result
        assert "尚未实现" in result["error"]

    @pytest.mark.asyncio
    async def test_unknown_action_placeholder(self, creative: CreativeTools) -> None:
        """未知 action 返回占位提示。"""
        result = await creative.execute("random_action", {})
        assert "error" in result
        assert result["action"] == "random_action"

    @pytest.mark.asyncio
    async def test_with_workspace(self) -> None:
        """带 workspace 参数的构造。"""
        tool = CreativeTools(workspace="/tmp/test_workspace")
        result = await tool.execute("test", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_preserves_action_name(self, creative: CreativeTools) -> None:
        """结果中保留原始 action 名称。"""
        for action in ["pr_cut", "ae_render", "ai_draw"]:
            result = await creative.execute(action, {"param": "value"})
            assert result["action"] == action
