"""系统监控工具测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.system_monitor import DEFAULT_ALERT_RULES, SystemMonitor


@pytest.fixture
def monitor() -> SystemMonitor:
    """创建使用默认配置的监控实例。"""
    return SystemMonitor()


# ── 资源使用 ────────────────────────────────────────────────


class TestResourceUsage:
    """resource_usage 测试。"""

    @pytest.mark.asyncio
    async def test_resource_usage_basic(self, monitor: SystemMonitor) -> None:
        """基本资源使用返回结构正确。"""
        mock_mem = MagicMock(
            total=16 * 1024**3,
            used=8 * 1024**3,
            available=8 * 1024**3,
            percent=50.0,
        )

        with (
            patch("src.tools.system_monitor.psutil.cpu_percent", return_value=25.0),
            patch("src.tools.system_monitor.psutil.cpu_count", return_value=8),
            patch("src.tools.system_monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.tools.system_monitor.psutil.disk_partitions", return_value=[]),
        ):
            result = await monitor.execute("resource_usage", {})

        assert result["success"] is True
        data = result["data"]
        assert data["cpu"]["percent"] == 25.0
        assert data["cpu"]["count_logical"] == 8
        assert data["memory"]["percent"] == 50.0
        assert "total_human" in data["memory"]
        assert isinstance(data["disks"], list)

    @pytest.mark.asyncio
    async def test_resource_usage_with_disks(self, monitor: SystemMonitor) -> None:
        """返回包含磁盘分区信息。"""
        mock_mem = MagicMock(total=16*1024**3, used=8*1024**3, available=8*1024**3, percent=50.0)
        mock_part = MagicMock(mountpoint="/", device="/dev/sda1", fstype="ext4", opts="rw")
        mock_usage = MagicMock(total=500*1024**3, used=250*1024**3, free=250*1024**3, percent=50.0)

        with (
            patch("src.tools.system_monitor.psutil.cpu_percent", return_value=10.0),
            patch("src.tools.system_monitor.psutil.cpu_count", return_value=4),
            patch("src.tools.system_monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.tools.system_monitor.psutil.disk_partitions", return_value=[mock_part]),
            patch("src.tools.system_monitor.psutil.disk_usage", return_value=mock_usage),
        ):
            result = await monitor.execute("resource_usage", {"per_disk": True})

        assert result["success"] is True
        disks = result["data"]["disks"]
        assert len(disks) == 1
        assert disks[0]["percent"] == 50.0
        assert disks[0]["device"] == "/dev/sda1"


# ── 进程排行 ────────────────────────────────────────────────


class TestTopProcesses:
    """top_processes 测试。"""

    @pytest.mark.asyncio
    async def test_top_by_cpu(self, monitor: SystemMonitor) -> None:
        """按 CPU 排序返回正确的进程列表。"""
        mock_procs = []
        for i, (cpu, mem_rss) in enumerate([(80.0, 100), (20.0, 500), (50.0, 200)]):
            proc = MagicMock()
            proc.pid = 100 + i
            proc.name.return_value = f"proc_{i}"
            proc.status.return_value = "running"
            proc.cpu_percent.return_value = cpu
            mem_info = MagicMock(rss=mem_rss * 1024**2, vms=mem_rss * 2 * 1024**2)
            proc.memory_info.return_value = mem_info
            proc.memory_percent.return_value = float(mem_rss) / 10
            mock_procs.append(proc)

        with patch("src.tools.system_monitor.psutil.process_iter", return_value=mock_procs):
            result = await monitor.execute("top_processes", {"sort_by": "cpu", "count": 3})

        assert result["success"] is True
        procs = result["data"]["processes"]
        assert len(procs) == 3
        # CPU 降序: 80, 50, 20
        assert procs[0]["cpu_percent"] == 80.0
        assert procs[1]["cpu_percent"] == 50.0
        assert procs[2]["cpu_percent"] == 20.0

    @pytest.mark.asyncio
    async def test_top_by_memory(self, monitor: SystemMonitor) -> None:
        """按内存排序返回正确的进程列表。"""
        mock_procs = []
        for i, (cpu, mem_rss) in enumerate([(10.0, 500), (5.0, 100), (30.0, 300)]):
            proc = MagicMock()
            proc.pid = 200 + i
            proc.name.return_value = f"app_{i}"
            proc.status.return_value = "running"
            proc.cpu_percent.return_value = cpu
            mem_info = MagicMock(rss=mem_rss * 1024**2, vms=mem_rss * 2 * 1024**2)
            proc.memory_info.return_value = mem_info
            proc.memory_percent.return_value = float(mem_rss) / 10
            mock_procs.append(proc)

        with patch("src.tools.system_monitor.psutil.process_iter", return_value=mock_procs):
            result = await monitor.execute("top_processes", {"sort_by": "memory", "count": 2})

        procs = result["data"]["processes"]
        assert len(procs) == 2
        # 内存降序: 500MB, 300MB
        assert procs[0]["memory_rss"] == 500 * 1024**2
        assert procs[1]["memory_rss"] == 300 * 1024**2

    @pytest.mark.asyncio
    async def test_top_processes_count_limit(self, monitor: SystemMonitor) -> None:
        """count 参数限制返回数量。"""
        mock_procs = []
        for i in range(20):
            proc = MagicMock()
            proc.pid = i
            proc.name.return_value = f"p_{i}"
            proc.status.return_value = "running"
            proc.cpu_percent.return_value = float(i)
            mem_info = MagicMock(rss=100, vms=200)
            proc.memory_info.return_value = mem_info
            proc.memory_percent.return_value = 1.0
            mock_procs.append(proc)

        with patch("src.tools.system_monitor.psutil.process_iter", return_value=mock_procs):
            result = await monitor.execute("top_processes", {"count": 5})

        assert len(result["data"]["processes"]) == 5


# ── 查找进程 ────────────────────────────────────────────────


class TestFindProcess:
    """find_process 测试。"""

    @pytest.mark.asyncio
    async def test_find_by_name_substring(self, monitor: SystemMonitor) -> None:
        """子串匹配查找进程。"""
        procs = []
        for name in ["python.exe", "chrome.exe", "python3"]:
            proc = MagicMock()
            proc.name.return_value = name
            proc.pid = hash(name) % 10000
            proc.status.return_value = "running"
            proc.cpu_percent.return_value = 5.0
            mem_info = MagicMock(rss=100 * 1024**2)
            proc.memory_info.return_value = mem_info
            proc.memory_percent.return_value = 1.0
            procs.append(proc)

        with patch("src.tools.system_monitor.psutil.process_iter", return_value=procs):
            result = await monitor.execute("find_process", {"name": "python"})

        assert result["success"] is True
        assert result["data"]["count"] == 2  # python.exe 和 python3

    @pytest.mark.asyncio
    async def test_find_exact_match(self, monitor: SystemMonitor) -> None:
        """精确匹配查找进程。"""
        procs = []
        for name in ["python.exe", "python3"]:
            proc = MagicMock()
            proc.name.return_value = name
            proc.pid = hash(name) % 10000
            proc.status.return_value = "running"
            proc.cpu_percent.return_value = 5.0
            mem_info = MagicMock(rss=100 * 1024**2)
            proc.memory_info.return_value = mem_info
            proc.memory_percent.return_value = 1.0
            procs.append(proc)

        with patch("src.tools.system_monitor.psutil.process_iter", return_value=procs):
            result = await monitor.execute("find_process", {"name": "python.exe", "exact": True})

        assert result["success"] is True
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_find_no_match(self, monitor: SystemMonitor) -> None:
        """无匹配结果时报错。"""
        with patch("src.tools.system_monitor.psutil.process_iter", return_value=[]):
            result = await monitor.execute("find_process", {"name": "nonexistent"})

        assert result["success"] is False
        assert "未找到" in result["error"]

    @pytest.mark.asyncio
    async def test_find_missing_name(self, monitor: SystemMonitor) -> None:
        """缺少 name 参数时报错。"""
        result = await monitor.execute("find_process", {})
        assert result["success"] is False
        assert "name" in result["error"]


# ── 告警检查 ────────────────────────────────────────────────


class TestCheckAlerts:
    """check_alerts 测试。"""

    @pytest.mark.asyncio
    async def test_no_alerts_when_normal(self, monitor: SystemMonitor) -> None:
        """正常范围时不触发告警。"""
        mock_mem = MagicMock(percent=50.0)

        with (
            patch("src.tools.system_monitor.psutil.cpu_percent", return_value=30.0),
            patch("src.tools.system_monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.tools.system_monitor.psutil.disk_partitions", return_value=[]),
        ):
            result = await monitor.execute("check_alerts", {})

        assert result["success"] is True
        assert result["data"]["alert_count"] == 0
        assert result["data"]["alerts"] == []

    @pytest.mark.asyncio
    async def test_cpu_alert_triggered(self, monitor: SystemMonitor) -> None:
        """CPU 超过阈值触发告警。"""
        mock_mem = MagicMock(percent=50.0)

        with (
            patch("src.tools.system_monitor.psutil.cpu_percent", return_value=95.0),
            patch("src.tools.system_monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.tools.system_monitor.psutil.disk_partitions", return_value=[]),
        ):
            result = await monitor.execute("check_alerts", {})

        assert result["success"] is True
        assert result["data"]["alert_count"] >= 1
        alert_metrics = [a["metric"] for a in result["data"]["alerts"]]
        assert "cpu_percent" in alert_metrics

    @pytest.mark.asyncio
    async def test_memory_alert_triggered(self, monitor: SystemMonitor) -> None:
        """内存超过阈值触发告警。"""
        mock_mem = MagicMock(percent=95.0)

        with (
            patch("src.tools.system_monitor.psutil.cpu_percent", return_value=30.0),
            patch("src.tools.system_monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.tools.system_monitor.psutil.disk_partitions", return_value=[]),
        ):
            result = await monitor.execute("check_alerts", {})

        alert_metrics = [a["metric"] for a in result["data"]["alerts"]]
        assert "memory_percent" in alert_metrics

    @pytest.mark.asyncio
    async def test_disk_alert_triggered(self, monitor: SystemMonitor) -> None:
        """磁盘超过阈值触发告警。"""
        mock_mem = MagicMock(percent=50.0)
        mock_part = MagicMock(mountpoint="C:\\")
        mock_usage = MagicMock(percent=98.0)

        with (
            patch("src.tools.system_monitor.psutil.cpu_percent", return_value=30.0),
            patch("src.tools.system_monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.tools.system_monitor.psutil.disk_partitions", return_value=[mock_part]),
            patch("src.tools.system_monitor.psutil.disk_usage", return_value=mock_usage),
        ):
            result = await monitor.execute("check_alerts", {})

        alert_metrics = [a["metric"] for a in result["data"]["alerts"]]
        assert "disk_percent" in alert_metrics

    @pytest.mark.asyncio
    async def test_custom_rules(self, monitor: SystemMonitor) -> None:
        """自定义规则覆盖默认规则。"""
        mock_mem = MagicMock(percent=70.0)

        custom_rules = [{"metric": "cpu_percent", "threshold": 50.0, "op": ">"}]

        with (
            patch("src.tools.system_monitor.psutil.cpu_percent", return_value=60.0),
            patch("src.tools.system_monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.tools.system_monitor.psutil.disk_partitions", return_value=[]),
        ):
            result = await monitor.execute("check_alerts", {"rules": custom_rules})

        assert result["data"]["alert_count"] == 1
        assert result["data"]["alerts"][0]["metric"] == "cpu_percent"


# ── 系统快照 ────────────────────────────────────────────────


class TestSnapshot:
    """snapshot 测试。"""

    @pytest.mark.asyncio
    async def test_snapshot_structure(self, monitor: SystemMonitor) -> None:
        """快照包含所有必要字段。"""
        mock_mem = MagicMock(
            total=16*1024**3, used=8*1024**3, available=8*1024**3, percent=50.0,
        )
        mock_part = MagicMock(mountpoint="/", device="/dev/sda1", fstype="ext4", opts="rw")
        mock_usage = MagicMock(total=500*1024**3, used=250*1024**3, free=250*1024**3, percent=50.0)

        with (
            patch("src.tools.system_monitor.psutil.cpu_percent", return_value=25.0),
            patch("src.tools.system_monitor.psutil.cpu_count", return_value=8),
            patch("src.tools.system_monitor.psutil.virtual_memory", return_value=mock_mem),
            patch("src.tools.system_monitor.psutil.disk_partitions", return_value=[mock_part]),
            patch("src.tools.system_monitor.psutil.disk_usage", return_value=mock_usage),
            patch("src.tools.system_monitor.psutil.process_iter", return_value=[]),
            patch("src.tools.system_monitor.psutil.boot_time", return_value=1700000000.0),
            patch("src.tools.system_monitor.platform.node", return_value="test-host"),
        ):
            result = await monitor.execute("snapshot", {"top_count": 3})

        assert result["success"] is True
        data = result["data"]
        assert "timestamp" in data
        assert "system" in data
        assert "resources" in data
        assert "top_cpu_processes" in data
        assert "top_memory_processes" in data
        assert "alerts" in data
        assert "alert_count" in data
        assert isinstance(data["top_cpu_processes"], list)


# ── 未知操作 ────────────────────────────────────────────────


class TestMisc:
    """杂项测试。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, monitor: SystemMonitor) -> None:
        """未知操作返回错误。"""
        result = await monitor.execute("unknown_action", {})
        assert result["success"] is False
        assert "未知操作" in result["error"]
