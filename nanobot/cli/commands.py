"""CLI commands for nanobot."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from nanobot import __version__, __logo__

app = typer.Typer(
    name="nanobot",
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} nanobot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """nanobot - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize nanobot configuration and workspace."""
    from nanobot.config.loader import get_config_path, save_config
    from nanobot.config.schema import Config
    from nanobot.utils.helpers import get_workspace_path
    
    config_path = get_config_path()
    
    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        if not typer.confirm("Overwrite?"):
            raise typer.Exit()
    
    # Create default config
    config = Config()
    save_config(config)
    console.print(f"[green]✓[/green] Created config at {config_path}")
    
    # Create workspace
    workspace = get_workspace_path()
    console.print(f"[green]✓[/green] Created workspace at {workspace}")
    
    # Create default bootstrap files
    _create_workspace_templates(workspace)
    
    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print(f"  1. Add your API key to [cyan]{config_path}[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]nanobot agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]")




def _create_workspace_templates(workspace: Path):
    """Create default workspace template files."""
    templates = {
        "AGENTS.md": """# Agent Instructions

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Guidelines

- Always explain what you're doing before taking actions
- Ask for clarification when the request is ambiguous
- Use tools to help accomplish tasks
- Remember important information in your memory files
""",
        "SOUL.md": """# Soul

I am nanobot, a lightweight AI assistant.

## Personality

- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values

- Accuracy over speed
- User privacy and safety
- Transparency in actions
""",
        "USER.md": """# User

Information about the user goes here.

## Preferences

- Communication style: (casual/formal)
- Timezone: (your timezone)
- Language: (your preferred language)
""",
    }
    
    for filename, content in templates.items():
        file_path = workspace / filename
        if not file_path.exists():
            file_path.write_text(content)
            console.print(f"  [dim]Created {filename}[/dim]")
    
    # Create memory directory and MEMORY.md
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text("""# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Important Notes

(Things to remember)
""")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the nanobot gateway."""
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.agent.loop import AgentLoop
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    
    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    
    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")
    
    config = load_config()
    
    # Create components
    bus = MessageBus()
    
    # Create provider (supports OpenRouter, Anthropic, OpenAI, Bedrock)
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    if not api_key and not is_bedrock:
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in your nanobot config file under providers.openrouter.apiKey or providers.openai.apiKey")
        raise typer.Exit(1)
    
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model
    )
    
    # Create cron service first (callback set after agent creation)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)
    
    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_tokens=config.agents.defaults.max_tokens,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        token_budget_mode=config.agents.defaults.token_budget_mode,
        merge_subagent_usage=config.agents.defaults.merge_subagent_usage,
        max_iterations=config.agents.defaults.max_tool_iterations,
        reasoning_effort=config.agents.defaults.reasoning_effort,
        web_search_config=config.tools.web.search,
        exec_config=config.tools.exec,
        mineru_config=config.tools.mineru,
        image_gen_config=config.tools.image_gen,
        notion_config=config.tools.notion,
        tool_history_config=config.tools.tool_history,
        context_compression_config=config.tools.context_compression,
        memory_system_config=config.tools.memory_system,
        feishu_config=config.channels.feishu,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
    )
    
    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )
        if job.payload.deliver and job.payload.to:
            from nanobot.bus.events import OutboundMessage
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                content=response or ""
            ))
        return response
    cron.on_job = on_cron_job
    
    # Create heartbeat service (starts only if enabled in state file)
    async def on_heartbeat(prompt: str) -> str:
        """Execute heartbeat through the agent."""
        return await agent.process_direct(prompt, session_key="heartbeat")
    
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        on_heartbeat=on_heartbeat,
        interval_s=20 * 60,  # 20 minutes
    )
    
    # Create channel manager
    channels = ChannelManager(config, bus)
    
    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")
    
    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
    
    heartbeat_status = heartbeat.get_status()
    if heartbeat_status["enabled"]:
        status_str = "[green]✓[/green]" if heartbeat_status["running"] else "[yellow]enabled (not running)[/yellow]"
        console.print(f"{status_str} Heartbeat: every {heartbeat_status['interval_s'] // 60}m")
    else:
        console.print("[dim]Heartbeat: disabled (use 'nanobot heartbeat start' to enable)[/dim]")
    
    async def run():
        try:
            await cron.start()
            await heartbeat.start()
            await asyncio.gather(
                agent.run(),
                channels.start_all(),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()
    
    asyncio.run(run())




# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:default", "--session", "-s", help="Session ID"),
):
    """Interact with the agent directly."""
    from nanobot.config.loader import load_config
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.agent.loop import AgentLoop
    
    config = load_config()
    
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    if not api_key and not is_bedrock:
        console.print("[red]Error: No API key configured.[/red]")
        raise typer.Exit(1)

    bus = MessageBus()
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model
    )
    
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_tokens=config.agents.defaults.max_tokens,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        token_budget_mode=config.agents.defaults.token_budget_mode,
        merge_subagent_usage=config.agents.defaults.merge_subagent_usage,
        max_iterations=config.agents.defaults.max_tool_iterations,
        reasoning_effort=config.agents.defaults.reasoning_effort,
        web_search_config=config.tools.web.search,
        exec_config=config.tools.exec,
        mineru_config=config.tools.mineru,
        notion_config=config.tools.notion,
        tool_history_config=config.tools.tool_history,
        context_compression_config=config.tools.context_compression,
        memory_system_config=config.tools.memory_system,
        feishu_config=config.channels.feishu,
        restrict_to_workspace=config.tools.restrict_to_workspace,
    )
    
    # --- Initialize channel senders for CLI mode ---
    # In CLI mode there is no gateway dispatcher, so we attach lightweight
    # channel senders directly so that the message tool can deliver to
    # external channels (e.g. Feishu) even when invoked from cron scripts.
    _cli_channels: dict[str, Any] = {}

    if config.channels.feishu.enabled:
        try:
            from nanobot.channels.feishu import FeishuChannel, FEISHU_AVAILABLE
            if FEISHU_AVAILABLE:
                _feishu_ch = FeishuChannel(config.channels.feishu, bus)
                # Initialise the Lark client for sending (no WebSocket needed)
                import lark_oapi as _lark
                _feishu_ch._client = _lark.Client.builder() \
                    .app_id(config.channels.feishu.app_id) \
                    .app_secret(config.channels.feishu.app_secret) \
                    .log_level(_lark.LogLevel.WARNING) \
                    .build()
                _cli_channels["feishu"] = _feishu_ch
        except Exception as e:
            console.print(f"[dim]Feishu send init skipped: {e}[/dim]")

    # Replace the default send_callback on the message tool so that
    # outbound messages are dispatched directly to the appropriate channel
    # sender instead of being queued on the bus (which has no consumer in
    # CLI mode).
    if _cli_channels:
        from nanobot.agent.tools.message import MessageTool as _MT

        async def _cli_send_callback(msg):
            ch = _cli_channels.get(msg.channel)
            if ch:
                await ch.send(msg)
            else:
                # Fallback: just put on bus (original behaviour)
                await bus.publish_outbound(msg)

        _msg_tool = agent_loop.tools.get("message")
        if isinstance(_msg_tool, _MT):
            _msg_tool.set_send_callback(_cli_send_callback)
    # --- End channel sender init ---
    
    if message:
        # Single message mode
        async def run_once():
            response = await agent_loop.process_direct(message, session_id)
            console.print(f"\n{__logo__} {response}")
        
        asyncio.run(run_once())
    else:
        # Interactive mode
        console.print(f"{__logo__} Interactive mode (Ctrl+C to exit)\n")
        
        async def run_interactive():
            while True:
                try:
                    user_input = console.input("[bold blue]You:[/bold blue] ")
                    if not user_input.strip():
                        continue
                    
                    response = await agent_loop.process_direct(user_input, session_id)
                    console.print(f"\n{__logo__} {response}\n")
                except KeyboardInterrupt:
                    console.print("\nGoodbye!")
                    break
        
        asyncio.run(run_interactive())


