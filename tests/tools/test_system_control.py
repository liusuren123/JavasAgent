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


# ─── copy 操作测试 ───────────────────────────────────────────


class TestCopy:
    """copy 操作测试。"""

    @pytest.mark.asyncio
    async def test_copy_file(self, tool: SystemControl) -> None:
        """正常复制文件。"""
        await tool.execute("write_file", {"path": "src.txt", "content": "data"})
        result = await tool.execute("copy", {"src": "src.txt", "dst": "dst.txt"})
        assert "error" not in result
        assert result["copied_from"].endswith("src.txt")

        read = await tool.execute("read_file", {"path": "dst.txt"})
        assert read["content"] == "data"

    @pytest.mark.asyncio
    async def test_copy_directory(self, tool: SystemControl) -> None:
        """正常复制目录。"""
        await tool.execute("create_dir", {"path": "srcdir"})
        await tool.execute("write_file", {"path": "srcdir/a.txt", "content": "A"})
        result = await tool.execute("copy", {"src": "srcdir", "dst": "dstdir"})
        assert "error" not in result

        read = await tool.execute("read_file", {"path": "dstdir/a.txt"})
        assert read["content"] == "A"

    @pytest.mark.asyncio
    async def test_copy_src_not_exist(self, tool: SystemControl) -> None:
        """源文件不存在时报错。"""
        result = await tool.execute("copy", {"src": "nope.txt", "dst": "dst.txt"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_copy_dst_exists_no_overwrite(self, tool: SystemControl) -> None:
        """目标已存在且 overwrite=false 时报错。"""
        await tool.execute("write_file", {"path": "a.txt", "content": "a"})
        await tool.execute("write_file", {"path": "b.txt", "content": "b"})
        result = await tool.execute("copy", {"src": "a.txt", "dst": "b.txt"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_copy_overwrite(self, tool: SystemControl) -> None:
        """overwrite=true 时覆盖目标文件。"""
        await tool.execute("write_file", {"path": "a.txt", "content": "original"})
        await tool.execute("write_file", {"path": "b.txt", "content": "old"})
        result = await tool.execute("copy", {
            "src": "a.txt", "dst": "b.txt", "overwrite": True,
        })
        assert "error" not in result
        read = await tool.execute("read_file", {"path": "b.txt"})
        assert read["content"] == "original"

    @pytest.mark.asyncio
    async def test_copy_dir_overwrite(self, tool: SystemControl) -> None:
        """overwrite=true 时覆盖目标目录。"""
        await tool.execute("create_dir", {"path": "srcdir"})
        await tool.execute("write_file", {"path": "srcdir/f.txt", "content": "new"})
        await tool.execute("create_dir", {"path": "dstdir"})
        result = await tool.execute("copy", {
            "src": "srcdir", "dst": "dstdir", "overwrite": True,
        })
        assert "error" not in result
        read = await tool.execute("read_file", {"path": "dstdir/f.txt"})
        assert read["content"] == "new"


# ─── move 操作测试 ───────────────────────────────────────────


class TestMove:
    """move 操作测试。"""

    @pytest.mark.asyncio
    async def test_move_file(self, tool: SystemControl) -> None:
        """正常移动文件。"""
        await tool.execute("write_file", {"path": "orig.txt", "content": "move me"})
        result = await tool.execute("move", {"src": "orig.txt", "dst": "moved.txt"})
        assert "error" not in result

        read = await tool.execute("read_file", {"path": "moved.txt"})
        assert read["content"] == "move me"

        # 源文件应已不存在
        check = await tool.execute("read_file", {"path": "orig.txt"})
        assert "error" in check

    @pytest.mark.asyncio
    async def test_move_directory(self, tool: SystemControl) -> None:
        """正常移动目录。"""
        await tool.execute("create_dir", {"path": "olddir"})
        await tool.execute("write_file", {"path": "olddir/x.txt", "content": "X"})
        result = await tool.execute("move", {"src": "olddir", "dst": "newdir"})
        assert "error" not in result

        read = await tool.execute("read_file", {"path": "newdir/x.txt"})
        assert read["content"] == "X"

    @pytest.mark.asyncio
    async def test_move_src_not_exist(self, tool: SystemControl) -> None:
        """源路径不存在时报错。"""
        result = await tool.execute("move", {"src": "ghost.txt", "dst": "dst.txt"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_move_dst_exists_no_overwrite(self, tool: SystemControl) -> None:
        """目标已存在且 overwrite=false 时报错。"""
        await tool.execute("write_file", {"path": "a.txt", "content": "a"})
        await tool.execute("write_file", {"path": "b.txt", "content": "b"})
        result = await tool.execute("move", {"src": "a.txt", "dst": "b.txt"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_move_overwrite_file(self, tool: SystemControl) -> None:
        """overwrite=true 时覆盖目标文件。"""
        await tool.execute("write_file", {"path": "src.txt", "content": "fresh"})
        await tool.execute("write_file", {"path": "dst.txt", "content": "stale"})
        result = await tool.execute("move", {
            "src": "src.txt", "dst": "dst.txt", "overwrite": True,
        })
        assert "error" not in result
        read = await tool.execute("read_file", {"path": "dst.txt"})
        assert read["content"] == "fresh"


# ─── rename 操作测试 ─────────────────────────────────────────


class TestRename:
    """rename 操作测试。"""

    @pytest.mark.asyncio
    async def test_rename_file(self, tool: SystemControl) -> None:
        """正常重命名文件。"""
        await tool.execute("write_file", {"path": "old.txt", "content": "rename"})
        result = await tool.execute("rename", {"path": "old.txt", "new_name": "new.txt"})
        assert "error" not in result
        assert result["renamed_to"].endswith("new.txt")

        read = await tool.execute("read_file", {"path": "new.txt"})
        assert read["content"] == "rename"

    @pytest.mark.asyncio
    async def test_rename_directory(self, tool: SystemControl) -> None:
        """正常重命名目录。"""
        await tool.execute("create_dir", {"path": "olddir"})
        result = await tool.execute("rename", {"path": "olddir", "new_name": "newdir"})
        assert "error" not in result

        listing = await tool.execute("list_files", {"path": ""})
        names = [i["name"] for i in listing["items"]]
        assert "newdir" in names
        assert "olddir" not in names

    @pytest.mark.asyncio
    async def test_rename_path_not_exist(self, tool: SystemControl) -> None:
        """路径不存在时报错。"""
        result = await tool.execute("rename", {"path": "nope.txt", "new_name": "yep.txt"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rename_missing_new_name(self, tool: SystemControl) -> None:
        """缺少 new_name 参数时报错。"""
        await tool.execute("write_file", {"path": "f.txt", "content": "x"})
        result = await tool.execute("rename", {"path": "f.txt"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rename_target_exists(self, tool: SystemControl) -> None:
        """目标名称已存在时报错。"""
        await tool.execute("write_file", {"path": "a.txt", "content": "a"})
        await tool.execute("write_file", {"path": "b.txt", "content": "b"})
        result = await tool.execute("rename", {"path": "a.txt", "new_name": "b.txt"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rename_with_separator(self, tool: SystemControl) -> None:
        """new_name 包含路径分隔符时报错。"""
        await tool.execute("write_file", {"path": "f.txt", "content": "x"})
        result = await tool.execute("rename", {"path": "f.txt", "new_name": "sub/name.txt"})
        assert "error" in result


# ─── search_files 操作测试 ────────────────────────────────────


class TestSearchFiles:
    """search_files 操作测试。"""

    @pytest.mark.asyncio
    async def test_search_by_extension(self, tool: SystemControl) -> None:
        """按扩展名搜索文件。"""
        await tool.execute("write_file", {"path": "a.py", "content": "py"})
        await tool.execute("write_file", {"path": "b.txt", "content": "txt"})
        result = await tool.execute("search_files", {"pattern": "*.py"})
        assert result["count"] == 1
        assert result["files"][0]["name"] == "a.py"

    @pytest.mark.asyncio
    async def test_search_recursive(self, tool: SystemControl) -> None:
        """递归搜索子目录。"""
        await tool.execute("create_dir", {"path": "sub"})
        await tool.execute("write_file", {"path": "sub/deep.py", "content": "deep"})
        await tool.execute("write_file", {"path": "top.py", "content": "top"})
        result = await tool.execute("search_files", {"pattern": "*.py", "recursive": True})
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_search_non_recursive(self, tool: SystemControl) -> None:
        """非递归搜索仅查顶层。"""
        await tool.execute("create_dir", {"path": "sub"})
        await tool.execute("write_file", {"path": "sub/deep.py", "content": "deep"})
        await tool.execute("write_file", {"path": "top.py", "content": "top"})
        result = await tool.execute("search_files", {"pattern": "*.py", "recursive": False})
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_search_max_results(self, tool: SystemControl) -> None:
        """max_results 限制返回数量。"""
        for i in range(5):
            await tool.execute("write_file", {"path": f"f{i}.txt", "content": str(i)})
        result = await tool.execute("search_files", {"pattern": "*.txt", "max_results": 2})
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_search_path_not_exist(self, tool: SystemControl) -> None:
        """搜索路径不存在时报错。"""
        result = await tool.execute("search_files", {"path": "nope", "pattern": "*"})
        assert "error" in result


# ─── disk_usage 操作测试 ─────────────────────────────────────


class TestDiskUsage:
    """disk_usage 操作测试。"""

    @pytest.mark.asyncio
    async def test_disk_usage_default(self, tool: SystemControl) -> None:
        """默认返回 workspace 磁盘信息。"""
        result = await tool.execute("disk_usage", {})
        assert "error" not in result
        assert "total" in result
        assert "used" in result
        assert "free" in result
        assert "total_human" in result
        assert result["total"] > 0

    @pytest.mark.asyncio
    async def test_disk_usage_specific_path(self, tool: SystemControl) -> None:
        """指定路径返回磁盘信息。"""
        await tool.execute("create_dir", {"path": "mydir"})
        result = await tool.execute("disk_usage", {"path": "mydir"})
        assert "error" not in result
        assert "total" in result
