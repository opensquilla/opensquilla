"""OpenSquilla CLI — Typer app with sub-commands."""

from __future__ import annotations

import typer

from opensquilla.env import load_env, warn_if_proxy_ignored

# Populate os.environ from .env files before any submodule import reads keys.
# Precedence: os.environ > $CWD/.env > $CWD/.env.test > ~/.opensquilla/.env.
load_env()
warn_if_proxy_ignored()

from opensquilla.cli.agent_cmd import run_agent_command  # noqa: E402
from opensquilla.cli.agents_cmd import agents_app  # noqa: E402
from opensquilla.cli.channels_cmd import channels_app  # noqa: E402
from opensquilla.cli.config_cmd import app as config_app  # noqa: E402
from opensquilla.cli.cost_cmd import app as cost_app  # noqa: E402
from opensquilla.cli.cron_cmd import cron_app  # noqa: E402
from opensquilla.cli.diagnostics_cmd import diagnostics_app  # noqa: E402
from opensquilla.cli.dist_cmd import app as dist_app  # noqa: E402
from opensquilla.cli.init_cmd import init_command  # noqa: E402
from opensquilla.cli.memory_flush_cmd import memory_flush_session_cmd  # noqa: E402
from opensquilla.cli.models_cmd import app as models_app  # noqa: E402
from opensquilla.cli.onboard_cmd import configure_command, onboard_command  # noqa: E402
from opensquilla.cli.providers_cmd import providers_app  # noqa: E402
from opensquilla.cli.replay import replay_app  # noqa: E402
from opensquilla.cli.search_cmd import search_app  # noqa: E402
from opensquilla.cli.sessions_cmd import app as sessions_app  # noqa: E402
from opensquilla.cli.skills_cmd import skills_app  # noqa: E402

app = typer.Typer(
    name="opensquilla",
    help="OpenSquilla - Python agent runtime with multi-channel support.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

# ── Sub-apps ─────────────────────────────────────────────────────────────────

app.add_typer(channels_app, name="channels")
app.add_typer(agents_app, name="agents")
app.add_typer(config_app, name="config")
app.add_typer(cost_app, name="cost")
app.add_typer(diagnostics_app, name="diagnostics")
app.add_typer(cron_app, name="cron")
app.add_typer(dist_app, name="dist")
app.add_typer(models_app, name="models")
app.add_typer(providers_app, name="providers")
app.add_typer(search_app, name="search")
app.add_typer(sessions_app, name="sessions")
app.add_typer(skills_app, name="skills")

app.command("init")(init_command)
app.command("onboard")(onboard_command)
app.command("configure")(configure_command)


# ── memory sub-app ────────────────────────────────────────────────────────────

memory_app = typer.Typer(help="Memory subsystem commands.")
app.add_typer(memory_app, name="memory")


def _build_cli_dream(agent: str, *, force: bool = False, need_provider: bool = True):
    """Assemble a Dream instance for CLI runs.

    Uses the local ``.opensquilla`` workspace root and the project's default
    provider factory. Unit tests monkeypatch this function to inject a
    mock Dream without touching provider wiring. When ``need_provider``
    is False (e.g. ``--status`` / ``--reset-cursor``), skip provider
    construction so the command works offline.
    """
    import os
    from pathlib import Path

    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.memory.dream_factory import build_dream_factory

    gw = GatewayConfig.load(os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))

    def _workspace_for_agent(agent_id: str) -> Path:
        return Path.cwd() / ".opensquilla" / "agents" / agent_id

    dream = build_dream_factory(
        config=gw,
        provider_selector=None,
        tool_registry=None,
        turn_runner=None,
        workspace_for_agent=_workspace_for_agent,
        need_provider=need_provider,
    )
    dream_obj = dream(agent)
    if force:
        dream_obj.cursor.reset()
    return dream_obj


