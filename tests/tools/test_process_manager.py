"""进程管理工具测试。"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import psutil
import pytest

from src.tools.process_manager import ProcessManager
from src.tools.process_utils import format_process_info


def _make_mock_process(
    pid: int,
    name: str = "test_proc",
    status: str = "running",
    cpu_percent: float = 1.5,
    rss_mb: float = 50.0,
    vms_mb: float = 200.0,
    ppid: int = 0,
    cmdline: list[str] | None = None,
) -> MagicMock:
    """创建一个 mock 的 psutil.Process 对象。"""
    proc = MagicMock()
    proc.pid = pid
    proc.name.return_value = name
    proc.status.return_value = status
    proc.cpu_percent.return_value = cpu_percent
    proc.ppid.return_value = ppid
    proc.cmdline.return_value = cmdline or ["python", "test.py"]
    proc.create_time.return_value = 1700000000.0

    mem_info = MagicMock()
    mem_info.rss = int(rss_mb * 1024 * 1024)
    mem_info.vms = int(vms_mb * 1024 * 1024)
    proc.memory_info.return_value = mem_info

    return proc


@pytest.fixture
def pm() -> ProcessManager:
    """创建 ProcessManager 实例。"""
    return ProcessManager()


class TestExecuteRouting:
    """execute 方法的 action 路由测试。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, pm: ProcessManager) -> None:
        result = await pm.execute("invalid_action", {})
        assert result["success"] is False
        assert "未知操作" in result["error"]

    @pytest.mark.asyncio
    async def test_known_actions_routed(self, pm: ProcessManager) -> None:
        """验证所有已知 action 都能路由到对应方法。"""
        for action in ["list", "find", "kill", "get_top", "get_tree"]:
            # 不关心返回值，只验证不会因为 action 不存在而报错
            result = await pm.execute(action, {})
            # 这些操作要么成功要么返回参数错误，但不应是"未知操作"
            assert "未知操作" not in str(result.get("error", ""))


class TestList:
    """list 操作测试。"""

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_list_basic(self, mock_iter, pm: ProcessManager) -> None:
        mock_iter.return_value = [
            _make_mock_process(1, "init", cpu_percent=0.1),
            _make_mock_process(100, "python", cpu_percent=5.0),
            _make_mock_process(200, "chrome", cpu_percent=15.0),
        ]
        result = await pm.execute("list", {})
        assert result["success"] is True
        assert result["data"]["total"] == 3
        assert len(result["data"]["processes"]) == 3

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_list_with_filter(self, mock_iter, pm: ProcessManager) -> None:
        mock_iter.return_value = [
            _make_mock_process(1, "init"),
            _make_mock_process(100, "python"),
            _make_mock_process(200, "chrome"),
        ]
        result = await pm.execute("list", {"filter": "python"})
        assert result["success"] is True
        assert result["data"]["total"] == 1
        assert result["data"]["processes"][0]["name"] == "python"

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_list_pagination(self, mock_iter, pm: ProcessManager) -> None:
        mock_iter.return_value = [_make_mock_process(i, f"proc_{i}") for i in range(25)]
        result = await pm.execute("list", {"page": 1, "page_size": 10})
        assert result["success"] is True
        assert result["data"]["total"] == 25
        assert len(result["data"]["processes"]) == 10
        assert result["data"]["has_more"] is True

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_list_second_page(self, mock_iter, pm: ProcessManager) -> None:
        mock_iter.return_value = [_make_mock_process(i, f"proc_{i}") for i in range(25)]
        result = await pm.execute("list", {"page": 3, "page_size": 10})
        assert result["success"] is True
        assert len(result["data"]["processes"]) == 5
        assert result["data"]["has_more"] is False

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_list_skips_terminated(self, mock_iter, pm: ProcessManager) -> None:
        mock_iter.return_value = [
            _make_mock_process(1, "alive", status="running"),
            _make_mock_process(2, "dead", status="terminated"),
        ]
        result = await pm.execute("list", {})
        assert result["success"] is True
        assert result["data"]["total"] == 1


