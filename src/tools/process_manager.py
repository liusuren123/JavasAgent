"""进程管理工具。

提供进程列表、查找、终止、资源排行、进程树等能力。
基于 psutil 实现，是 Phase 2 桌面操控的核心工具之一。
"""

from __future__ import annotations

from typing import Any

import psutil
from loguru import logger

from src.tools.process_utils import build_process_tree, format_process_info


class ProcessManager:
    """进程管理工具集。

    支持：
    - list: 列出运行中的进程（支持按名称过滤、分页）
    - find: 按 PID 或名称查找进程
    - kill: 终止指定进程（支持强制终止，需二次确认）
    - get_top: 获取 CPU/内存占用最高的进程
    - get_tree: 获取进程树（父子关系）

    Usage::

        pm = ProcessManager()
        result = await pm.execute("list", {"filter": "python"})
        result = await pm.execute("kill", {"pid": 1234, "confirm": True})
    """

    def __init__(self) -> None:
        self._actions = {
            "list": self._list,
            "find": self._find,
            "kill": self._kill,
            "get_top": self._get_top,
            "get_tree": self._get_tree,
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行进程管理操作。

        Args:
            action: 操作类型 (list / find / kill / get_top / get_tree)
            params: 操作参数

        Returns:
            包含 success 和 data/error 的结果字典
        """
        handler = self._actions.get(action)
        if handler is None:
            logger.error(f"未知操作: {action}")
            return {"success": False, "error": f"未知操作: {action}，支持: {', '.join(sorted(self._actions.keys()))}"}

        try:
            return await handler(params)
        except Exception as e:
            logger.error(f"进程管理操作失败 [{action}]: {e}")
            return {"success": False, "error": f"操作失败: {e}"}

    # ------------------------------------------------------------------
    # 列出进程
    # ------------------------------------------------------------------

    async def _list(self, params: dict) -> dict[str, Any]:
        """列出运行中的进程。

        Params:
            filter: 按名称过滤（子串匹配，可选）
            page: 页码（从 1 开始，默认 1）
            page_size: 每页数量（默认 20，最大 100）
            with_cmdline: 是否包含命令行参数（默认 False）
        """
        name_filter = (params.get("filter") or "").lower()
        page = max(1, params.get("page", 1))
        page_size = min(100, max(1, params.get("page_size", 20)))
        with_cmdline = params.get("with_cmdline", False)

        all_procs = []
        for proc in psutil.process_iter():
            try:
                info = format_process_info(proc, with_cmdline=with_cmdline)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            # 名称过滤
            if name_filter and name_filter not in info.get("name", "").lower():
                continue

            # 跳过已终止的进程
            if info.get("status") == "terminated":
                continue

            all_procs.append(info)

        total = len(all_procs)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = all_procs[start:end]

        logger.info(f"列出进程: 总计 {total} 个, 返回第 {page} 页 ({len(page_items)} 个)")
        return {
            "success": True,
            "data": {
                "processes": page_items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "has_more": end < total,
            },
        }

    # ------------------------------------------------------------------
    # 查找进程
    # ------------------------------------------------------------------

    async def _find(self, params: dict) -> dict[str, Any]:
        """按 PID 或名称查找进程。

        Params:
            pid: 进程 ID（优先）
            name: 进程名称（精确或子串匹配）
            exact: 是否精确匹配名称（默认 False）
        """
        pid = params.get("pid")
        name = params.get("name", "")
        exact = params.get("exact", False)

        # 按 PID 查找
        if pid is not None:
            try:
                pid = int(pid)
                proc = psutil.Process(pid)
                info = format_process_info(proc, with_cmdline=True)
                logger.info(f"查找进程 PID={pid}: {info.get('name')}")
                return {"success": True, "data": info}
            except psutil.NoSuchProcess:
                return {"success": False, "error": f"进程不存在: PID {pid}"}
            except psutil.AccessDenied:
                return {"success": False, "error": f"无权限访问进程: PID {pid}"}

        # 按名称查找
        if not name:
            return {"success": False, "error": "缺少参数: pid 或 name"}

        results = []
        name_lower = name.lower()
        for proc in psutil.process_iter():
            try:
                proc_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            if exact:
                if proc_name == name:
                    results.append(format_process_info(proc, with_cmdline=True))
            else:
                if name_lower in proc_name.lower():
                    results.append(format_process_info(proc, with_cmdline=True))

        if not results:
            return {"success": False, "error": f"未找到匹配的进程: {name}"}

        logger.info(f"查找进程 '{name}': 找到 {len(results)} 个")
        return {"success": True, "data": {"processes": results, "count": len(results)}}

    # ------------------------------------------------------------------
    # 终止进程
    # ------------------------------------------------------------------

    async def _kill(self, params: dict) -> dict[str, Any]:
        """终止指定进程。

        需要二次确认：params 中必须有 confirm=True 才会真正执行。

        Params:
            pid: 进程 ID（必填）
            force: 是否强制终止（SIGKILL，默认 False，先用 SIGTERM）
            confirm: 二次确认（必须为 True）
            kill_children: 是否同时终止子进程（默认 True）
        """
        pid = params.get("pid")
        if pid is None:
            return {"success": False, "error": "缺少参数: pid"}

        pid = int(pid)

        # 二次确认检查
        if not params.get("confirm"):
            # 获取进程信息用于展示
            try:
                proc = psutil.Process(pid)
                proc_info = format_process_info(proc)
                return {
                    "success": False,
                    "error": "需要二次确认才能终止进程",
                    "require_confirm": True,
                    "process": proc_info,
                    "hint": "请设置 confirm: true 以确认终止",
                }
            except psutil.NoSuchProcess:
                return {"success": False, "error": f"进程不存在: PID {pid}"}

        force = params.get("force", False)
        kill_children = params.get("kill_children", True)

        try:
            proc = psutil.Process(pid)
            proc_name = proc.name()
            children_killed = 0

            # 先终止子进程
            if kill_children:
                try:
                    children = proc.children(recursive=True)
                    for child in children:
                        try:
                            if force:
                                child.kill()
                            else:
                                child.terminate()
                            children_killed += 1
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # 终止主进程
            if force:
                proc.kill()
                method = "SIGKILL"
            else:
                proc.terminate()
                method = "SIGTERM"

            logger.info(f"终止进程 PID={pid} ({proc_name}), 方法={method}, 子进程={children_killed}")
            return {
                "success": True,
                "data": {
                    "pid": pid,
                    "name": proc_name,
                    "method": method,
                    "children_killed": children_killed,
                },
            }
        except psutil.NoSuchProcess:
            return {"success": False, "error": f"进程不存在: PID {pid}"}
        except psutil.AccessDenied:
            return {"success": False, "error": f"无权限终止进程: PID {pid}，请尝试 force=True"}
        except Exception as e:
            logger.error(f"终止进程失败 PID={pid}: {e}")
            return {"success": False, "error": f"终止进程失败: {e}"}

    # ------------------------------------------------------------------
    # 资源排行
    # ------------------------------------------------------------------

    async def _get_top(self, params: dict) -> dict[str, Any]:
        """获取 CPU/内存占用最高的进程。

        Params:
            sort_by: 排序依据 (cpu / memory，默认 cpu)
            count: 返回数量（默认 10，最大 50)
        """
        sort_by = params.get("sort_by", "cpu")
        count = min(50, max(1, params.get("count", 10)))

        all_procs = []
        for proc in psutil.process_iter():
            try:
                info = format_process_info(proc, with_cmdline=False)
                # 只保留有实际数值的进程
                if info.get("status") == "terminated":
                    continue
                all_procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # 排序
        if sort_by == "memory":
            all_procs.sort(key=lambda p: p.get("memory_info", {}).get("rss_mb", 0), reverse=True)
        else:
            all_procs.sort(key=lambda p: p.get("cpu_percent", 0), reverse=True)

        top = all_procs[:count]
        logger.info(f"获取 Top {count} 进程 (按 {sort_by} 排序)")
        return {
            "success": True,
            "data": {
                "processes": top,
                "sort_by": sort_by,
                "count": len(top),
            },
        }

    # ------------------------------------------------------------------
    # 进程树
    # ------------------------------------------------------------------

    async def _get_tree(self, params: dict) -> dict[str, Any]:
        """获取进程树（父子关系）。

        Params:
            pid: 根进程 ID（可选，不传则返回完整进程树）
            max_depth: 最大递归深度（默认 3）
        """
        pid = params.get("pid")
        max_depth = params.get("max_depth", 3)

        if pid is not None:
            pid = int(pid)
            try:
                root_proc = psutil.Process(pid)
                # 获取该进程及其所有子孙进程
                descendants = root_proc.children(recursive=True)
                procs = [root_proc] + descendants
            except psutil.NoSuchProcess:
                return {"success": False, "error": f"进程不存在: PID {pid}"}
            except psutil.AccessDenied:
                return {"success": False, "error": f"无权限访问进程: PID {pid}"}
        else:
            procs = list(psutil.process_iter())

        tree = build_process_tree(procs, max_depth=max_depth)

        logger.info(f"获取进程树: {len(procs)} 个进程")
        return {
            "success": True,
            "data": {
                "tree": tree,
                "total_processes": len(procs),
                "root_pid": pid,
            },
        }
