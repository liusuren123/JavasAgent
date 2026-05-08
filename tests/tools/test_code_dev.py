"""代码开发工具测试。"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.code_dev import CodeDev


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """创建临时工作目录并写入示例文件。"""
    code_file = tmp_path / "example.py"
    code_file.write_text(
        "def hello():\n    return 'hello'\n\ndef world():\n    return 'world'\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def tool(workspace: Path) -> CodeDev:
    """创建使用临时目录的 CodeDev 实例（无 LLM）。"""
    return CodeDev(workspace=str(workspace))


@pytest.fixture
def tool_with_llm(workspace: Path) -> CodeDev:
    """创建带 mock LLM 客户端的 CodeDev 实例。"""
    llm = MagicMock()
    llm.chat_with_system = AsyncMock(return_value="print('hello')")
    return CodeDev(workspace=str(workspace), llm_client=llm)


# ===========================================================================
# generate_code
# ===========================================================================


class TestGenerateCode:
    """generate_code 测试。"""

    @pytest.mark.asyncio
    async def test_generate_code_success(self, tool_with_llm: CodeDev) -> None:
        result = await tool_with_llm.execute("generate_code", {
            "prompt": "写一个 hello world",
            "language": "python",
        })
        assert "error" not in result
        assert "code" in result
        assert result["language"] == "python"

    @pytest.mark.asyncio
    async def test_generate_code_no_llm(self, tool: CodeDev) -> None:
        result = await tool.execute("generate_code", {"prompt": "test"})
        assert "error" in result
        assert "LLM" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_code_missing_prompt(self, tool_with_llm: CodeDev) -> None:
        result = await tool_with_llm.execute("generate_code", {})
        assert "error" in result
        assert "prompt" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_code_llm_failure(self, tool_with_llm: CodeDev) -> None:
        tool_with_llm._llm_client.chat_with_system = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        result = await tool_with_llm.execute("generate_code", {"prompt": "test"})
        assert "error" in result
        assert "API error" in result["error"]


# ===========================================================================
# read_code
# ===========================================================================


class TestReadCode:
    """read_code 测试。"""

    @pytest.mark.asyncio
    async def test_read_code_success(self, tool: CodeDev) -> None:
        result = await tool.execute("read_code", {"path": "example.py"})
        assert "error" not in result
        assert "content" in result
        assert result["language"] == "py"
        assert result["total_lines"] == 5

    @pytest.mark.asyncio
    async def test_read_code_with_line_range(self, tool: CodeDev) -> None:
        result = await tool.execute("read_code", {
            "path": "example.py",
            "start_line": 1,
            "end_line": 2,
        })
        assert "error" not in result
        assert result["total_lines"] == 2

    @pytest.mark.asyncio
    async def test_read_code_nonexistent(self, tool: CodeDev) -> None:
        result = await tool.execute("read_code", {"path": "missing.py"})
        assert "error" in result


# ===========================================================================
# edit_code
# ===========================================================================


class TestEditCode:
    """edit_code 测试。"""

    @pytest.mark.asyncio
    async def test_edit_code_by_line_range(self, tool: CodeDev, workspace: Path) -> None:
        result = await tool.execute("edit_code", {
            "path": "example.py",
            "start_line": 1,
            "end_line": 1,
            "replacement": "def greet():",
        })
        assert "error" not in result
        assert result["original_lines"] == 5

        # 验证文件内容
        content = (workspace / "example.py").read_text(encoding="utf-8")
        assert "def greet():" in content

    @pytest.mark.asyncio
    async def test_edit_code_by_regex(self, tool: CodeDev, workspace: Path) -> None:
        result = await tool.execute("edit_code", {
            "path": "example.py",
            "pattern": r"return 'hello'",
            "replacement": "return 'hi'",
        })
        assert "error" not in result

        content = (workspace / "example.py").read_text(encoding="utf-8")
        assert "return 'hi'" in content

    @pytest.mark.asyncio
    async def test_edit_code_nonexistent_file(self, tool: CodeDev) -> None:
        result = await tool.execute("edit_code", {
            "path": "missing.py",
            "start_line": 1,
            "end_line": 1,
            "replacement": "x",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_edit_code_invalid_line_range(self, tool: CodeDev) -> None:
        result = await tool.execute("edit_code", {
            "path": "example.py",
            "start_line": 10,
            "end_line": 20,
            "replacement": "x",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_edit_code_no_mode_params(self, tool: CodeDev) -> None:
        result = await tool.execute("edit_code", {"path": "example.py"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_edit_code_bad_regex(self, tool: CodeDev) -> None:
        result = await tool.execute("edit_code", {
            "path": "example.py",
            "pattern": "[invalid",
            "replacement": "x",
        })
        assert "error" in result


# ===========================================================================
# run_test
# ===========================================================================


class TestRunTest:
    """run_test 测试。"""

    @pytest.mark.asyncio
    async def test_run_test_success(self, tool: CodeDev) -> None:
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"returncode": 0, "stdout": "2 passed", "stderr": ""}
            result = await tool.execute("run_test", {"target": "tests/"})
            assert result["returncode"] == 0
            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_test_with_args(self, tool: CodeDev) -> None:
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"returncode": 1, "stdout": "", "stderr": "FAILED"}
            result = await tool.execute("run_test", {
                "target": "tests/",
                "args": ["-v", "--tb=short"],
            })
            assert result["returncode"] == 1
            cmd_parts = mock_run.call_args[0][0]
            assert "-v" in cmd_parts
            assert "--tb=short" in cmd_parts

    @pytest.mark.asyncio
    async def test_run_test_timeout(self, tool: CodeDev) -> None:
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"error": "命令超时 (30s): ..."}
            result = await tool.execute("run_test", {"target": "tests/", "timeout": 30})
            assert "error" in result


# ===========================================================================
# git_operation
# ===========================================================================


class TestGitOperation:
    """git_operation 测试。"""

    @pytest.mark.asyncio
    async def test_git_status(self, tool: CodeDev) -> None:
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"returncode": 0, "stdout": "On branch main", "stderr": ""}
            result = await tool.execute("git_operation", {"command": "status"})
            assert result["returncode"] == 0
            cmd_parts = mock_run.call_args[0][0]
            assert "git" in cmd_parts
            assert "status" in cmd_parts

    @pytest.mark.asyncio
    async def test_git_commit_with_args(self, tool: CodeDev) -> None:
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"returncode": 0, "stdout": "", "stderr": ""}
            result = await tool.execute("git_operation", {
                "command": "commit",
                "args": ["-m", "test commit"],
            })
            assert result["returncode"] == 0

    @pytest.mark.asyncio
    async def test_git_missing_command(self, tool: CodeDev) -> None:
        result = await tool.execute("git_operation", {})
        assert "error" in result
        assert "command" in result["error"]

    @pytest.mark.asyncio
    async def test_git_invalid_command(self, tool: CodeDev) -> None:
        result = await tool.execute("git_operation", {"command": "rebase"})
        assert "error" in result
        assert "不支持" in result["error"]


# ===========================================================================
# lint
# ===========================================================================


class TestLint:
    """lint 测试。"""

    @pytest.mark.asyncio
    async def test_lint_success(self, tool: CodeDev) -> None:
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"returncode": 0, "stdout": "All checks passed!", "stderr": ""}
            result = await tool.execute("lint", {"target": "src/"})
            assert result["returncode"] == 0
            cmd_parts = mock_run.call_args[0][0]
            assert "ruff" in cmd_parts
            assert "check" in cmd_parts

    @pytest.mark.asyncio
    async def test_lint_with_fix(self, tool: CodeDev) -> None:
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"returncode": 0, "stdout": "", "stderr": ""}
            result = await tool.execute("lint", {"target": "src/", "fix": True})
            cmd_parts = mock_run.call_args[0][0]
            assert "--fix" in cmd_parts

    @pytest.mark.asyncio
    async def test_lint_with_errors(self, tool: CodeDev) -> None:
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {
                "returncode": 1,
                "stdout": "Found 3 errors",
                "stderr": "",
            }
            result = await tool.execute("lint", {})
            assert result["returncode"] == 1


# ===========================================================================
# install_deps
# ===========================================================================


class TestInstallDeps:
    """install_deps 测试。"""

    @pytest.mark.asyncio
    async def test_install_with_pip(self, tool: CodeDev) -> None:
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"returncode": 0, "stdout": "Successfully installed", "stderr": ""}
            result = await tool.execute("install_deps", {
                "packages": ["requests"],
                "manager": "pip",
            })
            assert result["returncode"] == 0
            cmd_parts = mock_run.call_args[0][0]
            assert "pip" in cmd_parts
            assert "install" in cmd_parts
            assert "requests" in cmd_parts

    @pytest.mark.asyncio
    async def test_install_with_uv(self, tool: CodeDev) -> None:
        with patch.object(tool, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"returncode": 0, "stdout": "", "stderr": ""}
            result = await tool.execute("install_deps", {
                "packages": ["ruff"],
                "manager": "uv",
            })
            cmd_parts = mock_run.call_args[0][0]
            assert "uv" in cmd_parts
            assert "ruff" in cmd_parts

    @pytest.mark.asyncio
    async def test_install_missing_packages(self, tool: CodeDev) -> None:
        result = await tool.execute("install_deps", {})
        assert "error" in result
        assert "packages" in result["error"]

    @pytest.mark.asyncio
    async def test_install_invalid_manager(self, tool: CodeDev) -> None:
        result = await tool.execute("install_deps", {
            "packages": ["foo"],
            "manager": "conda",
        })
        assert "error" in result
        assert "不支持" in result["error"]


# ===========================================================================
# 统一入口
# ===========================================================================


class TestExecuteDispatch:
    """execute 分发测试。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool: CodeDev) -> None:
        result = await tool.execute("unknown_action", {})
        assert "error" in result
        assert "未知操作" in result["error"]

    @pytest.mark.asyncio
    async def test_run_command_timeout(self, tool: CodeDev) -> None:
        """_run_command 超时场景。"""
        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_sp:
            proc = MagicMock()
            proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_sp.return_value = proc
            result = await tool._run_command(["sleep", "999"], timeout=1)
            assert "error" in result
            assert "超时" in result["error"]

    @pytest.mark.asyncio
    async def test_run_command_exception(self, tool: CodeDev) -> None:
        """_run_command 异常场景。"""
        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_sp:
            mock_sp.side_effect = OSError("spawn failed")
            result = await tool._run_command(["bad_cmd"])
            assert "error" in result
            assert "spawn failed" in result["error"]