@memory_app.command("status")
def memory_status_cmd(
    agent_id: str = typer.Option("main", "--agent", help="Agent id (default: main)"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show read-only memory backend status from the running gateway."""

    from rich.table import Table

    from opensquilla.cli.gateway_rpc import run_gateway_sync
    from opensquilla.cli.output import print_json
    from opensquilla.cli.ui import console

    async def _run(client):
        return await client.call("doctor.memory.status", {"agentId": agent_id})

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return

    table = Table(title=f"Memory status — agent={agent_id}", show_header=True)
    table.add_column("Backend")
    table.add_column("Status")
    table.add_column("Entries", justify="right")
    table.add_column("Size bytes", justify="right")
    table.add_column("Error")
    table.add_row(
        str(payload.get("backend") or ""),
        str(payload.get("status") or ""),
        "" if payload.get("entryCount") is None else str(payload.get("entryCount")),
        "" if payload.get("sizeBytes") is None else str(payload.get("sizeBytes")),
        str(payload.get("error") or ""),
    )
    console.print(table)


@memory_app.command("list")
def memory_list_cmd(
    agent_id: str = typer.Option("main", "--agent", help="Agent id (default: main)"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List durable memory source files from the running gateway."""

    from rich.table import Table

    from opensquilla.cli.gateway_rpc import run_gateway_sync
    from opensquilla.cli.output import print_json
    from opensquilla.cli.ui import console

    async def _run(client):
        return await client.call("memory.list", {"agentId": agent_id})

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return

    table = Table(title=f"Memory sources - agent={agent_id}", show_header=True)
    table.add_column("Path")
    table.add_column("Lines", justify="right")
    table.add_column("Size bytes", justify="right")
    table.add_column("Modified")
    for row in payload.get("files", []):
        table.add_row(
            str(row.get("path") or ""),
            "" if row.get("lineCount") is None else str(row.get("lineCount")),
            "" if row.get("sizeBytes") is None else str(row.get("sizeBytes")),
            str(row.get("modifiedAt") or ""),
        )
    console.print(table)


@memory_app.command("search")
def memory_search_cmd(
    query: str = typer.Argument(..., help="Search query"),
    agent_id: str = typer.Option("main", "--agent", help="Agent id (default: main)"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Search durable memory from the running gateway."""

    from rich.table import Table

    from opensquilla.cli.gateway_rpc import run_gateway_sync
    from opensquilla.cli.output import print_json
    from opensquilla.cli.ui import console

    async def _run(client):
        return await client.call(
            "memory.search",
            {"query": query, "agentId": agent_id, "limit": limit},
        )

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return

    table = Table(title=f"Memory search - agent={agent_id}", show_header=True)
    table.add_column("Path")
    table.add_column("Lines")
    table.add_column("Score", justify="right")
    table.add_column("Snippet")
    for row in payload.get("results", []):
        table.add_row(
            str(row.get("path") or ""),
            f"{row.get('startLine', '')}-{row.get('endLine', '')}",
            f"{float(row.get('score') or 0.0):.3f}",
            str(row.get("snippet") or "")[:120],
        )
    console.print(table)


@memory_app.command("show")
def memory_show_cmd(
    path: str = typer.Argument(..., help="Memory source path"),
    agent_id: str = typer.Option("main", "--agent", help="Agent id (default: main)"),
    from_line: int | None = typer.Option(None, "--from-line", help="Start line, 1-indexed"),
    lines: int | None = typer.Option(None, "--lines", help="Number of lines to return"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show one durable memory source from the running gateway."""

    from opensquilla.cli.gateway_rpc import run_gateway_sync
    from opensquilla.cli.output import print_json
    from opensquilla.cli.ui import console

    async def _run(client):
        params: dict[str, object] = {"path": path, "agentId": agent_id}
        if from_line is not None:
            params["fromLine"] = from_line
        if lines is not None:
            params["lines"] = lines
        return await client.call("memory.show", params)

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return
    console.print(str(payload.get("content") or ""))
    if payload.get("truncated"):
        console.print("[dim]... truncated[/dim]")


@memory_app.command("dream")
def memory_dream_cmd(
    agent: str = typer.Option("main", "--agent", "-a", help="Agent ID"),
    force: bool = typer.Option(False, "--force", help="Reset cursor and process all files"),
    status: bool = typer.Option(False, "--status", help="Show cursor + pending file count, no run"),
    reset_cursor: bool = typer.Option(False, "--reset-cursor", help="Clear cursor file, no run"),
) -> None:
    """Run Dream consolidation for an agent."""
    import asyncio

    need_provider = not (status or reset_cursor)
    dream = _build_cli_dream(agent, force=force, need_provider=need_provider)
    if reset_cursor:
        dream.cursor.reset()
        typer.echo(f"reset cursor for agent={agent}")
        return
    if status:
        cursor = dream.cursor.load()
        pending = len(dream._candidate_files())
        typer.echo(
            f"agent={agent} cursor={cursor} pending={pending} "
            f"memory_md_exists={dream.memory_md.exists()}"
        )
        return
    result = asyncio.run(dream.run())
    typer.echo(
        f"dream agent={agent} "
        f"processed={result.files_processed} "
        f"deleted={result.files_deleted} "
        f"phase1={result.phase1_status} "
        f"phase2={result.phase2_status}"
    )
    if result.error:
        typer.echo(f"error: {result.error}", err=True)
        raise typer.Exit(code=1)


memory_app.command("flush-session")(memory_flush_session_cmd)


# ── gateway sub-app ───────────────────────────────────────────────────────────

gateway_app = typer.Typer(help="Gateway server commands.")
app.add_typer(gateway_app, name="gateway")


@gateway_app.command("run")
def gateway_run(
    port: int = typer.Option(18790, "--port", "-p", help="Port to bind"),
    bind: str = typer.Option("127.0.0.1", "--bind", "-b", help="Host to bind"),
    listen: str = typer.Option(
        "",
        "--listen",
        help="Host to bind (alias of --bind; wins over --bind when both supplied)",
    ),
    debug: bool = typer.Option(False, "--debug", help="Enable debug mode"),
) -> None:
    """Start the ASGI gateway server.

    Precedence for the bind address: --listen > --bind > OPENSQUILLA_LISTEN >
    OPENSQUILLA_GATEWAY_HOST > default (127.0.0.1). Binding to 0.0.0.0 or :: is
    opt-in only — the gateway's default auth assumes loopback scope.
    """
    from opensquilla.cli.gateway_cmd import run_gateway

    run_gateway(port=port, bind=bind, listen=listen, debug=debug)


@gateway_app.command("start")
def gateway_start(
    port: int = typer.Option(18790, "--port", "-p", help="Port to bind"),
    bind: str = typer.Option("127.0.0.1", "--bind", "-b", help="Host to bind"),
    listen: str = typer.Option("", "--listen", help="Host to bind (wins over --bind)"),
    health_timeout: float = typer.Option(60.0, "--timeout", help="Readiness wait timeout"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Start the gateway in the background and wait for readiness."""
    from opensquilla.cli.gateway_cmd import start_gateway

    start_gateway(
        port=port,
        bind=bind,
        listen=listen,
        health_timeout=health_timeout,
        json_output=json_output,
    )


@gateway_app.command("status")
def gateway_status(
    port: int = typer.Option(18790, "--port", "-p", help="Port to inspect"),
    bind: str = typer.Option("127.0.0.1", "--bind", "-b", help="Host to inspect"),
    listen: str = typer.Option("", "--listen", help="Host to inspect (wins over --bind)"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Inspect the managed gateway process without mutating state."""
    from opensquilla.cli.gateway_cmd import status_gateway

    status_gateway(port=port, bind=bind, listen=listen, json_output=json_output)


@gateway_app.command("stop")
def gateway_stop(
    port: int = typer.Option(18790, "--port", "-p", help="Port to stop"),
    bind: str = typer.Option("127.0.0.1", "--bind", "-b", help="Host to stop"),
    listen: str = typer.Option("", "--listen", help="Host to stop (wins over --bind)"),
    shutdown_timeout: float = typer.Option(10.0, "--timeout", help="Shutdown wait timeout"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Stop the recorded gateway process."""
    from opensquilla.cli.gateway_cmd import stop_gateway

    stop_gateway(
        port=port,
        bind=bind,
        listen=listen,
        shutdown_timeout=shutdown_timeout,
        json_output=json_output,
    )


@gateway_app.command("restart")
def gateway_restart(
    port: int = typer.Option(18790, "--port", "-p", help="Port to restart"),
    bind: str = typer.Option("127.0.0.1", "--bind", "-b", help="Host to restart"),
    listen: str = typer.Option("", "--listen", help="Host to restart (wins over --bind)"),
    health_timeout: float = typer.Option(60.0, "--timeout", help="Readiness wait timeout"),
    shutdown_timeout: float = typer.Option(
        10.0, "--shutdown-timeout", help="Shutdown wait timeout"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Restart the recorded gateway process."""
    from opensquilla.cli.gateway_cmd import restart_gateway

    restart_gateway(
        port=port,
        bind=bind,
        listen=listen,
        health_timeout=health_timeout,
        shutdown_timeout=shutdown_timeout,
        json_output=json_output,
    )


# ── replay sub-app ────────────────────────────────────────────────────────────

app.add_typer(replay_app, name="replay")


# ── top-level commands ────────────────────────────────────────────────────────


@app.command("agent")
def agent(
    message: str = typer.Option(..., "--message", "-m", help="Message to send"),
    agent_id: str = typer.Option("main", "--agent", help="Agent identifier"),
    session_id: str = typer.Option("", "--session-id", help="Session key/id to use"),
    model: str = typer.Option("", "--model", help="Model override"),
    workspace: str = typer.Option("", "--workspace", help="Workspace root for this run"),
    workspace_strict: bool | None = typer.Option(
        None,
        "--workspace-strict/--no-workspace-strict",
        help="Restrict read-side file tools to --workspace",
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", "-T", help="Total agent timeout in seconds (0=unlimited)"
    ),
    max_iterations: int | None = typer.Option(
        None,
        "--max-iterations",
        min=1,
        help="Maximum agent model/tool loop iterations",
    ),
    thinking: str = typer.Option(
        "",
        "--thinking",
        help="Thinking level override: off|minimal|low|medium|high|xhigh|adaptive",
    ),
    transcript_path: str = typer.Option(
        "", "--transcript-path", help="Write benchmark-compatible JSONL transcript"
    ),
    usage_path: str = typer.Option("", "--usage-path", help="Write usage JSON to this file"),
    session_db_path: str = typer.Option(
        ":memory:",
        "--session-db-path",
        help="Persistent session SQLite path for cross-invocation replay",
    ),
    no_memory_capture: bool = typer.Option(
        False,
        "--no-memory-capture",
        help="Do not write this invocation to durable searchable memory",
    ),
    file_paths: list[str] = typer.Option(
        [],
        "--file",
        "-f",
        help="Attach a local file; repeat for multiple files",
    ),
    unattended: bool = typer.Option(
        True,
        "--unattended/--interactive",
        help=(
            "Run without a live approval surface. Unattended is the default for "
            "single-shot automation."
        ),
    ),
    permissions: str | None = typer.Option(
        None,
        "--permissions",
        help=(
            "Permission profile for single-shot runs: restricted, bypass, or full. "
            "Defaults to OPENSQUILLA_AGENT_PERMISSIONS or restricted."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Run a single agent turn for automation."""
    run_agent_command(
        message=message,
        agent_id=agent_id,
        session_id=session_id,
        model=model,
        workspace=workspace,
        workspace_strict=workspace_strict,
        thinking=thinking,
        timeout=timeout,
        max_iterations=max_iterations,
        transcript_path=transcript_path,
        usage_path=usage_path,
        session_db_path=session_db_path,
        no_memory_capture=no_memory_capture,
        file_paths=file_paths,
        unattended=unattended,
        permissions=permissions,
        json_output=json_output,
    )


@app.command("chat")
def chat(
    model: str = typer.Option("", "--model", "-m", help="Model override"),
    session_id: str = typer.Option("", "--session", "-s", help="Resume session"),
    standalone: bool = typer.Option(False, "--standalone", help="Direct Agent without gateway"),
    workspace: str = typer.Option("", "--workspace", help="Workspace root for standalone tools"),
    workspace_strict: bool | None = typer.Option(
        None,
        "--workspace-strict/--no-workspace-strict",
        help="Restrict read-side file tools to --workspace in standalone mode",
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", "-T", help="Total agent timeout in seconds (0=unlimited)"
    ),
) -> None:
    """Start interactive chat mode."""
    from opensquilla.cli.chat_cmd import run_chat

    run_chat(
        model=model,
        session_id=session_id,
        standalone=standalone,
        workspace=workspace,
        workspace_strict=workspace_strict,
        timeout=timeout,
    )


@app.command("reset")
def reset_cmd(
    key: str = typer.Option(..., "--key", help="Session key to reset."),
    gateway_url: str = typer.Option(
        "http://localhost:18790", "--gateway", envvar="OPENSQUILLA_GATEWAY_URL"
    ),
) -> None:
    """Reset a session, flushing its memory synchronously.

    Exit codes: 0 on success (including raw-dump fallback),
    1 when flush + raw-dump both fail (session preserved).
    """
    import asyncio

    from opensquilla.cli.gateway_client import GatewayClient, GatewayRPCError
    from opensquilla.cli.url_utils import normalize_gateway_url

    async def _go():
        client = GatewayClient()
        try:
            await client.connect(normalize_gateway_url(gateway_url))
            return await client.reset_session(key)
        finally:
            await client.close()

    try:
        result = asyncio.run(_go())
    except GatewayRPCError as exc:
        data = exc.data or {}
        receipt = data.get("flush_receipt", {}) or {}
        typer.secho(f"\u2717 Reset aborted: {exc.message}", fg=typer.colors.RED)
        typer.echo(f"  Session preserved: {data.get('session_id', '?')}")
        if receipt.get("error"):
            typer.echo(f"  Cause: {receipt['error']}")
        raise typer.Exit(1)

    payload = result
    receipt = payload.get("flush_receipt") or {}
    mode = receipt.get("mode", "?")
    typer.secho(
        f"\u2713 Session reset ({payload.get('previous_session_id', '?')} \u2192 "
        f"{payload.get('session_id', '?')}).",
        fg=typer.colors.GREEN,
    )
    if mode == "llm":
        dur = receipt.get("duration_ms", 0) / 1000
        typer.echo(f"  Flush mode: llm ({dur:.1f}s)")
        for p in receipt.get("flushed_paths") or []:
            typer.echo(f"  Saved to: {p}")
    elif mode == "raw":
        reason = receipt.get("raw_reason", "unknown")
        dur = receipt.get("duration_ms", 0) / 1000
        typer.echo(f"  Flush mode: raw (reason: {reason}, after {dur:.1f}s)")
        for p in receipt.get("flushed_paths") or []:
            typer.echo(f"  Saved to: {p} (raw transcript dump)")
    elif mode == "skipped":
        typer.echo("  Flush mode: skipped (empty transcript)")
    else:
        typer.echo(f"  Flush mode: {mode}")

if __name__ == "__main__":
    app()
