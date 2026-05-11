"""JavasAgent 入口。

提供 CLI 交互界面。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from src.agents.base_agent import BaseAgent
from src.core.voice_chat import VoiceChatConfig, VoiceChatLoop
from src.platforms import create_platform_adapter
from src.tools.registry import ToolRegistry
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

    # 自动注册所有已启用的工具
    ToolRegistry.auto_register(agent, config)

    # 多 Agent 团队初始化
    if config.team.enabled and agent._team is not None:
        _init_team_members(agent, config)
        logger.info(f"多 Agent 团队已初始化: {config.team.name}")

    return agent


def _init_team_members(agent: BaseAgent, config: Any) -> None:
    """为 Agent 团队添加默认成员。

    根据配置中注册的工具，创建对应角色的子 Agent 并加入团队。

    Args:
        agent: 主 Agent 实例
        config: 应用配置
    """
    if agent._team is None:
        return

    # 定义角色与对应能力的映射
    role_capabilities: dict[str, tuple[str, list[str]]] = {
        "coder": ("代码开发", ["code", "programming", "testing"]),
        "researcher": ("信息搜索", ["search", "web", "analysis"]),
        "operator": ("系统操作", ["system", "os", "file", "shell"]),
    }

    max_workers = config.team.max_workers
    added = 0

    async def _add() -> None:
        nonlocal added
        for role, (_, caps) in role_capabilities.items():
            if added >= max_workers:
                break
            try:
                await agent._team.add_agent(
                    agent_id=f"{role}_1",
                    role=role,
                    capabilities=caps,
                )
                added += 1
            except ValueError:
                pass  # 已存在，跳过

    asyncio.run(_add())


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
@click.option("--wake-word", "-w", default="", help="唤醒词（空则不需要唤醒词）")
@click.option("--tts-rate", "-r", default=0, type=int, help="TTS 语速 (-10~10)")
def voice(wake_word: str, tts_rate: int) -> None:
    """启动语音对话模式。"""
    console.print(
        Panel(
            "[bold cyan]JavasAgent[/bold cyan] v0.1.0 — 语音模式\n"
            "像贾维斯一样的语音助手\n"
            "说出 [bold]退出[/bold] 或按 [bold]Ctrl+C[/bold] 结束",
            title="🎤 Voice Mode",
            border_style="cyan",
        )
    )

    agent = create_agent()
    voice_ops = VoiceOps()
    chat_config = VoiceChatConfig(
        wake_word=wake_word,
        tts_rate=tts_rate,
    )

    # 状态映射表
    state_labels = {
        "listening": "[bold yellow]🎤 正在听...[/bold yellow]",
        "thinking": "[bold magenta]🧠 思考中...[/bold magenta]",
        "speaking": "[bold green]🔊 回复中...[/bold green]",
        "idle": "[dim]等待中...[/dim]",
        "error": "[bold red]⚠️ 出错了，正在恢复...[/bold red]",
    }

    def on_state_change(state: str) -> None:
        """打印当前状态提示。"""
        label = state_labels.get(state, state)
        console.print(f"\r{label}", end="")

    voice_loop = VoiceChatLoop(agent, voice_ops, chat_config)
    voice_loop.set_state_callback(on_state_change)

    async def _voice_chat_loop() -> None:
        async with agent:
            await agent.initialize_memory()
            try:
                await voice_loop.start()
            except KeyboardInterrupt:
                pass
            finally:
                if voice_loop.is_running:
                    await voice_loop.stop()
                console.print("\n[dim]语音模式已退出。[/dim]")

    try:
        asyncio.run(_voice_chat_loop())
    except KeyboardInterrupt:
        console.print("\n[dim]再见，老板。[/dim]")


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


@cli.command()
def team() -> None:
    """查看多 Agent 团队状态。"""
    agent = create_agent()
    ts = agent.get_team_status()

    if not ts.get("enabled"):
        console.print(
            Panel(
                "多 Agent 模式未启用。\n"
                "在配置文件中设置 team.enabled=true 开启。",
                title="👥 团队状态",
                border_style="yellow",
            )
        )
        return

    table = Table(title=f"👥 团队: {ts.get('team_name', 'N/A')}", show_lines=True)
    table.add_column("Agent ID", style="cyan", width=20)
    table.add_column("角色", width=15)
    table.add_column("状态", width=10)
    table.add_column("能力", max_width=40)

    for m in ts.get("members", []):
        status_icon = {"idle": "🟢", "busy": "🔴", "offline": "⚫"}.get(
            m.get("status", ""), "⚪"
        )
        table.add_row(
            m.get("agent_id", ""),
            m.get("role", ""),
            f"{status_icon} {m.get('status', '')}",
            ", ".join(m.get("capabilities", [])),
        )

    console.print(table)
    console.print(
        f"\n成员数: {ts.get('total_members', 0)} | "
        f"已委派任务: {ts.get('delegated_tasks', 0)}"
    )


if __name__ == "__main__":
    cli()