@app.command()
def memory_refresh(
    diary: str = typer.Option(..., "--diary", help="Path to daily diary markdown file"),
    source: str = typer.Option("", "--source", help="Optional extracted_from label"),
):
    """Extract and merge personal memory from a daily diary file."""
    from nanobot.config.loader import load_config
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.agent.loop import AgentLoop

    config = load_config()
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")
    if not api_key and not is_bedrock:
        console.print("[red]Error: No API key configured.[/red]")
        raise typer.Exit(1)

    bus = MessageBus()
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model,
    )
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_tokens=config.agents.defaults.max_tokens,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        token_budget_mode=config.agents.defaults.token_budget_mode,
        merge_subagent_usage=config.agents.defaults.merge_subagent_usage,
        max_iterations=config.agents.defaults.max_tool_iterations,
        reasoning_effort=config.agents.defaults.reasoning_effort,
        web_search_config=config.tools.web.search,
        exec_config=config.tools.exec,
        mineru_config=config.tools.mineru,
        notion_config=config.tools.notion,
        tool_history_config=config.tools.tool_history,
        context_compression_config=config.tools.context_compression,
        memory_system_config=config.tools.memory_system,
        feishu_config=config.channels.feishu,
        restrict_to_workspace=config.tools.restrict_to_workspace,
    )

    diary_path = Path(diary).expanduser()
    if not diary_path.exists():
        console.print(f"[red]Diary not found:[/red] {diary_path}")
        raise typer.Exit(1)

    async def run_once():
        result = await agent_loop.process_memory_daily_update(diary_path, extracted_from=source or diary_path.name)
        console.print(json.dumps(result, ensure_ascii=False))

    import json
    asyncio.run(run_once())


@app.command()
def memory_status(
    user_id: str = typer.Option("", "--user-id", help="Optional memory user id override"),
    events: int = typer.Option(8, "--events", help="How many recent merge events to show"),
):
    """Show personal memory database status and recent events."""
    from nanobot.config.loader import load_config
    from nanobot.agent.personal_memory_store import PersonalMemoryStore

    config = load_config()
    store = PersonalMemoryStore(config.workspace_path, config.tools.memory_system)
    stats = store.get_stats(user_id=user_id or None)

    console.print(f"\n{__logo__} Personal Memory Status\n")
    console.print(f"DB: [cyan]{stats['db_path']}[/cyan]")
    console.print(f"User: [cyan]{stats['user_id']}[/cyan]")
    console.print(f"Active: [green]{stats['active']}[/green]")
    console.print(f"Superseded: [yellow]{stats['superseded']}[/yellow]")
    console.print(f"Archived: [dim]{stats['archived']}[/dim]")
    console.print(f"Candidates(unmerged/total): [magenta]{stats['candidates_unmerged']}[/magenta] / {stats['candidates_total']}")
    console.print(f"Events: [blue]{stats['events_total']}[/blue]")
    console.print(f"Latest update: [cyan]{stats['latest_update'] or 'N/A'}[/cyan]")

    core_items = store.list_core_candidates(user_id=user_id or None)
    if core_items:
        table = Table(title="Auto Core Memory")
        table.add_column("Slot", style="cyan")
        table.add_column("Kind", style="green")
        table.add_column("Priority", style="yellow")
        table.add_column("Summary")
        for item in core_items:
            table.add_row(
                str(item.get("slot") or ""),
                str(item.get("kind") or ""),
                str(item.get("priority") or 0),
                str(item.get("summary") or item.get("content") or ""),
            )
        console.print(table)

    recent_events = store.list_recent_events(user_id=user_id or None, limit=max(0, events))
    if recent_events:
        evt = Table(title="Recent Memory Events")
        evt.add_column("Time", style="cyan")
        evt.add_column("Action", style="green")
        evt.add_column("Memory ID", style="yellow")
        evt.add_column("Reason")
        for item in recent_events:
            evt.add_row(
                str(item.get("created_at") or ""),
                str(item.get("action") or ""),
                str(item.get("memory_id") or ""),
                str(item.get("reason") or ""),
            )
        console.print(evt)


