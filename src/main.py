"""JavasAgent 入口。

提供 CLI 交互界面。
"""

from __future__ import annotations

import asyncio
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from src.agents.base_agent import BaseAgent
from src.platforms import create_platform_adapter
from src.tools.system_control import SystemControl
from src.utils.config import load_config
from src.utils.logger import get_logger, setup_logger

console = Console()


def create_agent() -> BaseAgent:
    """创建并配置 Agent 实例。"""
    config = load_config()
    setup_logger(config.platform.log_level, config.platform.log_path)
    logger = get_logger("main")

    platform_adapter = create_platform_adapter(config)
    agent = BaseAgent(config, platform=platform_adapter)

    # 注册基础工具
    if config.tools.system_control.enabled:
        agent.register_tool("system_control", SystemControl())
        agent.register_tool("shell", SystemControl())
        logger.info("系统控制工具已注册")

    return agent


@click.group()
@click.version_option(version="0.1.0")
def cli() -> None:
    """JavasAgent - 像贾维斯一样的AI智能体。"""
    pass


@cli.command()
def chat() -> None:
    """启动交互式对话。"""
    console.print(
        Panel(
            "[bold cyan]JavasAgent[/bold cyan] v0.1.0\n"
            "像贾维斯一样的AI智能体\n"
            "输入 [bold]exit[/bold] 或 [bold]quit[/bold] 退出",
            title="🤖 Welcome",
            border_style="cyan",
        )
    )

    agent = create_agent()

    while True:
        try:
            user_input = Prompt.ask("[bold green]你[/bold green]")
            if user_input.strip().lower() in ("exit", "quit", "q"):
                console.print("[dim]再见，老板。[/dim]")
                break

            if not user_input.strip():
                continue

            result = asyncio.run(agent.process(user_input))
            console.print(f"[bold blue]Javas[/bold blue]: {result}")

        except KeyboardInterrupt:
            console.print("\n[dim]再见，老板。[/dim]")
            break
        except Exception as e:
            console.print(f"[red]错误: {e}[/red]")


@cli.command()
@click.argument("command")
def run(command: str) -> None:
    """执行单条命令。"""
    agent = create_agent()
    result = asyncio.run(agent.process(command))
    console.print(result)


@cli.command()
def status() -> None:
    """查看 Agent 状态。"""
    agent = create_agent()
    s = agent.status
    console.print(
        Panel(
            f"运行状态: {'✅ 运行中' if s['running'] else '⏸️ 空闲'}\n"
            f"队列任务: {s['scheduler']['queued']}\n"
            f"运行中: {s['scheduler']['running']}\n"
            f"已完成: {s['scheduler']['completed']}\n"
            f"记忆大小: {s['memory_size']} 条消息",
            title="📊 JavasAgent 状态",
            border_style="green",
        )
    )


if __name__ == "__main__":
    cli()
