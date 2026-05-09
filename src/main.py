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
from src.tools.browser_control import BrowserControl
from src.tools.calendar_ops import CalendarOps
from src.tools.code_dev import CodeDev
from src.tools.creative_tools import CreativeTools
from src.tools.email_ops import EmailOps
from src.tools.image_ops import ImageOps
from src.tools.office_ops import OfficeOps
from src.tools.process_manager import ProcessManager
from src.tools.system_control import SystemControl
from src.tools.voice_ops import VoiceOps
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

    # 注册系统控制工具
    if config.tools.system_control.enabled:
        system_tool = SystemControl()
        agent.register_tool("system_control", system_tool)
        agent.register_tool("shell", system_tool)
        logger.info("系统控制工具已注册")

    # 注册代码开发工具
    if config.tools.code_dev.enabled:
        code_dev = CodeDev(llm_client=agent._llm)
        agent.register_tool("code_dev", code_dev)
        logger.info("代码开发工具已注册")

    # 注册浏览器控制工具（懒初始化：首次 execute 时自动调用 initialize）
    if config.tools.browser_control.enabled:
        browser = BrowserControl()
        agent.register_tool("browser_control", browser)
        logger.info("浏览器控制工具已注册（懒初始化模式）")

    # 注册办公自动化工具
    if config.tools.office_ops.enabled:
        office = OfficeOps()
        agent.register_tool("office_ops", office)
        logger.info("办公自动化工具已注册")

    # 注册图片处理工具
    if config.tools.image_ops.enabled:
        image_ops = ImageOps()
        agent.register_tool("image_ops", image_ops)
        logger.info("图片处理工具已注册")

    # 注册邮件工具
    if config.tools.email_ops.enabled:
        email_ops = EmailOps()
        agent.register_tool("email_ops", email_ops)
        logger.info("邮件工具已注册")

    # 注册日历工具
    if config.tools.calendar_ops.enabled:
        calendar_ops = CalendarOps()
        agent.register_tool("calendar_ops", calendar_ops)
        logger.info("日历工具已注册")

    # 注册语音工具
    if config.tools.voice_ops.enabled:
        voice_ops = VoiceOps()
        agent.register_tool("voice_ops", voice_ops)
        logger.info("语音工具已注册")

    # 注册创意工具
    if config.tools.creative_tools.enabled:
        creative_tools = CreativeTools()
        agent.register_tool("creative_tools", creative_tools)
        logger.info("创意工具已注册")

    # 注册进程管理工具
    if config.tools.process_manager.enabled:
        process_manager = ProcessManager()
        agent.register_tool("process_manager", process_manager)
        logger.info("进程管理工具已注册")

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

    async def _chat_loop() -> None:
        async with agent:
            await agent.initialize_memory()
            while True:
                try:
                    user_input = Prompt.ask("[bold green]你[/bold green]")
                    if user_input.strip().lower() in ("exit", "quit", "q"):
                        console.print("[dim]再见，老板。[/dim]")
                        break

                    if not user_input.strip():
                        continue

                    result = await agent.process(user_input)
                    console.print(f"[bold blue]Javas[/bold blue]: {result}")

                except KeyboardInterrupt:
                    console.print("\n[dim]再见，老板。[/dim]")
                    break
                except Exception as e:
                    console.print(f"[red]错误: {e}[/red]")

    asyncio.run(_chat_loop())


@cli.command()
@click.argument("command")
def run(command: str) -> None:
    """执行单条命令。"""
    agent = create_agent()

    async def _run_once() -> str:
        async with agent:
            await agent.initialize_memory()
            return await agent.process(command)

    result = asyncio.run(_run_once())
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


@cli.command()
@click.option("--limit", "-n", default=10, help="显示最近 N 条历史记录")
def history(limit: int) -> None:
    """查看任务执行历史。"""
    agent = create_agent()
    from rich.table import Table

    table = Table(title="📋 任务执行历史", show_lines=True)
    table.add_column("序号", style="dim", width=4)
    table.add_column("任务 ID", style="cyan")
    table.add_column("意图", max_width=40)
    table.add_column("状态", width=8)
    table.add_column("提交时间", width=20)

    scheduler_status = agent.status["scheduler"]
    records = scheduler_status.get("history", [])
    if not records:
        console.print("[dim]暂无任务历史记录[/dim]")
        return

    for i, record in enumerate(records[-limit:], 1):
        status_str = {
            "queued": "⏳ 排队",
            "running": "🔄 运行",
            "done": "✅ 完成",
            "failed": "❌ 失败",
        }.get(record.get("status", ""), record.get("status", ""))
        table.add_row(
            str(i),
            record.get("plan_id", ""),
            record.get("intent", "")[:40],
            status_str,
            record.get("submitted_at", ""),
        )

    console.print(table)


@cli.command()
@click.argument("query")
@click.option("--top-k", "-k", default=5, help="返回结果数")
def memory(query: str, top_k: int) -> None:
    """从长期记忆中检索信息。"""
    agent = create_agent()

    async def _search() -> str | list:
        async with agent:
            await agent.initialize_memory()
            results = await agent.recall(query, top_k=top_k)
            return results

    results = asyncio.run(_search())

    if not results:
        console.print(f"[dim]未找到与「{query}」相关的记忆[/dim]")
        return

    from rich.table import Table

    table = Table(title=f"🧠 记忆检索: {query}")
    table.add_column("ID", style="dim", width=15)
    table.add_column("分类", style="cyan", width=12)
    table.add_column("内容", max_width=60)
    table.add_column("相关度", width=8)

    for entry in results:
        table.add_row(
            entry.id[:15],
            entry.category,
            entry.content[:60],
            f"{entry.relevance_score:.2f}",
        )

    console.print(table)


@cli.command()
@click.argument("content")
@click.option("--category", "-c", default="experience", help="记忆分类 (experience/knowledge/preference/skill)")
def remember(content: str, category: str) -> None:
    """将信息存入长期记忆。"""
    agent = create_agent()

    async def _store() -> str | None:
        async with agent:
            await agent.initialize_memory()
            return await agent.remember(content, category=category)

    entry_id = asyncio.run(_store())

    if entry_id:
        console.print(f"✅ 已记忆: {entry_id} [{category}]")
    else:
        console.print("[red]记忆存储失败[/red]")


if __name__ == "__main__":
    cli()