@app.command()
def memory_search(
    query: str = typer.Argument(..., help="Query for personal memory retrieval"),
    top_k: int = typer.Option(5, "--top-k", help="Top-K memories to return"),
    user_id: str = typer.Option("", "--user-id", help="Optional memory user id override"),
):
    """Query personal memory."""
    from nanobot.config import load_config
    from nanobot.personal_memory.store import PersonalMemoryStore
    from rich.table import Table
    
    config = load_config()
    store = PersonalMemoryStore(config.workspace_path, config.tools.memory_system)
    results = store.retrieve(query=query, top_k=max(1, top_k), user_id=user_id or None)
    """Search personal memory using the same retrieval logic as prompt injection."""
    from nanobot.config.loader import load_config
    from nanobot.agent.personal_memory_store import PersonalMemoryStore

    config = load_config()
    store = PersonalMemoryStore(config.workspace_path, config.tools.memory_system)
    results = store.retrieve(query=query, top_k=max(1, top_k), user_id=user_id or None)

    console.print(f"\n{__logo__} Memory Search\n")
    console.print(f"Query: [cyan]{query}[/cyan]")
    console.print(f"Hits: [green]{len(results)}[/green]\n")

    if not results:
        console.print("[yellow]No relevant memories found.[/yellow]")
        raise typer.Exit(0)

    table = Table(title="Retrieved Personal Memories")
    table.add_column("Slot", style="cyan")
    table.add_column("Kind", style="green")
    table.add_column("Scope", style="yellow")
    table.add_column("Priority", style="magenta")
    table.add_column("Summary")
    for item in results:
        table.add_row(
            str(item.get("slot") or ""),
            str(item.get("kind") or ""),
            str(item.get("scope") or ""),
            str(item.get("priority") or 0),
            str(item.get("summary") or item.get("content") or ""),
        )
    console.print(table)


@app.command()
def memory_benchmark(
    query: str = typer.Argument(..., help="Query text to benchmark prompt-memory retrieval"),
    repeats: int = typer.Option(5, "--repeats", min=1, help="Number of hot-run repeats"),
    session_id: str = typer.Option("cli:bench", "--session", "-s", help="Session ID for benchmark context"),
):
    """Benchmark personal memory retrieval and context build latency."""
    import statistics
    import time

    from nanobot.config.loader import load_config
    from nanobot.agent.context import ContextBuilder

    config = load_config()
    ctx = ContextBuilder(config.workspace_path, memory_system_config=config.tools.memory_system)

    history = [
        {"role": "user", "content": "我们之前讨论过长期记忆系统和 prompt 注入。"},
        {"role": "assistant", "content": "好的，我会基于已有长期记忆继续回答。"},
    ]
    session_summary = f"session={session_id}; topic=memory benchmark"

    def run_once() -> dict:
        retrieval_ms = 0.0
        retrieved_count = 0
        if ctx.memory_retriever:
            t0 = time.perf_counter()
            retrieved = ctx.memory_retriever.retrieve_for_prompt(
                user_text=query,
                session_state=session_summary,
                recent_messages=history,
            )
            retrieval_ms = (time.perf_counter() - t0) * 1000.0
            retrieved_count = len(retrieved)
        t1 = time.perf_counter()
        _ = ctx.build_messages(
            history=history,
            current_message=query,
            session_summary=session_summary,
            channel="cli",
            chat_id="benchmark",
        )
        build_ms = (time.perf_counter() - t1) * 1000.0
        stats = dict(ctx.last_build_stats)
        stats["direct_retrieval_ms"] = round(retrieval_ms, 3)
        stats["direct_retrieved_count"] = retrieved_count
        stats["measured_build_ms"] = round(build_ms, 3)
        return stats

    cold = run_once()
    hots = [run_once() for _ in range(max(1, repeats))]

    def metric(rows: list[dict], key: str) -> tuple[float, float, float]:
        vals = [float(r.get(key, 0.0) or 0.0) for r in rows]
        return min(vals), statistics.mean(vals), max(vals)

    console.print(f"\n{__logo__} Memory Benchmark\n")
    console.print(f"Query: [cyan]{query}[/cyan]")
    console.print(f"Memory enabled: [green]{config.tools.memory_system.enabled}[/green]")
    console.print(f"Retrieval top-k: [cyan]{config.tools.memory_system.retrieval_top_k}[/cyan]")
    console.print(f"Cold run retrieved: [green]{cold.get('retrieved_count', 0)}[/green]")
    console.print(f"Cold direct retrieval: [yellow]{cold.get('direct_retrieval_ms', 0.0):.3f} ms[/yellow]")
    console.print(f"Cold context retrieval: [yellow]{cold.get('retrieval_ms', 0.0):.3f} ms[/yellow]")
    console.print(f"Cold system prompt: [yellow]{cold.get('system_prompt_ms', 0.0):.3f} ms[/yellow]")
    console.print(f"Cold total context build: [yellow]{cold.get('total_ms', 0.0):.3f} ms[/yellow]\n")

    table = Table(title=f"Hot Runs x{len(hots)}")
    table.add_column("Metric", style="cyan")
    table.add_column("Min (ms)", style="green")
    table.add_column("Mean (ms)", style="yellow")
    table.add_column("Max (ms)", style="magenta")
    for key, label in [
        ("direct_retrieval_ms", "Direct retrieval"),
        ("retrieval_ms", "Context retrieval"),
        ("system_prompt_ms", "System prompt build"),
        ("total_ms", "Total context build"),
    ]:
        mn, avg, mx = metric(hots, key)
        table.add_row(label, f"{mn:.3f}", f"{avg:.3f}", f"{mx:.3f}")
    console.print(table)


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from nanobot.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Configuration", style="yellow")

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row(
        "WhatsApp",
        "✓" if wa.enabled else "✗",
        wa.bridge_url
    )

    dc = config.channels.discord
    table.add_row(
        "Discord",
        "✓" if dc.enabled else "✗",
        dc.gateway_url
    )
    
    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row(
        "Telegram",
        "✓" if tg.enabled else "✗",
        tg_config
    )

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess
    from nanobot.utils.helpers import get_bridge_path
    
    # User's bridge location
    user_bridge = get_bridge_path()
    
    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge
    
    # Check for npm
    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)
    
    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # nanobot/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)
    
    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge
    
    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall nanobot")
        raise typer.Exit(1)
    
    console.print(f"{__logo__} Setting up bridge...")
    
    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))
    
    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)
        
        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)
        
        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)
    
    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import subprocess
    
    bridge_dir = _get_bridge_dir()
    
    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")
    
    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Cron Commands
