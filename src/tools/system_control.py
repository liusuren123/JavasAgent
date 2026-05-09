"""系统控制工具。

提供文件操作、进程管理等基础系统能力。
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

from loguru import logger

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
        """执行终端命令。"""
        command = params.get("command", "")
        timeout = params.get("timeout", 60)
        cwd = params.get("cwd", str(self._workspace))

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        except asyncio.TimeoutError:
            return {"error": f"命令超时 ({timeout}s): {command[:100]}"}
        except Exception as e:
            return {"error": str(e)}

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
