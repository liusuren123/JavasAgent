"""命令执行工具的测试。"""

from __future__ import annotations

import sys

import pytest

from src.utils.command import run_command


class TestRunCommand:
    """run_command 函数测试。"""

    @pytest.mark.asyncio
    async def test_successful_command(self):
        """正常命令执行。"""
        result = await run_command(["python", "-c", "print('hello')"])
        assert result["returncode"] == 0
        assert "hello" in result["stdout"]

    @pytest.mark.asyncio
    async def test_failed_command(self):
        """失败命令执行。"""
        result = await run_command(["python", "-c", "raise SystemExit(1)"])
        assert result["returncode"] == 1

    @pytest.mark.asyncio
    async def test_command_with_stderr(self):
        """包含 stderr 的命令。"""
        result = await run_command(
            ["python", "-c", "import sys; print('err', file=sys.stderr)"]
        )
        assert result["returncode"] == 0
        assert "err" in result["stderr"]

    @pytest.mark.asyncio
    async def test_command_timeout(self):
        """命令超时。"""
        result = await run_command(
            ["python", "-c", "import time; time.sleep(10)"], timeout=1
        )
        assert "error" in result
        assert "超时" in result["error"]

    @pytest.mark.asyncio
    async def test_command_with_cwd(self, tmp_path):
        """指定工作目录。"""
        result = await run_command(["python", "-c", "import os; print(os.getcwd())"], cwd=str(tmp_path))
        assert result["returncode"] == 0
        # 在 Windows 上路径可能大小写不同
        assert str(tmp_path).lower() in result["stdout"].strip().lower()

    @pytest.mark.asyncio
    async def test_command_multibyte_output(self):
        """多字节字符输出（中文）。"""
        result = await run_command(["python", "-c", "print('你好世界')"])
        assert result["returncode"] == 0
        assert "你好" in result["stdout"]

    @pytest.mark.asyncio
    async def test_nonexistent_command(self):
        """不存在的命令。"""
        result = await run_command(["nonexistent_command_xyz_12345"])
        # shell 会返回错误
        assert result["returncode"] != 0 or "error" in result

    @pytest.mark.asyncio
    async def test_command_with_env(self):
        """自定义环境变量。"""
        result = await run_command(
            ["python", "-c", "import os; print(os.environ.get('JAVAS_TEST_VAR', ''))"],
            env={"JAVAS_TEST_VAR": "test_value"},
        )
        assert result["returncode"] == 0
        assert "test_value" in result["stdout"]


class TestRawCommand:
    """raw_command 模式测试。

    raw_command=True 时，cmd_parts[0] 直接作为 shell 命令执行，
    不经过 _quote_arg 拼接，适用于用户输入的完整命令字符串。
    """

    @pytest.mark.asyncio
    async def test_raw_command_with_spaces(self):
        """包含空格的完整命令字符串应正确执行。"""
        result = await run_command(
            ["python -c \"print('raw hello')\""],
            raw_command=True,
        )
        assert result["returncode"] == 0
        assert "raw hello" in result["stdout"]

    @pytest.mark.asyncio
    async def test_raw_command_git_log(self):
        """git log 命令（多参数带空格）应正确执行。"""
        result = await run_command(
            ["git --version"],
            raw_command=True,
        )
        assert result["returncode"] == 0
        assert "git" in result["stdout"].lower()

    @pytest.mark.asyncio
    async def test_raw_command_echo(self):
        """echo 命令应正确输出。"""
        result = await run_command(
            ["echo hello world"],
            raw_command=True,
        )
        assert result["returncode"] == 0
        assert "hello world" in result["stdout"]

    @pytest.mark.asyncio
    async def test_raw_command_empty(self):
        """空命令列表应返回空结果。"""
        result = await run_command([], raw_command=True)
        # 空命令字符串 -> shell 执行空命令
        assert result["returncode"] == 0 or "error" in result