# ============================================================================

cron_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Include disabled jobs"),
):
    """List scheduled jobs."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    jobs = service.list_jobs(include_disabled=all)
    
    if not jobs:
        console.print("No scheduled jobs.")
        return
    
    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Next Run")
    
    import time
    for job in jobs:
        # Format schedule
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = job.schedule.expr or ""
        else:
            sched = "one-time"
        
        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            next_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(job.state.next_run_at_ms / 1000))
            next_run = next_time
        
        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"
        
        table.add_row(job.id, job.name, sched, status, next_run)
    
    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"),
):
    """Add a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronSchedule
    
    # Determine schedule type
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr)
    elif at:
        import datetime
        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Error: Must specify --every, --cron, or --at[/red]")
        raise typer.Exit(1)
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    job = service.add_job(
        name=name,
        schedule=schedule,
        message=message,
        deliver=deliver,
        to=to,
        channel=channel,
    )
    
    console.print(f"[green]✓[/green] Added job '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
):
    """Remove a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    if service.remove_job(job_id):
        console.print(f"[green]✓[/green] Removed job {job_id}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("enable")
def cron_enable(
    job_id: str = typer.Argument(..., help="Job ID"),
    disable: bool = typer.Option(False, "--disable", help="Disable instead of enable"),
):
    """Enable or disable a job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    job = service.enable_job(job_id, enabled=not disable)
    if job:
        status = "disabled" if disable else "enabled"
        console.print(f"[green]✓[/green] Job '{job.name}' {status}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="Job ID to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if disabled"),
):
    """Manually run a job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    async def run():
        return await service.run_job(job_id, force=force)
    
    if asyncio.run(run()):
        console.print(f"[green]✓[/green] Job executed")
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Heartbeat Commands
# ============================================================================

heartbeat_app = typer.Typer(help="Manage heartbeat service (periodic agent wake-up)")
app.add_typer(heartbeat_app, name="heartbeat")


@heartbeat_app.command("status")
def heartbeat_status():
    """Show heartbeat service status."""
    from nanobot.config.loader import load_config
    from nanobot.heartbeat.service import HeartbeatService
    
    config = load_config()
    service = HeartbeatService(workspace=config.workspace_path)
    status = service.get_status()
    
    console.print(f"\n{__logo__} Heartbeat Status\n")
    
    # Status indicators
    enabled = "[green]enabled[/green]" if status["enabled"] else "[dim]disabled[/dim]"
    running = "[green]running[/green]" if status["running"] else "[dim]stopped[/dim]"
    console.print(f"Enabled:  {enabled}")
    console.print(f"Running:  {running}")
    console.print(f"Interval: [cyan]{status['interval_s'] // 60} minutes[/cyan]")
    
    # Last run info
    if status["last_run_ms"] > 0:
        import time
        last_run = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(status["last_run_ms"] / 1000))
        console.print(f"Last run: [cyan]{last_run}[/cyan]")
    else:
        console.print(f"Last run: [dim]never[/dim]")
    
    console.print(f"Last status: [yellow]{status['last_status']}[/yellow]")
    
    if status["last_error"]:
        console.print(f"Last error: [red]{status['last_error']}[/red]")
    
    # Heartbeat file info
    file_exists = "[green]exists[/green]" if status["heartbeat_file_exists"] else "[yellow]not found[/yellow]"
    console.print(f"HEARTBEAT.md: {file_exists}")
    console.print(f"  Path: [cyan]{status['heartbeat_file']}[/cyan]")


@heartbeat_app.command("start")
def heartbeat_start(
    interval: int = typer.Option(20, "--interval", "-i", help="Interval in minutes (default: 20)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force start without confirmation"),
):
    """
    Start the heartbeat service.
    
    This will periodically wake the agent to check HEARTBEAT.md for tasks.
    Requires user confirmation by default.
    """
    from nanobot.config.loader import load_config
    from nanobot.heartbeat.service import HeartbeatService
    
    config = load_config()
    service = HeartbeatService(
        workspace=config.workspace_path,
        interval_s=interval * 60,  # Convert minutes to seconds
    )
    
    # Check if already running
    if service.is_enabled and service.is_running:
        console.print(f"[yellow]Heartbeat already running[/yellow]")
        raise typer.Exit(0)
    
    # User confirmation
    if not force:
        console.print(f"\n{__logo__} Heartbeat Service\n")
        console.print(f"This will wake the agent every [cyan]{interval} minutes[/cyan]")
        console.print(f"to check [cyan]{service.heartbeat_file}[/cyan] for tasks.")
        console.print("")
        console.print("[dim]If HEARTBEAT.md is empty or has no actionable items,[/dim]")
        console.print("[dim]the agent will simply respond HEARTBEAT_OK and do nothing.[/dim]")
        console.print("")
        
        if not typer.confirm("Start heartbeat service?"):
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit(0)
    
    # Enable and start
    service.enable()
    
    async def start_service():
        await service.start()
    
    asyncio.run(start_service())
    console.print(f"[green]✓[/green] Heartbeat started (every {interval} minutes)")


@heartbeat_app.command("stop")
def heartbeat_stop(
    force: bool = typer.Option(False, "--force", "-f", help="Force stop without confirmation"),
):
    """Stop the heartbeat service."""
    from nanobot.config.loader import load_config
    from nanobot.heartbeat.service import HeartbeatService
    
    config = load_config()
    service = HeartbeatService(workspace=config.workspace_path)
    
    if not service.is_enabled and not service.is_running:
        console.print("[yellow]Heartbeat is not running[/yellow]")
        raise typer.Exit(0)
    
    if not force:
        if not typer.confirm("Stop heartbeat service?"):
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit(0)
    
    service.disable()
    console.print(f"[green]✓[/green] Heartbeat stopped")


@heartbeat_app.command("trigger")
def heartbeat_trigger():
    """Manually trigger a heartbeat check."""
    from nanobot.config.loader import load_config
    from nanobot.heartbeat.service import HeartbeatService
    
    config = load_config()
    service = HeartbeatService(workspace=config.workspace_path)
    
    if not service.is_enabled:
        console.print("[yellow]Heartbeat is not enabled. Run 'nanobot heartbeat start' first.[/yellow]")
        raise typer.Exit(1)
    
    async def run():
        console.print("Triggering heartbeat...")
        response = await service.trigger_now()
        if response:
            console.print(f"\n{__logo__} Response:\n{response}")
        else:
            console.print("[dim]No response[/dim]")
    
    asyncio.run(run())


# ============================================================================
# Subagent Commands
# ============================================================================


subagent_app = typer.Typer(help="Manage and monitor subagent tasks")
app.add_typer(subagent_app, name="subagent")


@subagent_app.command(name="status")
def subagent_status(
    running_only: bool = typer.Option(False, "--running", "-r", help="Show only running tasks"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum number of tasks to show"),
):
    """Show subagent task status."""
    from nanobot.subagent_state import SubagentStateService
    from nanobot.agent.subagent import SubagentManager
    
    # Get state from persistent storage
    state = SubagentStateService.get_instance()
    status = state.get_status()
    
    console.print(f"\n[bold]Subagent Status (Persistent)[/bold]\n")
    console.print(f"Running: [green]{status['runningCount']}[/green]")
    console.print(f"Total Spawned: {status['totalSpawned']}")
    
    tasks = state.list_tasks(include_completed=True, limit=limit, running_only=running_only)
    
    if tasks:
        table = Table(title="Tasks")
        table.add_column("ID", style="cyan", width=8)
        table.add_column("Label", style="green")
        table.add_column("Status", width=10)
        table.add_column("Duration", justify="right")
        
        for task in tasks:
            status_color = "green" if task["status"] == "running" else ("yellow" if task["status"] == "completed" else "red")
            duration = f"{task['durationMs']}ms" if task.get("durationMs") else "running..."
            table.add_row(
                task["taskId"][:8],
                task["label"][:30] + "..." if len(task.get("label", "")) > 30 else task.get("label", ""),
                f"[{status_color}]{task['status']}[/{status_color}]",
                duration,
            )
        
        console.print(table)
    else:
        console.print("[dim]No tasks[/dim]")


@subagent_app.command(name="info")
def subagent_info(
    task_id: str = typer.Argument(..., help="Task ID to inspect"),
):
    """Show detailed information for a specific task."""
    from nanobot.subagent_state import SubagentStateService
    from rich.panel import Panel
    
    state = SubagentStateService.get_instance()
    task = state.get_task(task_id)
    
    if not task:
        console.print(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)
    
    console.print(f"\n[bold]Task: {task_id[:8]}[/bold]\n")
    
    status_color = "green" if task["status"] == "running" else ("yellow" if task["status"] == "completed" else "red")
    console.print(f"Label: [green]{task.get('label', 'N/A')}[/green]")
    console.print(f"Status: [{status_color}]{task['status']}[/{status_color}]")
    
    if task.get("spawnedAtMs"):
        from datetime import datetime
        spawned = datetime.fromtimestamp(task["spawnedAtMs"] / 1000)
        console.print(f"Started: {spawned.strftime('%Y-%m-%d %H:%M:%S')}")
    
    if task.get("completedAtMs"):
        from datetime import datetime
        completed = datetime.fromtimestamp(task["completedAtMs"] / 1000)
        console.print(f"Completed: {completed.strftime('%Y-%m-%d %H:%M:%S')}")
    
    if task.get("durationMs"):
        console.print(f"Duration: {task['durationMs']}ms")
    
    console.print(f"\n[bold]Task:[/bold]")
    console.print(Panel(task.get("task", "N/A"), border_style="dim"))
    
    if task.get("error"):
        console.print(f"\n[bold red]Error:[/bold red]")
        console.print(Panel(task["error"], border_style="red"))
    
    if task.get("result"):
        console.print(f"\n[bold]Result:[/bold]")
        console.print(Panel(task["result"], border_style="green"))
    
    if task.get("usage"):
        console.print(f"\n[bold]Usage:[/bold]")
        for k, v in task["usage"].items():
            console.print(f"  {k}: {v}")


@subagent_app.command(name="clear")
def subagent_clear(
    older_than_ms: int = typer.Option(0, "--older-than", help="Clear tasks older than N milliseconds (0 = all completed)"),
):
    """Clear completed tasks from history."""
    from nanobot.subagent_state import SubagentStateService
    
    state = SubagentStateService.get_instance()
    
    if older_than_ms > 0:
        count = state.clear_completed_tasks(older_than_ms=older_than_ms)
        console.print(f"[green]Cleared {count} completed tasks older than {older_than_ms}ms[/green]")
    else:
        # Clear all completed
        tasks = state.list_tasks(include_completed=True, limit=1000)
        completed = [t for t in tasks if t.get("status") != "running"]
        for task in completed:
            state.clear_completed_tasks(older_than_ms=0)
        console.print(f"[green]Cleared {len(completed)} completed tasks[/green]")


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import load_config, get_config_path

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        console.print(f"Model: {config.agents.defaults.model}")
        
        # Check API keys
        has_openrouter = bool(config.providers.openrouter.api_key)
        has_anthropic = bool(config.providers.anthropic.api_key)
        has_openai = bool(config.providers.openai.api_key)
        has_gemini = bool(config.providers.gemini.api_key)
        has_vllm = bool(config.providers.vllm.api_base)
        
        console.print(f"OpenRouter API: {'[green]✓[/green]' if has_openrouter else '[dim]not set[/dim]'}")
        console.print(f"Anthropic API: {'[green]✓[/green]' if has_anthropic else '[dim]not set[/dim]'}")
        console.print(f"OpenAI API: {'[green]✓[/green]' if has_openai else '[dim]not set[/dim]'}")
        console.print(f"Gemini API: {'[green]✓[/green]' if has_gemini else '[dim]not set[/dim]'}")
        vllm_status = f"[green]✓ {config.providers.vllm.api_base}[/green]" if has_vllm else "[dim]not set[/dim]"
        console.print(f"vLLM/Local: {vllm_status}")


# ============================================================================
# Data Services Commands
# ============================================================================

data_app = typer.Typer(help="Manage PostgreSQL data services (users, tickets, skills)")
app.add_typer(data_app, name="data")


def _get_db_config() -> dict:
    """Get database configuration from environment or defaults."""
    import os
    return {
        "host": os.environ.get("NANOBOT_DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("NANOBOT_DB_PORT", "5433")),
        "database": os.environ.get("NANOBOT_DB_NAME", "nanobot_db"),
        "user": os.environ.get("NANOBOT_DB_USER", "postgres"),
        "password": os.environ.get("NANOBOT_DB_PASSWORD", "postgres"),
    }


@data_app.command("init")
def data_init():
    """Initialize all database tables."""
    from nanobot.services.postgres_user import PostgresUserService
    from nanobot.services.postgres_ticket import PostgresTicketService
    from nanobot.services.postgres_skill import PostgresSkillService
    
    config = _get_db_config()
    console.print("Initializing databases...")
    
    try:
        user_service = PostgresUserService(**config)
        user_service.init_db()
        console.print("[green]+[/green] Users table ready")
        user_service.close()
    except Exception as e:
        console.print(f"[red]x[/red] Users: {e}")
    
    try:
        ticket_service = PostgresTicketService(**config)
        ticket_service.init_db()
        console.print("[green]+[/green] Tickets table ready")
        ticket_service.close()
    except Exception as e:
        console.print(f"[red]x[/red] Tickets: {e}")
    
    try:
        skill_service = PostgresSkillService(**config)
        skill_service.init_db()
        console.print("[green]+[/green] Skills table ready")
        skill_service.close()
    except Exception as e:
        console.print(f"[red]x[/red] Skills: {e}")


@data_app.command("status")
def data_status():
    """Show database status."""
    import psycopg
    
    config = _get_db_config()
    
    try:
        conn = psycopg.connect(**config, connect_timeout=5)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """)
        tables = [r[0] for r in cur.fetchall()]
        
        console.print(f"\n{__logo__} PostgreSQL Status\n")
        console.print(f"Host: [cyan]{config['host']}:{config['port']}[/cyan]")
        console.print(f"Database: [cyan]{config['database']}[/cyan]")
        
        table = Table(title="Tables")
        table.add_column("Table", style="cyan")
        table.add_column("Rows", style="green", justify="right")
        
        for table_name in tables:
            if table_name in ('users', 'tickets', 'ticket_messages', 'skills', 'skill_invocations', 'kb_entries'):
                cur.execute(f"SELECT COUNT(*) FROM \"{table_name}\"")
                count = cur.fetchone()[0]
                table.add_row(table_name, str(count))
        
        console.print(table)
        conn.close()
        
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@data_app.command("demo")
def data_demo():
    """Run a complete demo of all services."""
    from nanobot.services.postgres_user import PostgresUserService, UserRole
    from nanobot.services.postgres_ticket import PostgresTicketService, TicketStatus, TicketPriority, TicketCategory
    from nanobot.services.postgres_skill import PostgresSkillService, SkillCategory, SkillStatus
    
    config = _get_db_config()
    
    console.print(f"\n{__logo__} Data Services Demo\n")
    
    # ---- User Service ----
    console.print("[bold]1. User Service[/bold]")
    user_service = PostgresUserService(**config)
    user_service.init_db()
    
    # Create demo user
    user = user_service.create(
        username="demo_user",
        email="demo@example.com",
        enterprise_id="demo_ent",
        role=UserRole.AGENT,
        display_name="演示用户",
        department="客服部"
    )
    console.print(f"  Created user: [green]{user.username}[/green] ({user.id[:8]})")
    
    # Search users
    users = user_service.search(enterprise_id="demo_ent")
    console.print(f"  Users in demo_ent: [cyan]{len(users)}[/cyan]")
    user_service.close()
    
    # ---- Ticket Service ----
    console.print("\n[bold]2. Ticket Service[/bold]")
    ticket_service = PostgresTicketService(**config)
    ticket_service.init_db()
    
    ticket = ticket_service.create(
        title="无法登录系统",
        description="用户反映登录时提示密码错误",
        customer_id=user.id,
        customer_name=user.display_name,
        category=TicketCategory.TECHNICAL,
        priority=TicketPriority.P2_HIGH,
        enterprise_id="demo_ent"
    )
    console.print(f"  Created ticket: [green]{ticket.title}[/green] ({ticket.id[:8]})")
    
    # Add message
    msg = ticket_service.add_message(
        ticket_id=ticket.id,
        sender_id=user.id,
        sender_name=user.display_name,
        content="我尝试重置密码但没收到邮件"
    )
    console.print(f"  Added message to ticket")
    
    # Update status
    ticket_service.update_status(ticket.id, TicketStatus.IN_PROGRESS)
    console.print(f"  Status updated to: [yellow]{TicketStatus.IN_PROGRESS.value}[/yellow]")
    
    # Get stats
    stats = ticket_service.get_statistics(enterprise_id="demo_ent")
    console.print(f"  Total tickets: [cyan]{stats['total']}[/cyan]")
    ticket_service.close()
    
    # ---- Skill Service ----
    console.print("\n[bold]3. Skill Service[/bold]")
    skill_service = PostgresSkillService(**config)
    skill_service.init_db()
    
    skill = skill_service.create(
        name="hotel-booking",
        display_name="酒店预订助手",
        description="帮助用户预订酒店房间",
        category=SkillCategory.CUSTOMER_SERVICE,
        business_type="hotel",
        enterprise_id="demo_ent",
        status=SkillStatus.ACTIVE,
        triggers=["酒店", "预订", "房间"],
        capabilities=["查询房型", "预订房间"]
    )
    console.print(f"  Created skill: [green]{skill.display_name}[/green] ({skill.id[:8]})")
    
    # Search by trigger
    matched = skill_service.search_by_trigger("我想预订酒店", enterprise_id="demo_ent")
    console.print(f"  Skills matching '预订酒店': [cyan]{len(matched)}[/cyan]")
    
    # Record invocation
    inv = skill_service.record_invocation(
        skill_id=skill.id,
        skill_name=skill.name,
        user_id=user.id,
        input_summary="用户询问酒店预订",
        duration_ms=150,
        enterprise_id="demo_ent"
    )
    console.print(f"  Recorded invocation: [green]{inv.id[:8]}[/green]")
    
    # Get stats
    skill_stats = skill_service.get_statistics(enterprise_id="demo_ent")
    console.print(f"  Total skills: [cyan]{skill_stats['total_skills']}[/cyan]")
    console.print(f"  Total invocations: [cyan]{skill_stats['total_invocations']}[/cyan]")
    skill_service.close()
    
    console.print("\n[green]✓ Demo completed![/green]")


