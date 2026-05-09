"""剪贴板管理工具测试。"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.tools.clipboard_ops import ClipboardOps


@pytest.fixture
def tool() -> ClipboardOps:
    """创建工具实例。"""
    return ClipboardOps()


def _mock_pyperclip():
    """创建 pyperclip mock。"""
    m = MagicMock()
    m.PyperclipException = Exception
    return m


def _mock_win32clipboard():
    """创建 win32clipboard mock。"""
    m = MagicMock()
    m.CF_HDROP = 15
    m.CF_DIB = 8
    return m


class TestClipboardOpsWriteTextAndRead:
    """测试 write_text + read 文本。"""

    @pytest.mark.asyncio
    async def test_write_text_success(self, tool: ClipboardOps) -> None:
        mock_pc = _mock_pyperclip()
        with patch.dict(sys.modules, {"pyperclip": mock_pc}):
            result = await tool.execute("write_text", {"text": "Hello!"})
            assert result["success"] is True
            assert result["format"] == "text"
            assert result["length"] == 6
            mock_pc.copy.assert_called_once_with("Hello!")

    @pytest.mark.asyncio
    async def test_read_text(self, tool: ClipboardOps) -> None:
        mock_pc = _mock_pyperclip()
        mock_pc.paste.return_value = "Hello!"
        with patch.dict(sys.modules, {"pyperclip": mock_pc}):
            result = await tool.execute("read", {})
            assert result["format"] == "text"
            assert result["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_write_and_read_roundtrip(self, tool: ClipboardOps) -> None:
        """完整写入再读出流程。"""
        stored_text = ""

        def fake_copy(t: str) -> None:
            nonlocal stored_text
            stored_text = t

        mock_pc = _mock_pyperclip()
        mock_pc.copy.side_effect = fake_copy
        mock_pc.paste.side_effect = lambda: stored_text or None

        with patch.dict(sys.modules, {"pyperclip": mock_pc}):
            await tool.execute("write_text", {"text": "Roundtrip test"})
            result = await tool.execute("read", {})
            assert result["content"] == "Roundtrip test"

    @pytest.mark.asyncio
    async def test_write_text_non_string(self, tool: ClipboardOps) -> None:
        mock_pc = _mock_pyperclip()
        with patch.dict(sys.modules, {"pyperclip": mock_pc}):
            result = await tool.execute("write_text", {"text": 123})
            assert "error" in result


class TestClipboardOpsClear:
    """测试 clear 操作。"""

    @pytest.mark.asyncio
    async def test_clear_with_win32(self, tool: ClipboardOps) -> None:
        mock_w32 = _mock_win32clipboard()
        with patch.dict(sys.modules, {"win32clipboard": mock_w32}):
            result = await tool.execute("clear", {})
            assert result["success"] is True
            mock_w32.EmptyClipboard.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_fallback_to_pyperclip(self, tool: ClipboardOps) -> None:
        """win32clipboard 不可用时回退到 pyperclip。"""
        mock_pc = _mock_pyperclip()
        # win32clipboard 设为 None 触发 ImportError
        with patch.dict(sys.modules, {"win32clipboard": None, "pyperclip": mock_pc}):
            result = await tool.execute("clear", {})
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_read_after_clear(self, tool: ClipboardOps) -> None:
        """清空后读取应返回空。"""
        mock_w32 = _mock_win32clipboard()
        mock_pc = _mock_pyperclip()
        mock_pc.paste.return_value = ""

        with patch.dict(sys.modules, {"win32clipboard": mock_w32}):
            await tool.execute("clear", {})

        with patch.dict(sys.modules, {"pyperclip": mock_pc, "win32clipboard": mock_w32}):
            result = await tool.execute("read", {})
            assert result["format"] == "empty"


class TestClipboardOpsUnknownAction:
    """测试未知操作处理。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool: ClipboardOps) -> None:
        result = await tool.execute("nonexistent", {})
        assert "error" in result
        assert "nonexistent" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_action(self, tool: ClipboardOps) -> None:
        result = await tool.execute("", {})
        assert "error" in result


class TestClipboardOpsWriteFiles:
    """测试 write_files 操作。"""

    @pytest.mark.asyncio
    async def test_write_files_success(self, tool: ClipboardOps) -> None:
        mock_w32 = _mock_win32clipboard()
        with patch.dict(sys.modules, {"win32clipboard": mock_w32}):
            result = await tool.execute(
                "write_files", {"files": ["C:\\a.txt", "C:\\b.txt"]}
            )
            assert result["success"] is True
            assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_write_files_empty_list(self, tool: ClipboardOps) -> None:
        mock_w32 = _mock_win32clipboard()
        with patch.dict(sys.modules, {"win32clipboard": mock_w32}):
            result = await tool.execute("write_files", {"files": []})
            assert "error" in result

    @pytest.mark.asyncio
    async def test_write_files_no_win32(self, tool: ClipboardOps) -> None:
        """无 win32clipboard 时应返回错误。"""
        with patch.dict(sys.modules, {"win32clipboard": None}):
            result = await tool.execute("write_files", {"files": ["C:\\a.txt"]})
            assert "error" in result


class TestClipboardOpsWatch:
    """测试 watch 监控功能。"""

    @pytest.mark.asyncio
    async def test_watch_start_and_stop(self, tool: ClipboardOps) -> None:
        mock_pc = _mock_pyperclip()
        mock_pc.paste.return_value = "init"
        with patch.dict(sys.modules, {"pyperclip": mock_pc}):
            result = await tool.execute("watch", {"sub": "start"})
            assert result["status"] == "started"

        result = await tool.execute("watch", {"sub": "stop"})
        assert result["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_watch_changes_returns_list(self, tool: ClipboardOps) -> None:
        result = await tool.execute("watch", {"sub": "changes"})
        assert "changes" in result
        assert isinstance(result["changes"], list)

    @pytest.mark.asyncio
    async def test_watch_start_twice(self, tool: ClipboardOps) -> None:
        mock_pc = _mock_pyperclip()
        mock_pc.paste.return_value = "x"
        with patch.dict(sys.modules, {"pyperclip": mock_pc}):
            await tool.execute("watch", {"sub": "start"})
            result = await tool.execute("watch", {"sub": "start"})
            assert result["status"] == "already_running"
        await tool.execute("watch", {"sub": "stop"})

    @pytest.mark.asyncio
    async def test_watch_unknown_sub(self, tool: ClipboardOps) -> None:
        result = await tool.execute("watch", {"sub": "invalid"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_watch_stop_when_not_running(self, tool: ClipboardOps) -> None:
        result = await tool.execute("watch", {"sub": "stop"})
        assert result["status"] == "not_running"
