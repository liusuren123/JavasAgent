"""T-TL-04: SystemMonitor 系统监控 — 实操测试。

真实调用 psutil 获取系统信息。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.tools.system_monitor import SystemMonitor


@pytest.fixture
def monitor():
    return SystemMonitor()


@pytest.mark.asyncio
async def test_resource_usage(monitor):
    """获取 CPU/内存/磁盘使用情况。"""
    result = await monitor.execute("resource_usage", {})

    assert result["success"] is True, f"resource_usage 失败: {result}"
    data = result["data"]

    # CPU
    assert "cpu" in data
    assert 0 <= data["cpu"]["percent"] <= 100
    assert data["cpu"]["count_logical"] > 0
    print(f"[OK] CPU: {data['cpu']['percent']}% ({data['cpu']['count_logical']} 逻辑核)")

    # 内存
    assert "memory" in data
    assert data["memory"]["total"] > 0
    assert 0 <= data["memory"]["percent"] <= 100
    print(f"[OK] 内存: {data['memory']['percent']}% ({data['memory']['used_human']}/{data['memory']['total_human']})")

    # 磁盘
    assert "disks" in data
    assert len(data["disks"]) > 0
    for disk in data["disks"]:
        print(f"[OK] 磁盘: {disk['mountpoint']} - {disk['percent']}% ({disk['used_human']}/{disk['total_human']})")


@pytest.mark.asyncio
async def test_system_info(monitor):
    """获取系统基本信息。"""
    result = await monitor.execute("system_info", {})

    assert result["success"] is True
    data = result["data"]

    assert "os" in data
    assert "hostname" in data
    assert "uptime_seconds" in data
    assert data["uptime_seconds"] > 0
    print(f"[OK] OS: {data['os']} | 主机: {data['hostname']} | 运行: {data['uptime_human']}")


@pytest.mark.asyncio
async def test_check_alerts(monitor):
    """检查阈值告警。"""
    result = await monitor.execute("check_alerts", {})

    assert result["success"] is True
    data = result["data"]

    assert "alerts" in data
    assert "alert_count" in data
    assert "current_values" in data
    assert "cpu_percent" in data["current_values"]
    print(f"[OK] 告警检查: {data['alert_count']} 个告警 | CPU={data['current_values']['cpu_percent']}% | MEM={data['current_values']['memory_percent']}%")


@pytest.mark.asyncio
async def test_top_processes(monitor):
    """获取 Top 进程。"""
    result = await monitor.execute("top_processes", {"sort_by": "cpu", "count": 5})

    assert result["success"] is True
    data = result["data"]

    assert len(data["processes"]) > 0
    assert len(data["processes"]) <= 5
    for proc in data["processes"]:
        assert "pid" in proc
        assert "name" in proc
    print(f"[OK] Top 进程({data['sort_by']}): {[p['name'] for p in data['processes'][:3]]}...")


@pytest.mark.asyncio
async def test_snapshot(monitor):
    """生成系统快照。"""
    result = await monitor.execute("snapshot", {"top_count": 3})

    assert result["success"] is True
    data = result["data"]

    assert "timestamp" in data
    assert "system" in data
    assert "resources" in data
    assert "alerts" in data
    print(f"[OK] 快照生成: {data['timestamp']} | 告警={data['alert_count']}")


@pytest.mark.asyncio
async def test_unknown_action(monitor):
    """未知操作应返回错误。"""
    result = await monitor.execute("nonexistent_action", {})
    assert result["success"] is False
    assert "未知操作" in result["error"]
    print(f"[OK] 未知操作错误: {result['error'][:50]}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