@data_app.command("user")
def data_user(
    action: str = typer.Argument(..., help="Action: create, list, get, update, delete"),
    username: str = typer.Option("", "--username", help="Username"),
    email: str = typer.Option("", "--email", help="Email"),
    enterprise_id: str = typer.Option("", "--enterprise", help="Enterprise ID"),
    role: str = typer.Option("customer", "--role", help="Role: admin, manager, agent, customer"),
    display_name: str = typer.Option("", "--name", help="Display name"),
):
    """Manage users."""
    from nanobot.services.postgres_user import PostgresUserService, UserRole
    
    config = _get_db_config()
    service = PostgresUserService(**config)
    
    try:
        if action == "list":
            users = service.search(enterprise_id=enterprise_id or None)
            table = Table(title="Users")
            table.add_column("ID", style="cyan")
            table.add_column("Username", style="green")
            table.add_column("Email")
            table.add_column("Role")
            table.add_column("Enterprise")
            for u in users:
                table.add_row(u.id[:8], u.username, u.email or "", u.role.value, u.enterprise_id or "")
            console.print(table)
        
        elif action == "create":
            if not username:
                console.print("[red]--username required[/red]")
                raise typer.Exit(1)
            user = service.create(
                username=username,
                email=email or None,
                enterprise_id=enterprise_id or None,
                role=UserRole(role),
                display_name=display_name or username
            )
            console.print(f"[green]Created user: {user.id}[/green]")
        
        elif action == "get":
            if not username and not enterprise_id:
                console.print("[red]--username or --enterprise required[/red]")
                raise typer.Exit(1)
            user = service.get_by_username(username, enterprise_id=enterprise_id or None)
            if user:
                console.print(f"ID: {user.id}")
                console.print(f"Username: {user.username}")
                console.print(f"Email: {user.email}")
                console.print(f"Role: {user.role.value}")
                console.print(f"Enterprise: {user.enterprise_id}")
                console.print(f"Created: {user.created_at}")
            else:
                console.print("[yellow]User not found[/yellow]")
    finally:
        service.close()


