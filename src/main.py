"""JavasAgent 入口。

提供 CLI 交互界面。
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

# Windows GBK 终端兼容：强制 UTF-8 输出
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from src.agents.base_agent import BaseAgent
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


# ------------------------------------------------------------------
# service 子命令组
# ------------------------------------------------------------------
@cli.group()
def service() -> None:
    """后台服务管理。"""
    pass


@service.command("start")
@click.option("--background", is_flag=True, default=False, help="后台静默运行（无终端输出）")
def service_start(background: bool) -> None:
    """启动后台服务。

    \b
    javas service start             前台运行（可看日志）
    javas service start --background  后台静默运行
    """
    from src.daemon.service import JavasService, ServiceConfig

    config = load_config()
    daemon_cfg = getattr(config, "daemon", None)

    svc_config = ServiceConfig()
    if daemon_cfg is not None:
        svc_config.pipe_name = getattr(daemon_cfg, "pipe_name", svc_config.pipe_name)
        svc_config.autostart = getattr(daemon_cfg, "autostart", svc_config.autostart)
        svc_config.tray_enabled = getattr(daemon_cfg, "tray_enabled", svc_config.tray_enabled)
        svc_config.tray_tooltip = getattr(daemon_cfg, "tray_tooltip", svc_config.tray_tooltip)
        svc_config.window_width = getattr(daemon_cfg, "window_width", svc_config.window_width)
        svc_config.window_height = getattr(daemon_cfg, "window_height", svc_config.window_height)
        svc_config.window_always_on_top = getattr(daemon_cfg, "window_always_on_top", svc_config.window_always_on_top)

        # 热键
        hotkeys = getattr(daemon_cfg, "hotkeys", None)
        if hotkeys and isinstance(hotkeys, dict):
            svc_config.hotkeys = hotkeys

    svc = JavasService(config=svc_config)

    if background:
        # 后台模式：最小化输出
        import logging
        logging.basicConfig(level=logging.WARNING)
    else:
        console.print(
            Panel(
                "[bold cyan]JavasAgent[/bold cyan] 后台服务\n"
                "按 [bold]Ctrl+C[/bold] 停止",
                title="🚀 Service Mode",
                border_style="cyan",
            )
        )

    async def _run():
        try:
            await svc.start()
            # 保持运行直到停止
            while svc.is_running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await svc.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("[dim]服务已停止[/dim]")


@service.command("stop")
def service_stop() -> None:
    """停止后台服务。"""
    from src.daemon.ipc_client import IPCClient

    try:
        client = IPCClient()
        client.connect()
        result = client.send_request("stop", {})
        client.close()
        console.print("[green]✅ 服务停止命令已发送[/green]")
    except ConnectionError:
        console.print("[yellow]⚠️ 后台服务未运行[/yellow]")
    except Exception as exc:
        console.print(f"[red]❌ 停止失败: {exc}[/red]")


@service.command("status")
def service_status() -> None:
    """查询后台服务状态。"""
    from src.daemon.ipc_client import IPCClient

    try:
        client = IPCClient()
        client.connect()
        result = client.send_request("status", {})
        client.close()

        table = Table(title="📊 后台服务状态")
        table.add_column("组件", style="cyan")
        table.add_column("状态")

        state = result.get("state", "unknown")
        state_icon = {"running": "🟢", "stopped": "🔴", "starting": "🟡"}.get(state, "⚪")
        table.add_row("服务状态", f"{state_icon} {state}")
        table.add_row("Agent", "✅ 就绪" if result.get("agent") else "❌ 未就绪")
        table.add_row("IPC 服务器", "✅ 运行" if result.get("ipc_server") else "❌ 停止")
        table.add_row("系统托盘", "✅ 运行" if result.get("tray") else "❌ 停止")
        table.add_row("全局热键", "✅ 活跃" if result.get("hotkey") else "❌ 停止")
        table.add_row("对话窗口", "✅ 就绪" if result.get("chat_window") else "❌ 未创建")
        voice_status = "✅ 开启" if result.get("voice_enabled") else "⏸️ 关闭"
        table.add_row("语音", voice_status)

        console.print(table)
    except ConnectionError:
        console.print("[yellow]⚠️ 后台服务未运行[/yellow]")
        console.print("使用 [bold]javas service start[/bold] 启动")
    except Exception as exc:
        console.print(f"[red]❌ 查询失败: {exc}[/red]")


@service.command("install")
def service_install() -> None:
    """启用开机自启。"""
    from src.daemon.autostart import AutoStart

    try:
        AutoStart.enable()
        console.print("[green]✅ 开机自启已启用[/green]")
    except RuntimeError as exc:
        console.print(f"[red]❌ {exc}[/red]")
    except OSError as exc:
        console.print(f"[red]❌ 注册表写入失败: {exc}[/red]")


@service.command("uninstall")
def service_uninstall() -> None:
    """禁用开机自启。"""
    from src.daemon.autostart import AutoStart

    try:
        AutoStart.disable()
        console.print("[green]✅ 开机自启已禁用[/green]")
    except RuntimeError as exc:
        console.print(f"[red]❌ {exc}[/red]")
    except OSError as exc:
        console.print(f"[red]❌ 注册表操作失败: {exc}[/red]")


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
@click.option("--no-wake", is_flag=True, default=False, help="免唤醒直接对话模式")
@click.option("--continuous", is_flag=True, default=False, help="唤醒后持续对话")
@click.option("--keyword", "-k", default="", help="指定唤醒词")
@click.option("--list-keywords", is_flag=True, default=False, help="列出可用唤醒词")
@click.option("--wake-word", "-w", default="", help="唤醒词（空则不需要唤醒词）", hidden=True)
@click.option("--tts-rate", "-r", default=0, type=int, help="TTS 语速 (-10~10)")
def voice(
    no_wake: bool,
    continuous: bool,
    keyword: str,
    list_keywords: bool,
    wake_word: str,
    tts_rate: int,
) -> None:
    """启动语音对话模式。

    \b
    javas voice                    启动语音模式（需唤醒词）
    javas voice --no-wake          免唤醒直接对话模式
    javas voice --continuous       唤醒后持续对话
    javas voice --keyword 贾维斯   指定唤醒词
    javas voice --list-keywords    列出可用唤醒词
    """
    config = load_config()

    # --list-keywords：列出可用唤醒词后退出
    if list_keywords:
        keywords = config.voice.wake_word.keywords
        console.print(
            Panel(
                "可用唤醒词：\n"
                + "\n".join(f"  • {kw}" for kw in keywords),
                title="🔑 唤醒词列表",
                border_style="cyan",
            )
        )
        return

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

    # 构建管道配置
    from src.voice.pipeline import VoicePipeline, VoicePipelineConfig

    wake_word_enabled = not no_wake
    effective_keyword = keyword or wake_word or ""
    effective_keywords = [effective_keyword] if effective_keyword else config.voice.wake_word.keywords

    pipeline_config = VoicePipelineConfig(
        wake_words=effective_keywords,
        wake_word_enabled=wake_word_enabled,
        continuous_mode=continuous or config.voice.pipeline.continuous_mode,
        continuous_timeout=config.voice.pipeline.continuous_timeout,
        interruption_enabled=config.voice.pipeline.interruption_enabled,
        stt_engine=config.voice.stt.engine,
        tts_engine=config.voice.tts.engine,
        greeting=config.voice.pipeline.greeting,
        farewell=config.voice.pipeline.farewell,
        vad_threshold=config.voice.vad.threshold,
        silence_timeout=config.voice.vad.silence_timeout,
    )

    pipeline = VoicePipeline(agent, voice_ops, pipeline_config)

    # 状态映射表
    state_labels = {
        "listening": "[bold yellow]🎤 正在听...[/bold yellow]",
        "processing": "[bold magenta]🧠 思考中...[/bold magenta]",
        "speaking": "[bold green]🔊 回复中...[/bold green]",
        "idle": "[dim]等待中...[/dim]",
    }

    def on_state_change(state: Any) -> None:
        """打印当前状态提示。"""
        label = state_labels.get(state.value if hasattr(state, "value") else state, str(state))
        console.print(f"\r{label}", end="")

    pipeline.set_state_callback(on_state_change)

    async def _voice_chat_loop() -> None:
        async with agent:
            await agent.initialize_memory()
            try:
                await pipeline.start()
            except KeyboardInterrupt:
                pass
            finally:
                if pipeline.is_running:
                    await pipeline.stop()
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
