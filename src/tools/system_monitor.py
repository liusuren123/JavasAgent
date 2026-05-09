"""系统监控工具。

提供 CPU/内存/磁盘资源监控、进程排行、网络接口信息、
可配置的阈值告警以及系统状态快照能力。
基于 psutil 实现，是贾维斯主动健康监控的核心工具。
"""

from __future__ import annotations

import datetime
import platform
from typing import Any

import psutil
from loguru import logger


# ── 默认告警规则 ────────────────────────────────────────────

DEFAULT_ALERT_RULES: list[dict[str, Any]] = [
    {"metric": "cpu_percent", "threshold": 90.0, "op": ">"},
    {"metric": "memory_percent", "threshold": 90.0, "op": ">"},
    {"metric": "disk_percent", "threshold": 95.0, "op": ">"},
]


class SystemMonitor:
    """系统监控工具集。

    支持：
    - resource_usage: 获取 CPU / 内存 / 磁盘使用情况
    - top_processes: 列出 Top N 进程（按 cpu 或 memory 排序）
    - find_process: 按名称查找进程
    - system_info: 获取系统基本信息（开机时长、OS 等）
    - network_interfaces: 获取网络接口信息
    - check_alerts: 检查是否有阈值告警
    - snapshot: 生成完整的系统状态快照

    Usage::

        monitor = SystemMonitor()
        result = await monitor.execute("resource_usage", {})
        result = await monitor.execute("top_processes", {"sort_by": "cpu", "count": 5})
        result = await monitor.execute("snapshot", {})
    """

    def __init__(
        self,
        workspace: str | None = None,
        alert_rules: list[dict[str, Any]] | None = None,
    ) -> None:
        self._workspace = workspace
        self._alert_rules = alert_rules or DEFAULT_ALERT_RULES

        self._actions: dict[str, Any] = {
            "resource_usage": self._resource_usage,
            "top_processes": self._top_processes,
            "find_process": self._find_process,
            "system_info": self._system_info,
            "network_interfaces": self._network_interfaces,
            "check_alerts": self._check_alerts,
            "snapshot": self._snapshot,
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行系统监控操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            包含 success 和 data/error 的结果字典
        """
        handler = self._actions.get(action)
        if handler is None:
            logger.error(f"未知操作: {action}")
            return {
                "success": False,
                "error": f"未知操作: {action}，支持: {', '.join(sorted(self._actions.keys()))}",
            }

        try:
            return await handler(params)
        except Exception as e:
            logger.error(f"系统监控操作失败 [{action}]: {e}")
            return {"success": False, "error": f"操作失败: {e}"}

    # ------------------------------------------------------------------
    # 资源使用情况
    # ------------------------------------------------------------------

    async def _resource_usage(self, params: dict) -> dict[str, Any]:
        """获取 CPU / 内存 / 磁盘使用情况。

        Params:
            disk_path: 指定磁盘路径（可选，默认检测所有分区）
            per_disk: 是否返回每个分区的信息（默认 True）
        """
        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_count_physical = psutil.cpu_count(logical=False)

        # 内存
        mem = psutil.virtual_memory()

        # 磁盘
        per_disk = params.get("per_disk", True)
        disk_path = params.get("disk_path")
        disks: list[dict[str, Any]] = []

        if disk_path:
            try:
                usage = psutil.disk_usage(disk_path)
                disks.append(self._format_disk_usage(disk_path, usage))
            except Exception as e:
                logger.warning(f"无法获取磁盘信息: {disk_path} — {e}")
        elif per_disk:
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append(self._format_disk_usage(part.mountpoint, usage, part))
                except (PermissionError, OSError):
                    continue
        else:
            # 只返回根路径所在磁盘
            try:
                usage = psutil.disk_usage("/")
                disks.append(self._format_disk_usage("/", usage))
            except OSError:
                try:
                    usage = psutil.disk_usage("C:\\")
                    disks.append(self._format_disk_usage("C:\\", usage))
                except OSError:
                    pass

        logger.info(
            f"资源使用: CPU {cpu_percent}% | 内存 {mem.percent}% | "
            f"磁盘分区 {len(disks)} 个"
        )

        return {
            "success": True,
            "data": {
                "cpu": {
                    "percent": cpu_percent,
                    "count_logical": cpu_count,
                    "count_physical": cpu_count_physical,
                },
                "memory": {
                    "total": mem.total,
                    "used": mem.used,
                    "available": mem.available,
                    "percent": mem.percent,
                    "total_human": self._bytes_to_gb(mem.total),
                    "used_human": self._bytes_to_gb(mem.used),
                    "available_human": self._bytes_to_gb(mem.available),
                },
                "disks": disks,
            },
        }

    # ------------------------------------------------------------------
    # 进程排行
    # ------------------------------------------------------------------

    async def _top_processes(self, params: dict) -> dict[str, Any]:
        """列出 Top N 进程。

        Params:
            sort_by: 排序依据 (cpu / memory，默认 cpu)
            count: 返回数量（默认 10，最大 50）
        """
        sort_by = params.get("sort_by", "cpu")
        count = min(50, max(1, params.get("count", 10)))

        all_procs: list[dict[str, Any]] = []
        for proc in psutil.process_iter():
            try:
                info: dict[str, Any] = {
                    "pid": proc.pid,
                    "name": proc.name(),
                    "status": proc.status(),
                }
                with proc.oneshot():
                    info["cpu_percent"] = proc.cpu_percent(interval=0)
                    mem_info = proc.memory_info()
                    info["memory_rss"] = mem_info.rss
                    info["memory_rss_human"] = self._bytes_to_mb(mem_info.rss)
                    info["memory_vms"] = mem_info.vms
                    info["memory_percent"] = round(
                        proc.memory_percent(), 2
                    )
                all_procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # 排序
        if sort_by == "memory":
            all_procs.sort(key=lambda p: p.get("memory_rss", 0), reverse=True)
        else:
            all_procs.sort(key=lambda p: p.get("cpu_percent", 0), reverse=True)

        top = all_procs[:count]
        logger.info(f"Top {count} 进程 (按 {sort_by} 排序)")

        return {
            "success": True,
            "data": {
                "processes": top,
                "sort_by": sort_by,
                "count": len(top),
            },
        }

    # ------------------------------------------------------------------
    # 查找进程
    # ------------------------------------------------------------------

    async def _find_process(self, params: dict) -> dict[str, Any]:
        """按名称查找进程。

        Params:
            name: 进程名称（子串匹配）
            exact: 是否精确匹配（默认 False）
        """
        name = params.get("name", "")
        if not name:
            return {"success": False, "error": "缺少参数: name"}

        exact = params.get("exact", False)
        name_lower = name.lower()
        results: list[dict[str, Any]] = []

        for proc in psutil.process_iter():
            try:
                proc_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            if exact:
                if proc_name == name:
                    results.append(self._basic_proc_info(proc))
            else:
                if name_lower in proc_name.lower():
                    results.append(self._basic_proc_info(proc))

        if not results:
            return {"success": False, "error": f"未找到匹配的进程: {name}"}

        logger.info(f"查找进程 '{name}': 找到 {len(results)} 个")
        return {
            "success": True,
            "data": {"processes": results, "count": len(results)},
        }

    # ------------------------------------------------------------------
    # 系统信息
    # ------------------------------------------------------------------

    async def _system_info(self, params: dict) -> dict[str, Any]:
        """获取系统基本信息。

        包括：操作系统、主机名、开机时长、Python 版本等。
        """
        boot_ts = psutil.boot_time()
        uptime_seconds = int(datetime.datetime.now().timestamp() - boot_ts)
        uptime_delta = datetime.timedelta(seconds=uptime_seconds)

        return {
            "success": True,
            "data": {
                "os": platform.system(),
                "os_release": platform.release(),
                "os_version": platform.version(),
                "hostname": platform.node(),
                "architecture": platform.machine(),
                "processor": platform.processor(),
                "python_version": platform.python_version(),
                "boot_time": datetime.datetime.fromtimestamp(boot_ts).isoformat(),
                "uptime_seconds": uptime_seconds,
                "uptime_human": str(uptime_delta),
                "cpu_count_logical": psutil.cpu_count(logical=True),
                "cpu_count_physical": psutil.cpu_count(logical=False),
            },
        }

    # ------------------------------------------------------------------
    # 网络接口
    # ------------------------------------------------------------------

    async def _network_interfaces(self, params: dict) -> dict[str, Any]:
        """获取网络接口信息。

        Params:
            include_stats: 是否包含流量统计（默认 True）
        """
        include_stats = params.get("include_stats", True)
        addrs = psutil.net_if_addrs()
        interfaces: list[dict[str, Any]] = []

        stats = psutil.net_if_stats() if include_stats else {}

        for ifname, addr_list in addrs.items():
            iface: dict[str, Any] = {"name": ifname, "addresses": []}

            for addr in addr_list:
                iface["addresses"].append({
                    "family": str(addr.family),
                    "address": addr.address,
                    "netmask": addr.netmask,
                    "broadcast": addr.broadcast,
                })

            if include_stats and ifname in stats:
                st = stats[ifname]
                iface["stats"] = {
                    "is_up": st.isup,
                    "speed_mbps": st.speed,
                    "mtu": st.mtu,
                }

            interfaces.append(iface)

        result: dict[str, Any] = {
            "success": True,
            "data": {"interfaces": interfaces, "count": len(interfaces)},
        }

        if include_stats:
            io = psutil.net_io_counters(pernic=True)
            io_data: dict[str, dict[str, int]] = {}
            for ifname, counters in io.items():
                io_data[ifname] = {
                    "bytes_sent": counters.bytes_sent,
                    "bytes_recv": counters.bytes_recv,
                    "packets_sent": counters.packets_sent,
                    "packets_recv": counters.packets_recv,
                }
            result["data"]["io_counters"] = io_data

        return result

    # ------------------------------------------------------------------
    # 告警检查
    # ------------------------------------------------------------------

    async def _check_alerts(self, params: dict) -> dict[str, Any]:
        """检查是否有阈值告警。

        使用初始化时传入的 alert_rules 或默认规则，
        逐项检查当前指标是否超过阈值。

        Params:
            rules: 临时覆盖告警规则（可选）
        """
        rules = params.get("rules", self._alert_rules)

        # 获取当前资源数据
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk_usages: dict[str, float] = {}
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disk_usages[part.mountpoint] = usage.percent
            except (PermissionError, OSError):
                continue

        # 当前指标值
        current_values: dict[str, float] = {
            "cpu_percent": cpu_percent,
            "memory_percent": mem.percent,
        }
        # 磁盘取最高使用率
        if disk_usages:
            current_values["disk_percent"] = max(disk_usages.values())
        else:
            current_values["disk_percent"] = 0.0

        alerts: list[dict[str, Any]] = []

        for rule in rules:
            metric = rule.get("metric", "")
            threshold = rule.get("threshold", 100.0)
            op = rule.get("op", ">")

            current = current_values.get(metric)
            if current is None:
                continue

            triggered = self._compare(current, threshold, op)
            if triggered:
                alerts.append({
                    "metric": metric,
                    "current": round(current, 2),
                    "threshold": threshold,
                    "op": op,
                    "message": f"{metric} 当前值 {current:.1f}% {op} 阈值 {threshold}%",
                })
                logger.warning(
                    f"告警触发: {metric} = {current:.1f}% {op} {threshold}%"
                )

        return {
            "success": True,
            "data": {
                "alerts": alerts,
                "alert_count": len(alerts),
                "current_values": {k: round(v, 2) for k, v in current_values.items()},
            },
        }

    # ------------------------------------------------------------------
    # 系统快照
    # ------------------------------------------------------------------

    async def _snapshot(self, params: dict) -> dict[str, Any]:
        """生成完整的系统状态快照。

        一次性采集 CPU、内存、磁盘、Top 进程、系统信息、网络接口，
        生成结构化的快照报告。

        Params:
            top_count: Top 进程数量（默认 5）
        """
        top_count = params.get("top_count", 5)

        # 并行采集
        resource_result = await self._resource_usage({"per_disk": True})
        sysinfo_result = await self._system_info({})
        top_cpu_result = await self._top_processes({"sort_by": "cpu", "count": top_count})
        top_mem_result = await self._top_processes({"sort_by": "memory", "count": top_count})
        alert_result = await self._check_alerts({})

        now = datetime.datetime.now().isoformat()

        snapshot = {
            "timestamp": now,
            "system": sysinfo_result.get("data", {}),
            "resources": resource_result.get("data", {}),
            "top_cpu_processes": top_cpu_result.get("data", {}).get("processes", []),
            "top_memory_processes": top_mem_result.get("data", {}).get("processes", []),
            "alerts": alert_result.get("data", {}).get("alerts", []),
            "alert_count": alert_result.get("data", {}).get("alert_count", 0),
        }

        logger.info(
            f"系统快照已生成: CPU {snapshot['resources'].get('cpu', {}).get('percent')}% | "
            f"内存 {snapshot['resources'].get('memory', {}).get('percent')}% | "
            f"告警 {snapshot['alert_count']} 个"
        )

        return {"success": True, "data": snapshot}

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _format_disk_usage(
        mountpoint: str,
        usage: psutil._common.sdiskusage,
        partition: psutil._common.sdiskpart | None = None,
    ) -> dict[str, Any]:
        """格式化单个磁盘的使用信息。"""
        result: dict[str, Any] = {
            "mountpoint": mountpoint,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": usage.percent,
            "total_human": SystemMonitor._bytes_to_gb(usage.total),
            "used_human": SystemMonitor._bytes_to_gb(usage.used),
            "free_human": SystemMonitor._bytes_to_gb(usage.free),
        }
        if partition:
            result["device"] = partition.device
            result["fstype"] = partition.fstype
            result["opts"] = partition.opts
        return result

    @staticmethod
    def _basic_proc_info(proc: psutil.Process) -> dict[str, Any]:
        """获取进程的基本信息。"""
        try:
            mem_info = proc.memory_info()
            return {
                "pid": proc.pid,
                "name": proc.name(),
                "status": proc.status(),
                "cpu_percent": proc.cpu_percent(interval=0),
                "memory_rss_human": SystemMonitor._bytes_to_mb(mem_info.rss),
                "memory_percent": round(proc.memory_percent(), 2),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {"pid": proc.pid, "name": "<exited>", "status": "gone"}

    @staticmethod
    def _bytes_to_gb(n: float) -> str:
        """字节数转人类可读的 GB 字符串。"""
        return f"{n / (1024 ** 3):.1f} GB"

    @staticmethod
    def _bytes_to_mb(n: float) -> str:
        """字节数转人类可读的 MB 字符串。"""
        return f"{n / (1024 ** 2):.1f} MB"

    @staticmethod
    def _compare(current: float, threshold: float, op: str) -> bool:
        """比较当前值与阈值。"""
        if op == ">":
            return current > threshold
        elif op == ">=":
            return current >= threshold
        elif op == "<":
            return current < threshold
        elif op == "<=":
            return current <= threshold
        elif op == "==":
            return current == threshold
        return False
