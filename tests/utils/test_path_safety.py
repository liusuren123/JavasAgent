"""路径安全工具测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.utils.path_safety import PathSafetyError, is_safe_path, safe_resolve_path


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """创建临时工作目录。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "readme.md").write_text("# docs")
    (tmp_path / "config.yaml").write_text("key: value")
    return tmp_path


class TestSafeResolvePath:
    """safe_resolve_path 测试。"""

    def test_normal_relative_path(self, workspace: Path) -> None:
        """正常相对路径应正常解析。"""
        result = safe_resolve_path(workspace, "src/main.py")
        assert result == workspace / "src" / "main.py"

    def test_directory_path(self, workspace: Path) -> None:
        """目录路径应正常解析。"""
        result = safe_resolve_path(workspace, "src")
        assert result == workspace / "src"

    def test_simple_filename(self, workspace: Path) -> None:
        """简单文件名应正常解析。"""
        result = safe_resolve_path(workspace, "config.yaml")
        assert result == workspace / "config.yaml"

    def test_nested_path(self, workspace: Path) -> None:
        """嵌套路径应正常解析。"""
        result = safe_resolve_path(workspace, "docs/readme.md")
        assert result == workspace / "docs" / "readme.md"

    def test_traversal_with_dotdot(self, workspace: Path) -> None:
        """包含 .. 的路径遍历应被阻止。"""
        with pytest.raises(PathSafetyError, match="遍历序列"):
            safe_resolve_path(workspace, "../../../etc/passwd")

    def test_traversal_hidden_dotdot(self, workspace: Path) -> None:
        """隐藏的路径遍历应被阻止。"""
        with pytest.raises(PathSafetyError, match="遍历序列"):
            safe_resolve_path(workspace, "src/../../../etc/passwd")

    def test_traversal_to_root(self, workspace: Path) -> None:
        """指向根目录的路径遍历应被阻止。"""
        with pytest.raises(PathSafetyError):
            safe_resolve_path(workspace, "../../etc/passwd")

    def test_absolute_path_outside(self, workspace: Path) -> None:
        """绝对路径应被阻止（解析后超出工作区）。"""
        with pytest.raises(PathSafetyError):
            safe_resolve_path(workspace, "/etc/passwd")

    def test_empty_path_raises(self, workspace: Path) -> None:
        """空路径应报错。"""
        with pytest.raises(PathSafetyError, match="不能为空"):
            safe_resolve_path(workspace, "")

    def test_allow_create_parents(self, workspace: Path) -> None:
        """allow_create_parents 应创建不存在的父目录。"""
        result = safe_resolve_path(
            workspace, "new/deep/path/file.txt", allow_create_parents=True
        )
        assert result.parent.exists()

    def test_no_create_parents_by_default(self, workspace: Path) -> None:
        """默认不创建父目录，但路径解析仍成功。"""
        result = safe_resolve_path(workspace, "new/deep/path/file.txt")
        assert not result.parent.exists()


class TestIsSafePath:
    """is_safe_path 测试。"""

    def test_safe_path(self, workspace: Path) -> None:
        """安全路径返回 True。"""
        assert is_safe_path(workspace, "src/main.py") is True

    def test_unsafe_path(self, workspace: Path) -> None:
        """不安全路径返回 False。"""
        assert is_safe_path(workspace, "../../../etc/passwd") is False

    def test_empty_path(self, workspace: Path) -> None:
        """空路径返回 False。"""
        assert is_safe_path(workspace, "") is False


class TestPathSafetyIntegration:
    """路径安全与工具集成测试。"""

    def test_system_control_rejects_traversal(self, workspace: Path) -> None:
        """SystemControl 工具应拒绝路径遍历。"""
        import asyncio

        from src.tools.system_control import SystemControl

        tool = SystemControl(workspace=str(workspace))

        result = asyncio.run(
            tool.execute("read_file", {"path": "../../../etc/passwd"})
        )
        assert "error" in result
        assert "遍历" in result["error"] or "超出" in result["error"]

    def test_system_control_accepts_normal_path(self, workspace: Path) -> None:
        """SystemControl 工具应接受正常路径。"""
        import asyncio

        from src.tools.system_control import SystemControl

        tool = SystemControl(workspace=str(workspace))

        result = asyncio.run(
            tool.execute("read_file", {"path": "config.yaml"})
        )
        assert "content" in result
        assert result["content"] == "key: value"

    def test_code_dev_rejects_traversal(self, workspace: Path) -> None:
        """CodeDev 工具应拒绝路径遍历。"""
        import asyncio

        from src.tools.code_dev import CodeDev

        tool = CodeDev(workspace=str(workspace))

        result = asyncio.run(
            tool.execute("read_code", {"path": "../../../etc/passwd"})
        )
        assert "error" in result
        assert "遍历" in result["error"] or "超出" in result["error"]

    def test_code_dev_accepts_normal_path(self, workspace: Path) -> None:
        """CodeDev 工具应接受正常路径。"""
        import asyncio

        from src.tools.code_dev import CodeDev

        tool = CodeDev(workspace=str(workspace))

        result = asyncio.run(
            tool.execute("read_code", {"path": "src/main.py"})
        )
        assert "content" in result
        assert "hello" in result["content"]

    def test_write_file_rejects_traversal(self, workspace: Path) -> None:
        """写入操作应拒绝路径遍历。"""
        import asyncio

        from src.tools.system_control import SystemControl

        tool = SystemControl(workspace=str(workspace))

        result = asyncio.run(
            tool.execute("write_file", {
                "path": "../../../tmp/malicious.py",
                "content": "evil",
            })
        )
        assert "error" in result

    def test_delete_file_rejects_traversal(self, workspace: Path) -> None:
        """删除操作应拒绝路径遍历。"""
        import asyncio

        from src.tools.system_control import SystemControl

        tool = SystemControl(workspace=str(workspace))

        result = asyncio.run(
            tool.execute("delete_file", {"path": "../../../important_file"})
        )
        assert "error" in result

    def test_edit_code_rejects_traversal(self, workspace: Path) -> None:
        """代码编辑应拒绝路径遍历。"""
        import asyncio

        from src.tools.code_dev import CodeDev

        tool = CodeDev(workspace=str(workspace))

        result = asyncio.run(
            tool.execute("edit_code", {
                "path": "../../../tmp/evil.py",
                "pattern": "old",
                "replacement": "new",
            })
        )
        assert "error" in result