class TestFind:
    """find 操作测试。"""

    @pytest.mark.asyncio
    async def test_find_missing_params(self, pm: ProcessManager) -> None:
        result = await pm.execute("find", {})
        assert result["success"] is False
        assert "缺少参数" in result["error"]

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.Process")
    async def test_find_by_pid(self, mock_process_cls, pm: ProcessManager) -> None:
        mock_proc = _make_mock_process(1234, "target_proc")
        mock_process_cls.return_value = mock_proc

        result = await pm.execute("find", {"pid": 1234})
        assert result["success"] is True
        assert result["data"]["pid"] == 1234
        assert result["data"]["name"] == "target_proc"

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.Process")
    async def test_find_by_pid_not_found(self, mock_process_cls, pm: ProcessManager) -> None:
        mock_process_cls.side_effect = psutil.NoSuchProcess(9999)
        result = await pm.execute("find", {"pid": 9999})
        assert result["success"] is False
        assert "进程不存在" in result["error"]

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_find_by_name(self, mock_iter, pm: ProcessManager) -> None:
        mock_iter.return_value = [
            _make_mock_process(1, "init"),
            _make_mock_process(100, "python_main"),
            _make_mock_process(200, "python_worker"),
            _make_mock_process(300, "chrome"),
        ]
        result = await pm.execute("find", {"name": "python"})
        assert result["success"] is True
        assert result["data"]["count"] == 2

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_find_by_name_exact(self, mock_iter, pm: ProcessManager) -> None:
        mock_iter.return_value = [
            _make_mock_process(100, "python"),
            _make_mock_process(200, "python_worker"),
        ]
        result = await pm.execute("find", {"name": "python", "exact": True})
        assert result["success"] is True
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_find_by_name_not_found(self, mock_iter, pm: ProcessManager) -> None:
        mock_iter.return_value = [_make_mock_process(1, "init")]
        result = await pm.execute("find", {"name": "nonexistent"})
        assert result["success"] is False
        assert "未找到" in result["error"]


class TestKill:
    """kill 操作测试。"""

    @pytest.mark.asyncio
    async def test_kill_missing_pid(self, pm: ProcessManager) -> None:
        result = await pm.execute("kill", {"confirm": True})
        assert result["success"] is False
        assert "缺少参数" in result["error"]

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.Process")
    async def test_kill_without_confirm(self, mock_process_cls, pm: ProcessManager) -> None:
        mock_proc = _make_mock_process(1234, "test_proc")
        mock_process_cls.return_value = mock_proc

        result = await pm.execute("kill", {"pid": 1234})
        assert result["success"] is False
        assert result["require_confirm"] is True
        assert "confirm" in result["hint"].lower() or "confirm" in result["error"]
        # 确认未调用 terminate/kill
        mock_proc.terminate.assert_not_called()
        mock_proc.kill.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.Process")
    async def test_kill_with_confirm_terminate(self, mock_process_cls, pm: ProcessManager) -> None:
        mock_proc = _make_mock_process(1234, "test_proc")
        mock_proc.children.return_value = []
        mock_process_cls.return_value = mock_proc

        result = await pm.execute("kill", {"pid": 1234, "confirm": True})
        assert result["success"] is True
        assert result["data"]["method"] == "SIGTERM"
        mock_proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.Process")
    async def test_kill_with_force(self, mock_process_cls, pm: ProcessManager) -> None:
        mock_proc = _make_mock_process(1234, "test_proc")
        mock_proc.children.return_value = []
        mock_process_cls.return_value = mock_proc

        result = await pm.execute("kill", {"pid": 1234, "confirm": True, "force": True})
        assert result["success"] is True
        assert result["data"]["method"] == "SIGKILL"
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.Process")
    async def test_kill_not_found(self, mock_process_cls, pm: ProcessManager) -> None:
        mock_process_cls.side_effect = psutil.NoSuchProcess(9999)
        result = await pm.execute("kill", {"pid": 9999, "confirm": True})
        assert result["success"] is False

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.Process")
    async def test_kill_access_denied(self, mock_process_cls, pm: ProcessManager) -> None:
        mock_proc = _make_mock_process(1234, "system_proc")
        mock_proc.children.return_value = []
        mock_proc.terminate.side_effect = psutil.AccessDenied(1234)
        mock_process_cls.return_value = mock_proc

        result = await pm.execute("kill", {"pid": 1234, "confirm": True})
        assert result["success"] is False

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.Process")
    async def test_kill_with_children(self, mock_process_cls, pm: ProcessManager) -> None:
        mock_child = _make_mock_process(5678, "child_proc")
        mock_proc = _make_mock_process(1234, "parent_proc")
        mock_proc.children.return_value = [mock_child]
        mock_process_cls.return_value = mock_proc

        result = await pm.execute("kill", {"pid": 1234, "confirm": True})
        assert result["success"] is True
        assert result["data"]["children_killed"] == 1


