"""系统控制工具测试。"""

import os
import tempfile

import pytest

from src.tools.system_control import SystemControl


@pytest.fixture
def tool() -> SystemControl:
    """创建使用临时目录的工具实例。"""
    return SystemControl(workspace=tempfile.mkdtemp())


class TestSystemControl:
    """SystemControl 测试。"""

    @pytest.mark.asyncio
    async def test_list_files_empty(self, tool: SystemControl) -> None:
        result = await tool.execute("list_files", {"path": ""})
        assert "items" in result
        assert isinstance(result["items"], list)

    @pytest.mark.asyncio
    async def test_write_and_read(self, tool: SystemControl) -> None:
        # 写入
        write_result = await tool.execute("write_file", {
            "path": "test.txt",
            "content": "Hello JavasAgent!",
        })
        assert "error" not in write_result

        # 读取
        read_result = await tool.execute("read_file", {"path": "test.txt"})
        assert read_result["content"] == "Hello JavasAgent!"

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, tool: SystemControl) -> None:
        result = await tool.execute("read_file", {"path": "nonexistent.txt"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_create_dir(self, tool: SystemControl) -> None:
        result = await tool.execute("create_dir", {"path": "subdir/nested"})
        assert "created" in result

    @pytest.mark.asyncio
    async def test_delete_file(self, tool: SystemControl) -> None:
        await tool.execute("write_file", {"path": "to_delete.txt", "content": "bye"})
        result = await tool.execute("delete_file", {"path": "to_delete.txt"})
        assert "deleted" in result

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool: SystemControl) -> None:
        result = await tool.execute("unknown_action", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_system_info(self, tool: SystemControl) -> None:
        result = await tool.execute("get_info", {})
        assert "os" in result
        assert "python_version" in result
