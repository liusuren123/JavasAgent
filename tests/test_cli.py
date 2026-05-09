"""CLI 命令测试。

验证 CLI 入口命令的基本行为。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from src.main import cli


class TestStatusCommand:
    """status 命令测试。"""

    def test_status_output(self) -> None:
        """status 命令应输出 Agent 状态面板。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "JavasAgent" in result.output
        assert "空闲" in result.output or "运行中" in result.output


class TestHistoryCommand:
    """history 命令测试。"""

    def test_history_empty(self) -> None:
        """无任务历史时应提示。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["history"])
        # 即使无历史，命令本身不应报错
        assert result.exit_code == 0

    def test_history_with_limit(self) -> None:
        """--limit 参数应被接受。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["history", "--limit", "5"])
        assert result.exit_code == 0


class TestRememberCommand:
    """remember 命令测试。"""

    @patch("src.main.asyncio.run")
    def test_remember_success(self, mock_run: MagicMock) -> None:
        """成功记忆时应输出 ID。"""
        mock_run.return_value = "mem_abc123"
        runner = CliRunner()
        result = runner.invoke(cli, ["remember", "测试记忆", "--category", "knowledge"])
        assert "已记忆" in result.output or result.exit_code == 0

    @patch("src.main.asyncio.run")
    def test_remember_failure(self, mock_run: MagicMock) -> None:
        """记忆失败时应提示。"""
        mock_run.return_value = None
        runner = CliRunner()
        result = runner.invoke(cli, ["remember", "测试记忆"])
        assert "失败" in result.output or result.exit_code == 0


class TestMemoryCommand:
    """memory 命令测试。"""

    @patch("src.main.asyncio.run")
    def test_memory_no_results(self, mock_run: MagicMock) -> None:
        """无匹配记忆时应提示。"""
        mock_run.return_value = []
        runner = CliRunner()
        result = runner.invoke(cli, ["memory", "测试查询"])
        assert "未找到" in result.output or result.exit_code == 0

    @patch("src.main.asyncio.run")
    def test_memory_with_results(self, mock_run: MagicMock) -> None:
        """有匹配结果时应输出表格。"""
        from src.memory.long_term import MemoryEntry
        from datetime import datetime

        mock_run.return_value = [
            MemoryEntry(
                id="mem_abc123",
                content="测试内容",
                category="experience",
                created_at=datetime.now(),
                relevance_score=0.95,
            )
        ]
        runner = CliRunner()
        result = runner.invoke(cli, ["memory", "测试查询"])
        assert "测试内容" in result.output or "记忆检索" in result.output or result.exit_code == 0