@data_app.command("ticket")
def data_ticket(
    action: str = typer.Argument(..., help="Action: create, list, get, update, status"),
    title: str = typer.Option("", "--title", help="Ticket title"),
    customer_id: str = typer.Option("", "--customer", help="Customer ID"),
    enterprise_id: str = typer.Option("", "--enterprise", help="Enterprise ID"),
    status: str = typer.Option("", "--status", help="Status: open, pending, in_progress, resolved, closed"),
    category: str = typer.Option("other", "--category", help="Category: technical, billing, product, complaint, suggestion"),
):
    """Manage tickets."""
    from nanobot.services.postgres_ticket import PostgresTicketService, TicketStatus, TicketCategory
    
    config = _get_db_config()
    service = PostgresTicketService(**config)
    
    try:
        if action == "list":
            tickets = service.search(enterprise_id=enterprise_id or None)
            table = Table(title="Tickets")
            table.add_column("ID", style="cyan")
            table.add_column("Title")
            table.add_column("Status", style="yellow")
            table.add_column("Priority")
            table.add_column("Created")
            for t in tickets:
                table.add_row(t.id[:8], t.title[:40], t.status.value, t.priority.value, str(t.created_at)[:10])
            console.print(table)
        
        elif action == "create":
            if not title or not customer_id:
                console.print("[red]--title and --customer required[/red]")
                raise typer.Exit(1)
            ticket = service.create(
                title=title,
                description="",
                customer_id=customer_id,
                customer_name="Customer",
                enterprise_id=enterprise_id or None,
                category=TicketCategory(category)
            )
            console.print(f"[green]Created ticket: {ticket.id}[/green]")
        
        elif action == "status":
            # Update status
            ticket_id = customer_id  # Reuse --customer for ticket ID
            if not ticket_id:
                console.print("[red]--customer (ticket ID) required[/red]")
                raise typer.Exit(1)
            new_status = TicketStatus(status) if status else None
            if not new_status:
                console.print("[red]--status required[/red]")
                raise typer.Exit(1)
            ticket = service.update_status(ticket_id, new_status)
            console.print(f"[green]Updated ticket status to: {ticket.status.value}[/green]")
        
        elif action == "stats":
            stats = service.get_statistics(enterprise_id=enterprise_id or None)
            console.print(f"Total: {stats['total']}")
            console.print(f"By status: {stats['by_status']}")
            console.print(f"By priority: {stats['by_priority']}")
    finally:
        service.close()