class TestGetTop:
    """get_top 操作测试。"""

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_get_top_cpu(self, mock_iter, pm: ProcessManager) -> None:
        mock_iter.return_value = [
            _make_mock_process(1, "low_cpu", cpu_percent=1.0),
            _make_mock_process(2, "high_cpu", cpu_percent=50.0),
            _make_mock_process(3, "mid_cpu", cpu_percent=10.0),
        ]
        result = await pm.execute("get_top", {"sort_by": "cpu", "count": 2})
        assert result["success"] is True
        assert result["data"]["count"] == 2
        assert result["data"]["processes"][0]["name"] == "high_cpu"
        assert result["data"]["processes"][1]["name"] == "mid_cpu"

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_get_top_memory(self, mock_iter, pm: ProcessManager) -> None:
        mock_iter.return_value = [
            _make_mock_process(1, "small", rss_mb=10.0),
            _make_mock_process(2, "big", rss_mb=500.0),
            _make_mock_process(3, "medium", rss_mb=100.0),
        ]
        result = await pm.execute("get_top", {"sort_by": "memory", "count": 2})
        assert result["success"] is True
        assert result["data"]["processes"][0]["name"] == "big"
        assert result["data"]["processes"][1]["name"] == "medium"

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_get_top_default_params(self, mock_iter, pm: ProcessManager) -> None:
        mock_iter.return_value = [_make_mock_process(i, f"p{i}") for i in range(15)]
        result = await pm.execute("get_top", {})
        assert result["success"] is True
        assert result["data"]["count"] == 10  # 默认 count=10


class TestGetTree:
    """get_tree 操作测试。"""

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.process_iter")
    async def test_get_tree_full(self, mock_iter, pm: ProcessManager) -> None:
        parent = _make_mock_process(1, "init", ppid=0)
        child = _make_mock_process(100, "child", ppid=1)
        mock_iter.return_value = [parent, child]

        result = await pm.execute("get_tree", {})
        assert result["success"] is True
        assert result["data"]["total_processes"] == 2

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.Process")
    async def test_get_tree_by_pid(self, mock_process_cls, pm: ProcessManager) -> None:
        mock_proc = _make_mock_process(1234, "target", ppid=1)
        mock_proc.children.return_value = [_make_mock_process(5678, "child", ppid=1234)]
        mock_process_cls.return_value = mock_proc

        result = await pm.execute("get_tree", {"pid": 1234})
        assert result["success"] is True
        assert result["data"]["root_pid"] == 1234

    @pytest.mark.asyncio
    @patch("src.tools.process_manager.psutil.Process")
    async def test_get_tree_pid_not_found(self, mock_process_cls, pm: ProcessManager) -> None:
        mock_process_cls.side_effect = psutil.NoSuchProcess(9999)
        result = await pm.execute("get_tree", {"pid": 9999})
        assert result["success"] is False
        assert "进程不存在" in result["error"]


class TestFormatProcessInfo:
    """process_utils.format_process_info 测试。"""

    def test_basic_info(self) -> None:
        proc = _make_mock_process(1234, "test", cpu_percent=3.5)
        info = format_process_info(proc)
        assert info["pid"] == 1234
        assert info["name"] == "test"
        assert info["status"] == "running"
        assert info["cpu_percent"] == 3.5
        assert "rss_mb" in info["memory_info"]
        assert "cmdline" not in info

    def test_with_cmdline(self) -> None:
        proc = _make_mock_process(1234, "test", cmdline=["python", "-m", "pytest"])
        info = format_process_info(proc, with_cmdline=True)
        assert info["cmdline"] == ["python", "-m", "pytest"]

    def test_no_such_process_graceful(self) -> None:
        proc = MagicMock()
        proc.pid = 9999
        # 让所有 psutil 方法都抛出异常，模拟进程已消失
        proc.name.side_effect = psutil.NoSuchProcess(9999)
        proc.status.side_effect = psutil.NoSuchProcess(9999)
        proc.cpu_percent.side_effect = psutil.NoSuchProcess(9999)
        proc.memory_info.side_effect = psutil.NoSuchProcess(9999)
        proc.create_time.side_effect = psutil.NoSuchProcess(9999)
        info = format_process_info(proc)
        assert info["pid"] == 9999
        assert info["status"] == "unknown"
