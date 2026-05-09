"""系统控制工具。

提供文件操作、进程管理等基础系统能力。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.command import run_command
from src.utils.path_safety import PathSafetyError, safe_resolve_path


class SystemControl:
    """系统控制工具集。"""

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = Path(workspace) if workspace else Path.cwd()

    async def execute(self, action: str, params: dict[str, Any]) -> Any:
        """执行系统控制操作。

        Args:
            action: 操作类型
            params: 操作参数
        """
        handlers = {
            "list_files": self._list_files,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "delete_file": self._delete_file,
            "create_dir": self._create_dir,
            "run_command": self._run_command,
            "get_info": self._get_system_info,
            "copy": self._copy,
            "move": self._move,
            "rename": self._rename,
            "search_files": self._search_files,
            "disk_usage": self._disk_usage,
        }

        handler = handlers.get(action)
        if handler is None:
            logger.error(f"未知操作: {action}")
            return {"error": f"未知操作: {action}"}

        return await handler(params)

    def _safe_path(self, user_path: str, *, allow_create_parents: bool = False) -> Path:
        """安全解析用户路径，防止路径遍历。

        Args:
            user_path: 用户提供的相对路径
            allow_create_parents: 是否允许创建父目录

        Returns:
            解析后的安全路径

        Raises:
            PathSafetyError: 路径不安全时抛出
        """
        return safe_resolve_path(
            self._workspace,
            user_path,
            allow_create_parents=allow_create_parents,
        )

    async def _list_files(self, params: dict) -> dict:
        """列出目录文件。"""
        raw_path = params.get("path", "") or ""
        try:
            path = self._safe_path(raw_path) if raw_path else self._workspace
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"路径不存在: {path}"}

        items = []
        for item in sorted(path.iterdir()):
            items.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else 0,
            })
        return {"path": str(path), "items": items}

    async def _read_file(self, params: dict) -> dict:
        """读取文件内容。"""
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        encoding = params.get("encoding", "utf-8")
        content = path.read_text(encoding=encoding)
        return {"path": str(path), "content": content, "size": len(content)}

    async def _write_file(self, params: dict) -> dict:
        """写入文件。"""
        try:
            path = self._safe_path(params["path"], allow_create_parents=True)
        except PathSafetyError as e:
            return {"error": str(e)}

        content = params.get("content", "")
        encoding = params.get("encoding", "utf-8")
        path.write_text(content, encoding=encoding)
        logger.info(f"文件已写入: {path} ({len(content)} 字符)")
        return {"path": str(path), "size": len(content)}

    async def _delete_file(self, params: dict) -> dict:
        """删除文件或目录。"""
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"路径不存在: {path}"}

        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

        logger.info(f"已删除: {path}")
        return {"deleted": str(path)}

    async def _create_dir(self, params: dict) -> dict:
        """创建目录。"""
        try:
            path = self._safe_path(params["path"], allow_create_parents=True)
        except PathSafetyError as e:
            return {"error": str(e)}

        path.mkdir(parents=True, exist_ok=True)
        return {"created": str(path)}

    async def _run_command(self, params: dict) -> dict:
        """执行终端命令。

        传入的 command 为完整的 shell 命令字符串（如 ``"git log -5 --oneline"``）。
        通过 ``run_command`` 的 ``raw_command`` 模式执行，避免参数被错误引号包裹。
        """
        command = params.get("command", "")
        if not command:
            return {"error": "缺少参数: command"}
        timeout = params.get("timeout", 60)
        cwd = params.get("cwd", str(self._workspace))

        return await run_command(
            [command],
            cwd=cwd,
            timeout=timeout,
            raw_command=True,
        )

    async def _get_system_info(self, params: dict) -> dict:
        """获取系统信息。"""
        import platform

        return {
            "os": platform.system(),
            "os_version": platform.version(),
            "python_version": platform.python_version(),
            "workspace": str(self._workspace),
            "cwd": os.getcwd(),
        }

    async def _copy(self, params: dict) -> dict:
        """复制文件或目录。

        Args:
            params: 包含 src（源路径）、dst（目标路径）、
                    overwrite（是否覆盖，默认 false）的字典。

        Returns:
            包含复制结果信息的字典。
        """
        try:
            src = self._safe_path(params["src"])
            dst = self._safe_path(params["dst"], allow_create_parents=True)
        except PathSafetyError as e:
            return {"error": str(e)}

        overwrite = params.get("overwrite", False)

        if not src.exists():
            return {"error": f"源路径不存在: {src}"}

        if dst.exists() and not overwrite:
            return {"error": f"目标路径已存在: {dst}"}

        try:
            if src.is_dir():
                if dst.exists() and overwrite:
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            logger.info(f"已复制: {src} -> {dst}")
            return {"copied_from": str(src), "copied_to": str(dst)}
        except OSError as e:
            logger.error(f"复制失败: {e}")
            return {"error": f"复制失败: {e}"}

    async def _move(self, params: dict) -> dict:
        """移动或重命名文件或目录。

        Args:
            params: 包含 src（源路径）、dst（目标路径）、
                    overwrite（是否覆盖，默认 false）的字典。

        Returns:
            包含移动结果信息的字典。
        """
        try:
            src = self._safe_path(params["src"])
            dst = self._safe_path(params["dst"], allow_create_parents=True)
        except PathSafetyError as e:
            return {"error": str(e)}

        overwrite = params.get("overwrite", False)

        if not src.exists():
            return {"error": f"源路径不存在: {src}"}

        if dst.exists() and not overwrite:
            return {"error": f"目标路径已存在: {dst}"}

        try:
            if dst.exists() and overwrite:
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            logger.info(f"已移动: {src} -> {dst}")
            return {"moved_from": str(src), "moved_to": str(dst)}
        except OSError as e:
            logger.error(f"移动失败: {e}")
            return {"error": f"移动失败: {e}"}

    async def _rename(self, params: dict) -> dict:
        """重命名文件或目录（只改名称，不改变所在目录）。

        Args:
            params: 包含 path（原路径）、new_name（新名称）的字典。

        Returns:
            包含重命名结果信息的字典。
        """
        try:
            path = self._safe_path(params["path"])
        except PathSafetyError as e:
            return {"error": str(e)}

        new_name = params.get("new_name", "")
        if not new_name:
            return {"error": "缺少参数: new_name"}

        if not path.exists():
            return {"error": f"路径不存在: {path}"}

        # 防止新名称包含路径分隔符
        if os.sep in new_name or (os.altsep and os.altsep in new_name):
            return {"error": "new_name 不能包含路径分隔符"}

        new_path = path.parent / new_name
        # 验证新路径仍然安全
        try:
            new_path = self._safe_path(str(new_path.relative_to(self._workspace)))
        except (ValueError, PathSafetyError) as e:
            return {"error": f"新名称导致路径不安全: {e}"}

        if new_path.exists():
            return {"error": f"目标路径已存在: {new_path}"}

        try:
            path.rename(new_path)
            logger.info(f"已重命名: {path} -> {new_path}")
            return {"renamed_from": str(path), "renamed_to": str(new_path)}
        except OSError as e:
            logger.error(f"重命名失败: {e}")
            return {"error": f"重命名失败: {e}"}

    async def _search_files(self, params: dict) -> dict:
        """按名称或扩展名搜索文件。

        Args:
            params: 包含 path（搜索根目录）、pattern（glob 模式，如 *.py）、
                    recursive（是否递归，默认 true）、
                    max_results（最大结果数，默认 100）的字典。

        Returns:
            包含匹配文件列表的字典。
        """
        raw_path = params.get("path", "") or ""
        try:
            search_root = self._safe_path(raw_path) if raw_path else self._workspace
        except PathSafetyError as e:
            return {"error": str(e)}

        if not search_root.exists():
            return {"error": f"搜索路径不存在: {search_root}"}

        pattern = params.get("pattern", "*")
        recursive = params.get("recursive", True)
        max_results = params.get("max_results", 100)

        try:
            if recursive:
                matches = sorted(search_root.rglob(pattern))
            else:
                matches = sorted(search_root.glob(pattern))
        except OSError as e:
            logger.error(f"搜索失败: {e}")
            return {"error": f"搜索失败: {e}"}

        results = []
        for match in matches[:max_results]:
            try:
                rel = match.relative_to(search_root)
                results.append({
                    "path": str(rel),
                    "name": match.name,
                    "type": "dir" if match.is_dir() else "file",
                    "size": match.stat().st_size if match.is_file() else 0,
                })
            except OSError:
                continue

        logger.info(f"搜索完成: 在 {search_root} 中找到 {len(results)} 个匹配项")
        return {
            "root": str(search_root),
            "pattern": pattern,
            "count": len(results),
            "files": results,
        }

    async def _disk_usage(self, params: dict) -> dict:
        """获取磁盘使用信息。

        Args:
            params: 包含 path（路径，默认为 workspace）的字典。

        Returns:
            包含磁盘总容量、已用空间和可用空间的字典。
        """
        raw_path = params.get("path", "") or ""
        try:
            path = self._safe_path(raw_path) if raw_path else self._workspace
        except PathSafetyError as e:
            return {"error": str(e)}

        try:
            total, used, free = shutil.disk_usage(path)
            logger.info(f"磁盘信息: {path} — 总计 {total}, 已用 {used}, 可用 {free}")
            return {
                "path": str(path),
                "total": total,
                "used": used,
                "free": free,
                "total_human": f"{total / (1024**3):.1f} GB",
                "used_human": f"{used / (1024**3):.1f} GB",
                "free_human": f"{free / (1024**3):.1f} GB",
            }
        except OSError as e:
            logger.error(f"获取磁盘信息失败: {e}")
            return {"error": f"获取磁盘信息失败: {e}"}