@data_app.command("skill")
def data_skill(
    action: str = typer.Argument(..., help="Action: create, list, search, find, stats"),
    name: str = typer.Option("", "--name", help="Skill name"),
    display_name: str = typer.Option("", "--display", help="Display name"),
    category: str = typer.Option("", "--category", help="Category: customer_service, sales, technical, faq, etc."),
    business_type: str = typer.Option("", "--business", help="Business type: hotel, retail, fintech, etc."),
    enterprise_id: str = typer.Option("", "--enterprise", help="Enterprise ID"),
    trigger: str = typer.Option("", "--trigger", help="Trigger keyword"),
):
    """Manage skills."""
    from nanobot.services.postgres_skill import PostgresSkillService, SkillCategory, SkillStatus
    
    config = _get_db_config()
    service = PostgresSkillService(**config)
    
    try:
        if action == "list":
            skills = service.search(enterprise_id=enterprise_id or None)
            table = Table(title="Skills")
            table.add_column("ID", style="cyan")
            table.add_column("Name")
            table.add_column("Display Name")
            table.add_column("Category")
            table.add_column("Status")
            for s in skills:
                table.add_row(s.id[:8], s.name, s.display_name, s.category.value, s.status.value)
            console.print(table)
        
        elif action == "create":
            if not name or not display_name:
                console.print("[red]--name and --display required[/red]")
                raise typer.Exit(1)
            skill = service.create(
                name=name,
                display_name=display_name,
                description="",
                category=SkillCategory(category) if category else SkillCategory.OTHER,
                business_type=business_type or None,
                enterprise_id=enterprise_id or None,
                triggers=[trigger] if trigger else [],
                capabilities=[]
            )
            console.print(f"[green]Created skill: {skill.id}[/green]")
        
        elif action == "search":
            if not trigger:
                console.print("[red]--trigger required[/red]")
                raise typer.Exit(1)
            skills = service.search_by_trigger(trigger, enterprise_id=enterprise_id or None)
            console.print(f"Found {len(skills)} skills matching '{trigger}':")
            for s in skills:
                console.print(f"  - {s.display_name} ({s.name}) - {s.category.value}")
        
        elif action == "stats":
            stats = service.get_statistics(enterprise_id=enterprise_id or None)
            console.print(f"Total skills: {stats['total_skills']}")
            console.print(f"Total invocations: {stats['total_invocations']}")
            console.print(f"Success rate: {stats['success_rate']}%")
            if stats['top_skills']:
                console.print("\nTop skills:")
                for s in stats['top_skills'][:5]:
                    console.print(f"  - {s['display_name']}: {s['invocations']} invocations")
    finally:
        service.close()


if __name__ == "__main__":
    app()
