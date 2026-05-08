"""代码开发工具集。

提供代码生成、编辑、测试、Git 操作、代码检查、依赖管理等能力。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from loguru import logger


class CodeDev:
    """代码开发工具集。"""

    def __init__(self, workspace: str | None = None, llm_client: Any = None) -> None:
        """初始化代码开发工具。

        Args:
            workspace: 工作目录路径，默认为当前工作目录
            llm_client: LLM 客户端实例（需提供 chat_with_system 方法）
        """
        self._workspace = Path(workspace) if workspace else Path.cwd()
        self._llm_client = llm_client

    async def execute(self, action: str, params: dict[str, Any]) -> Any:
        """执行代码开发操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            操作结果字典
        """
        handlers = {
            "generate_code": self._generate_code,
            "read_code": self._read_code,
            "edit_code": self._edit_code,
            "run_test": self._run_test,
            "git_operation": self._git_operation,
            "lint": self._lint,
            "install_deps": self._install_deps,
        }

        handler = handlers.get(action)
        if handler is None:
            logger.error(f"未知操作: {action}")
            return {"error": f"未知操作: {action}"}

        return await handler(params)

    # ------------------------------------------------------------------
    # generate_code
    # ------------------------------------------------------------------

    async def _generate_code(self, params: dict) -> dict:
        """根据 prompt 生成代码（调用 LLM）。

        Params:
            prompt: 代码生成提示
            language: 目标语言（默认 python）
            system_prompt: 可选系统提示覆盖
        """
        prompt = params.get("prompt", "")
        if not prompt:
            return {"error": "缺少参数: prompt"}

        language = params.get("language", "python")
        system_prompt = params.get(
            "system_prompt",
            f"You are an expert {language} developer. Generate clean, well-documented code.",
        )

        if self._llm_client is None:
            return {"error": "LLM 客户端未配置"}

        try:
            code = await self._llm_client.chat_with_system(
                system_prompt=system_prompt,
                user_message=prompt,
            )
            logger.info(f"代码生成完成: {len(code)} 字符, 语言={language}")
            return {"code": code, "language": language}
        except Exception as e:
            logger.error(f"代码生成失败: {e}")
            return {"error": f"代码生成失败: {e}"}

    # ------------------------------------------------------------------
    # read_code
    # ------------------------------------------------------------------

    async def _read_code(self, params: dict) -> dict:
        """读取代码文件内容（带语法高亮标记）。

        Params:
            path: 文件路径（相对于 workspace）
            encoding: 文件编码（默认 utf-8）
            start_line: 起始行号（可选，1-based）
            end_line: 结束行号（可选，包含）
        """
        path = self._workspace / params["path"]
        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        try:
            content = path.read_text(encoding=params.get("encoding", "utf-8"))
        except Exception as e:
            return {"error": f"读取文件失败: {e}"}

        lines = content.splitlines(keepends=True)

        start_line = params.get("start_line")
        end_line = params.get("end_line")
        if start_line is not None or end_line is not None:
            s = (start_line or 1) - 1
            e = end_line or len(lines)
            lines = lines[s:e]

        # 带行号格式化
        numbered_lines = []
        first_line = start_line or 1
        for i, line in enumerate(lines):
            line_num = first_line + i
            # 去掉末尾换行以便统一拼接
            numbered_lines.append(f"{line_num:>4} | {line.rstrip()}")

        suffix = path.suffix.lstrip(".")
        logger.info(f"读取代码文件: {path} ({len(lines)} 行)")
        return {
            "path": str(path),
            "language": suffix,
            "content": "\n".join(numbered_lines),
            "total_lines": len(lines),
        }

    # ------------------------------------------------------------------
    # edit_code
    # ------------------------------------------------------------------

    async def _edit_code(self, params: dict) -> dict:
        """编辑代码文件。

        支持两种模式:
          1) 指定行范围替换（start_line + end_line + replacement）
          2) 正则匹配替换（pattern + replacement）

        Params:
            path: 文件路径
            start_line: 起始行号（模式 1）
            end_line: 结束行号（模式 1）
            pattern: 正则表达式（模式 2）
            replacement: 替换文本
            encoding: 文件编码
        """
        path = self._workspace / params["path"]
        if not path.exists():
            return {"error": f"文件不存在: {path}"}

        encoding = params.get("encoding", "utf-8")
        replacement = params.get("replacement", "")

        try:
            content = path.read_text(encoding=encoding)
            lines = content.splitlines(keepends=True)
        except Exception as e:
            return {"error": f"读取文件失败: {e}"}

        original_line_count = len(lines)

        # 模式 1：行范围替换
        start_line = params.get("start_line")
        end_line = params.get("end_line")

        if start_line is not None and end_line is not None:
            if start_line < 1 or end_line > original_line_count or start_line > end_line:
                return {"error": f"行号范围无效: {start_line}-{end_line}，文件共 {original_line_count} 行"}

            new_lines = replacement.splitlines(keepends=True)
            # 确保替换文本最后一行有换行
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"

            lines[start_line - 1 : end_line] = new_lines

        # 模式 2：正则替换
        elif "pattern" in params:
            pattern = params["pattern"]
            try:
                new_content, count = re.subn(pattern, replacement, content)
            except re.error as e:
                return {"error": f"正则表达式错误: {e}"}

            lines = new_content.splitlines(keepends=True)
            logger.info(f"正则替换完成: 匹配 {count} 处")
        else:
            return {"error": "需要提供 start_line/end_line 或 pattern 参数"}

        new_content = "".join(lines)
        try:
            path.write_text(new_content, encoding=encoding)
        except Exception as e:
            return {"error": f"写入文件失败: {e}"}

        logger.info(f"编辑代码文件: {path} ({original_line_count} -> {len(lines)} 行)")
        return {
            "path": str(path),
            "original_lines": original_line_count,
            "new_lines": len(lines),
        }

    # ------------------------------------------------------------------
    # run_test
    # ------------------------------------------------------------------

    async def _run_test(self, params: dict) -> dict:
        """运行测试命令（pytest）。

        Params:
            target: 测试目标（文件或目录，默认 tests/）
            args: 额外 pytest 参数列表
            timeout: 超时秒数（默认 120）
        """
        target = params.get("target", "tests/")
        args = params.get("args", [])
        timeout = params.get("timeout", 120)

        cmd_parts = ["python", "-m", "pytest", target]
        cmd_parts.extend(args)

        return await self._run_command(cmd_parts, timeout=timeout)

    # ------------------------------------------------------------------
    # git_operation
    # ------------------------------------------------------------------

    async def _git_operation(self, params: dict) -> dict:
        """Git 操作。

        Params:
            command: 子命令 (status, add, commit, push, pull, diff, log)
            args: 额外参数列表
            timeout: 超时秒数（默认 60）
        """
        command = params.get("command", "")
        if not command:
            return {"error": "缺少参数: command"}

        valid_commands = {"status", "add", "commit", "push", "pull", "diff", "log"}
        if command not in valid_commands:
            return {"error": f"不支持的 git 命令: {command}，支持: {', '.join(sorted(valid_commands))}"}

        args = params.get("args", [])
        timeout = params.get("timeout", 60)

        cmd_parts = ["git", command] + args
        return await self._run_command(cmd_parts, timeout=timeout)

    # ------------------------------------------------------------------
    # lint
    # ------------------------------------------------------------------

    async def _lint(self, params: dict) -> dict:
        """代码检查（ruff）。

        Params:
            target: 检查目标（默认 src/）
            fix: 是否自动修复（默认 False）
            args: 额外 ruff 参数列表
            timeout: 超时秒数（默认 60）
        """
        target = params.get("target", "src/")
        fix = params.get("fix", False)
        args = params.get("args", [])
        timeout = params.get("timeout", 60)

        cmd_parts = ["ruff", "check", target]
        if fix:
            cmd_parts.append("--fix")
        cmd_parts.extend(args)

        return await self._run_command(cmd_parts, timeout=timeout)

    # ------------------------------------------------------------------
    # install_deps
    # ------------------------------------------------------------------

    async def _install_deps(self, params: dict) -> dict:
        """安装依赖。

        Params:
            packages: 要安装的包列表
            manager: 包管理器（pip / uv，默认 pip）
            args: 额外参数列表
            timeout: 超时秒数（默认 120）
        """
        packages = params.get("packages", [])
        if not packages:
            return {"error": "缺少参数: packages"}

        manager = params.get("manager", "pip")
        if manager not in ("pip", "uv"):
            return {"error": f"不支持的包管理器: {manager}，支持: pip, uv"}

        args = params.get("args", [])
        timeout = params.get("timeout", 120)

        if manager == "uv":
            cmd_parts = ["uv", "pip", "install"] + list(packages)
        else:
            cmd_parts = ["pip", "install"] + list(packages)
        cmd_parts.extend(args)

        return await self._run_command(cmd_parts, timeout=timeout)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    async def _run_command(
        self,
        cmd_parts: list[str],
        timeout: int = 60,
    ) -> dict:
        """执行命令行并返回结果。"""
        command = " ".join(cmd_parts)
        logger.debug(f"执行命令: {command}")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workspace),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return {
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        except asyncio.TimeoutError:
            logger.error(f"命令超时 ({timeout}s): {command[:100]}")
            return {"error": f"命令超时 ({timeout}s): {command[:100]}"}
        except Exception as e:
            logger.error(f"命令执行失败: {e}")
            return {"error": str(e)}
