"""命令执行工具。

提供统一的异步命令执行能力，供各工具集共享使用。
"""

from __future__ import annotations

import asyncio
import locale
import sys
from typing import Any

from loguru import logger


def _quote_arg(arg: str) -> str:
    """为命令行参数添加引号。

    在 Windows 上使用双引号，在 POSIX 上使用 shlex.quote。

    Args:
        arg: 要引号的参数

    Returns:
        引号后的参数
    """
    if sys.platform == "win32":
        # Windows: 只有包含空格或特殊字符时才需要双引号
        if " " in arg or '"' in arg or "'" in arg or ";" in arg:
            # 转义内部双引号
            escaped = arg.replace('"', '\\"')
            return f'"{escaped}"'
        return arg
    else:
        import shlex
        return shlex.quote(arg)


def _decode_bytes(raw: bytes, fallback_encoding: str) -> str:
    """解码子进程输出字节流。

    优先使用 UTF-8 解码，如果失败则回退到指定编码（errors="replace"）。

    Args:
        raw: 子进程输出的原始字节
        fallback_encoding: 回退编码名称

    Returns:
        解码后的字符串
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(fallback_encoding, errors="replace")


async def run_command(
    cmd_parts: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
    raw_command: bool = False,
) -> dict[str, Any]:
    """执行命令行并返回结果。

    Args:
        cmd_parts: 命令各部分组成的列表
        cwd: 工作目录，默认当前目录
        timeout: 超时秒数
        env: 额外环境变量
        raw_command: 为 True 时直接取 cmd_parts[0] 作为完整 shell 命令，
            不对参数做引号拼接。适用于用户输入的完整命令字符串场景。

    Returns:
        包含 returncode, stdout, stderr 的字典，
        超时或异常时包含 error 字段
    """
    if raw_command:
        command = cmd_parts[0] if cmd_parts else ""
    else:
        command = " ".join(_quote_arg(str(p)) for p in cmd_parts)
    logger.debug(f"执行命令: {command}")

    try:
        import os

        # 构建子进程环境变量：
        # 1. 继承当前进程环境
        # 2. 注入 PYTHONIOENCODING=utf-8 确保 Python 子进程使用 UTF-8 输出
        # 3. 注入用户自定义环境变量（最高优先级）
        proc_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        if env:
            proc_env.update(env)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=proc_env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        # 解码策略：优先 UTF-8（PYTHONIOENCODING 已保证 Python 子进程输出 UTF-8），
        # 对非 Python 进程的输出回退到系统控制台编码（Windows 为 GBK/cp936）
        fallback_encoding = (
            locale.getpreferredencoding(False) or "utf-8"
        )
        stdout_text = _decode_bytes(stdout, fallback_encoding)
        stderr_text = _decode_bytes(stderr, fallback_encoding)

        return {
            "returncode": proc.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
        }
    except asyncio.TimeoutError:
        logger.error(f"命令超时 ({timeout}s): {command[:100]}")
        return {"error": f"命令超时 ({timeout}s): {command[:100]}"}
    except Exception as e:
        logger.error(f"命令执行失败: {e}")
        return {"error": str(e)}
