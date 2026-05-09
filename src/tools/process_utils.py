"""进程管理辅助函数。

提供进程信息格式化、进程树构建等辅助能力。
"""

from __future__ import annotations

import datetime
from typing import Any

import psutil


def format_process_info(proc: psutil.Process, *, with_cmdline: bool = False) -> dict[str, Any]:
    """从 psutil.Process 提取并格式化进程信息。

    Args:
        proc: psutil 进程对象
        with_cmdline: 是否包含命令行参数

    Returns:
        进程信息字典
    """
    try:
        info: dict[str, Any] = {
            "pid": proc.pid,
            "name": _safe_call(proc.name, "unknown"),
            "status": _safe_call(proc.status, "unknown"),
            "cpu_percent": _safe_call(proc.cpu_percent, 0.0),
            "memory_info": _format_memory(proc),
            "create_time": _format_time(proc),
        }
        if with_cmdline:
            cmdline = _safe_call(proc.cmdline, [])
            info["cmdline"] = cmdline if isinstance(cmdline, list) else []
        return info
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return {"pid": proc.pid, "name": "unknown", "status": "terminated"}


def _safe_call(fn, default):
    """安全调用 psutil 方法，异常时返回默认值。"""
    try:
        return fn()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return default


def _format_memory(proc: psutil.Process) -> dict[str, Any]:
    """格式化内存信息。"""
    try:
        mem = proc.memory_info()
        return {
            "rss_mb": round(mem.rss / (1024 * 1024), 2),
            "vms_mb": round(mem.vms / (1024 * 1024), 2),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"rss_mb": 0, "vms_mb": 0}


def _format_time(proc: psutil.Process) -> str:
    """格式化进程创建时间。"""
    try:
        ts = proc.create_time()
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return "unknown"


def build_process_tree(procs: list[psutil.Process], max_depth: int = 3) -> list[dict[str, Any]]:
    """构建进程树（父子关系）。

    Args:
        procs: 进程列表
        max_depth: 最大递归深度

    Returns:
        树形结构的进程列表
    """
    proc_map: dict[int, dict[str, Any]] = {}
    for proc in procs:
        try:
            info = format_process_info(proc)
            info["children"] = []
            proc_map[proc.pid] = info
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    roots: list[dict[str, Any]] = []
    for proc in procs:
        pid = proc.pid
        if pid not in proc_map:
            continue
        try:
            ppid = proc.ppid()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            roots.append(proc_map[pid])
            continue

        if ppid == 0 or ppid not in proc_map:
            roots.append(proc_map[pid])
        else:
            proc_map[ppid]["children"].append(proc_map[pid])

    return roots
