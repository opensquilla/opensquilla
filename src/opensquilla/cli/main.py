"""OpenSquilla CLI — Typer app with sub-commands."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from opensquilla.env import warn_if_proxy_ignored
from opensquilla.paths import default_opensquilla_home, is_valid_profile_name

# `load_env()` is NOT called at module import time on purpose: the active
# profile (CLI --profile + OPENSQUILLA_PROFILE env) is only known after
# Typer parses the global callback, so loading here would always pick the
# legacy ~/.opensquilla/.env regardless of which profile the user picked.
# The callback below resolves the active profile, calls load_env(home=...),
# then re-invokes warn_if_proxy_ignored() so the proxy hint is logged
# against the post-load env. Subcommand modules are imported below;
# they don't read env at import time, so the deferred load is safe.

from opensquilla.cli.agent_cmd import run_agent_command  # noqa: E402
from opensquilla.cli.agents_cmd import agents_app  # noqa: E402
from opensquilla.cli.channels_cmd import channels_app  # noqa: E402
from opensquilla.cli.config_cmd import app as config_app  # noqa: E402
from opensquilla.cli.cost_cmd import app as cost_app  # noqa: E402
from opensquilla.cli.cron_cmd import cron_app  # noqa: E402
from opensquilla.cli.diagnostics_cmd import diagnostics_app  # noqa: E402
from opensquilla.cli.dist_cmd import app as dist_app  # noqa: E402
from opensquilla.cli.doctor_cmd import doctor_command  # noqa: E402
from opensquilla.cli.init_cmd import init_command  # noqa: E402
from opensquilla.cli.mcp_server_cmd import app as mcp_server_app  # noqa: E402
from opensquilla.cli.memory_flush_cmd import memory_flush_session_cmd  # noqa: E402
from opensquilla.cli.migrate_cmd import migrate_app  # noqa: E402
from opensquilla.cli.models_cmd import app as models_app  # noqa: E402
from opensquilla.cli.onboard_cmd import configure_command, onboard_app  # noqa: E402
from opensquilla.cli.providers_cmd import providers_app  # noqa: E402
from opensquilla.cli.replay import replay_app  # noqa: E402
from opensquilla.cli.sandbox_cmd import sandbox_app  # noqa: E402
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
app.add_typer(mcp_server_app, name="mcp-server")
app.add_typer(migrate_app, name="migrate")
app.add_typer(models_app, name="models")
app.add_typer(providers_app, name="providers")
app.add_typer(sandbox_app, name="sandbox")
app.add_typer(search_app, name="search")
app.add_typer(sessions_app, name="sessions")
app.add_typer(skills_app, name="skills")

app.command("init")(init_command)
app.command("doctor")(doctor_command)
app.add_typer(onboard_app, name="onboard")
app.command("configure")(configure_command)


# ── Global options ────────────────────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def _profile_callback(
    ctx: typer.Context,
    profile: str | None = typer.Option(
        None,
        "--profile",
        envvar="OPENSQUILLA_PROFILE",
        help=(
            "Profile name for multi-instance mode. Resolved to "
            "$OPENSQUILLA_HOME/<profile>/ (default: "
            "~/.opensquilla/profiles/). When set, isolates state/logs/config "
            "from other instances sharing the same host. Ignored if "
            "OPENSQUILLA_STATE_DIR is set (full override)."
        ),
    ),
) -> None:
    """OpenSquilla global options."""
    # Preserve `no_args_is_help` — only act when a subcommand is invoked.
    if ctx.invoked_subcommand is None:
        return
    name = (profile or "").strip()
    if name:
        if not is_valid_profile_name(name):
            raise typer.BadParameter(
                f"Invalid profile name {name!r}; must match "
                f"^[a-z0-9][a-z0-9_-]{{0,63}}$."
            )
        # Export so subprocesses (e.g. `gateway start` spawning `gateway run`)
        # inherit the active profile and so any code path that reads
        # `os.environ["OPENSQUILLA_PROFILE"]` directly sees the CLI choice.
        os.environ["OPENSQUILLA_PROFILE"] = name

    # Now that the active profile is known, resolve the home and load
    # .env from THAT home. Loading before this point would have picked
    # the legacy ~/.opensquilla/.env regardless of --profile, which
    # leaked keys across profile boundaries.
    from opensquilla.env import load_env

    home = default_opensquilla_home()
    load_env(home=home)
    warn_if_proxy_ignored()


# ── memory sub-app ────────────────────────────────────────────────────────────

memory_app = typer.Typer(help="Memory subsystem commands.")
app.add_typer(memory_app, name="memory")
raw_fallbacks_app = typer.Typer(help="Raw fallback receipt commands.")
memory_app.add_typer(raw_fallbacks_app, name="raw-fallbacks")
repair_app = typer.Typer(help="Compaction memory repair commands.")
memory_app.add_typer(repair_app, name="repair")


def _build_cli_dream(agent: str, *, force: bool = False, need_provider: bool = True):
    """Assemble a Dream instance for CLI runs.

    Uses the same configured agent workspace resolver as gateway Dream runs.
    Unit tests monkeypatch this function to inject a mock Dream without
    touching provider wiring. When ``need_provider`` is False (e.g. ``--status``
    / ``--reset-cursor``), skip provider construction so the command works
    offline.
    """
    import os

    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.memory.dream_factory import build_dream_factory

    gw = GatewayConfig.load(os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))

    dream = build_dream_factory(
        config=gw,
        turn_runner=None,
        need_provider=need_provider,
    )
    dream_obj = dream(agent)
    if force:
        dream_obj.cursor.reset()
    return dream_obj


@memory_app.command("status")
def memory_status_cmd(
    agent_id: str = typer.Option("main", "--agent", help="Agent id (default: main)"),
    deep: bool = typer.Option(False, "--deep", help="Include detailed retrieval health"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    config_path: Path | None = typer.Option(None, "--config", help="Override config path."),
) -> None:
    """Show read-only memory backend status from the running gateway."""

    from rich.table import Table

    from opensquilla.cli.gateway_rpc import run_gateway_sync
    from opensquilla.cli.output import print_json
    from opensquilla.cli.ui import console

    async def _run(client):
        params: dict[str, object] = {"agentId": agent_id}
        if deep:
            params["deep"] = True
        return await client.call("doctor.memory.status", params)

    payload = run_gateway_sync(_run, json_output=json_output, config_path=config_path)
    if json_output:
        print_json(payload)
        return

    table = Table(title=f"Memory status — agent={agent_id}", show_header=True)
    table.add_column("Backend")
    table.add_column("Status")
    table.add_column("Entries", justify="right")
    table.add_column("Size bytes", justify="right")
    table.add_column("Sources")
    table.add_column("Error")
    source_counts = payload.get("sourceCounts") or {}
    source_summary = ", ".join(
        f"{source} {counts.get('files', 0)} files/{counts.get('chunks', 0)} chunks"
        for source, counts in sorted(source_counts.items())
        if isinstance(counts, dict)
    )
    table.add_row(
        str(payload.get("backend") or ""),
        str(payload.get("status") or ""),
        "" if payload.get("entryCount") is None else str(payload.get("entryCount")),
        "" if payload.get("sizeBytes") is None else str(payload.get("sizeBytes")),
        source_summary,
        str(payload.get("error") or ""),
    )
    console.print(table)


@memory_app.command("index")
def memory_index_cmd(
    agent_id: str = typer.Option("main", "--agent", help="Agent id (default: main)"),
    force: bool = typer.Option(False, "--force", help="Rebuild index rows and rescan sources"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Sync or force-rebuild the memory search index through the gateway."""

    from opensquilla.cli.gateway_rpc import run_gateway_sync
    from opensquilla.cli.output import print_json
    from opensquilla.cli.ui import console

    async def _run(client):
        return await client.call("memory.index", {"agentId": agent_id, "force": force})

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return
    console.print(
        f"memory index agent={payload.get('agentId', agent_id)} "
        f"force={bool(payload.get('force'))}"
    )


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
    source: str = typer.Option(
        "memory",
        "--source",
        help="Search source: memory, sessions, or all",
    ),
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
            {"query": query, "agentId": agent_id, "limit": limit, "source": source},
        )

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return

    table = Table(title=f"Memory search - agent={agent_id}", show_header=True)
    table.add_column("Source")
    table.add_column("Path")
    table.add_column("Lines")
    table.add_column("Score", justify="right")
    table.add_column("Snippet")
    for row in payload.get("results", []):
        table.add_row(
            str(row.get("source") or "memory"),
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


@raw_fallbacks_app.command("list")
def memory_raw_fallbacks_list_cmd(
    agent_id: str = typer.Option("main", "--agent", help="Agent id (default: main)"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List raw fallback receipts from the running gateway."""

    from rich.table import Table

    from opensquilla.cli.gateway_rpc import run_gateway_sync
    from opensquilla.cli.output import print_json
    from opensquilla.cli.ui import console

    async def _run(client):
        return await client.call("memory.raw_fallbacks.list", {"agentId": agent_id})

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return

    table = Table(title=f"Raw memory fallbacks - agent={agent_id}", show_header=True)
    table.add_column("Path")
    table.add_column("Size bytes", justify="right")
    table.add_column("Reason")
    table.add_column("Modified")
    for row in payload.get("files", []):
        table.add_row(
            str(row.get("path") or ""),
            "" if row.get("sizeBytes") is None else str(row.get("sizeBytes")),
            str(row.get("reason") or ""),
            str(row.get("modifiedAt") or ""),
        )
    console.print(table)


@raw_fallbacks_app.command("show")
def memory_raw_fallbacks_show_cmd(
    path: str = typer.Argument(..., help="Raw fallback path"),
    agent_id: str = typer.Option("main", "--agent", help="Agent id (default: main)"),
    from_line: int | None = typer.Option(None, "--from-line", help="Start line, 1-indexed"),
    lines: int | None = typer.Option(None, "--lines", help="Number of lines to return"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show one raw fallback receipt from the running gateway."""

    from opensquilla.cli.gateway_rpc import run_gateway_sync
    from opensquilla.cli.output import print_json
    from opensquilla.cli.ui import console

    async def _run(client):
        params: dict[str, object] = {"path": path, "agentId": agent_id}
        if from_line is not None:
            params["fromLine"] = from_line
        if lines is not None:
            params["lines"] = lines
        return await client.call("memory.raw_fallbacks.show", params)

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return
    console.print(str(payload.get("content") or ""))
    if payload.get("truncated"):
        console.print("[dim]... truncated[/dim]")


@repair_app.command("list")
def memory_repair_list_cmd(
    agent_id: str = typer.Option("main", "--agent", help="Agent id (default: main)"),
    limit: int = typer.Option(50, "--limit", min=1, help="Maximum pending repairs"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    config_path: Path | None = typer.Option(None, "--config", help="Override config path."),
) -> None:
    """List degraded compaction records pending repair."""

    from rich.table import Table

    from opensquilla.cli.gateway_rpc import run_gateway_sync
    from opensquilla.cli.output import print_json
    from opensquilla.cli.ui import console

    async def _run(client):
        return await client.call(
            "memory.repair.list",
            {"agentId": agent_id, "limit": limit},
        )

    payload = run_gateway_sync(_run, json_output=json_output, config_path=config_path)
    if json_output:
        print_json(payload)
        return

    table = Table(title=f"Memory repair queue - agent={agent_id}", show_header=True)
    table.add_column("Summary")
    table.add_column("Session")
    table.add_column("Compaction")
    table.add_column("Status")
    table.add_column("Removed", justify="right")
    for row in payload.get("items", []):
        table.add_row(
            str(row.get("summaryId") or ""),
            str(row.get("sessionKey") or ""),
            str(row.get("compactionId") or ""),
            str(row.get("flushReceiptStatus") or ""),
            "" if row.get("removedCount") is None else str(row.get("removedCount")),
        )
    console.print(table)


@repair_app.command("show")
def memory_repair_show_cmd(
    summary_id: int | None = typer.Option(None, "--summary-id", help="Repair summary id"),
    session_key: str = typer.Option("", "--session-key", help="Session key to inspect"),
    compaction_id: str = typer.Option("", "--compaction-id", help="Compaction id to inspect"),
    agent_id: str = typer.Option("main", "--agent", help="Agent id (default: main)"),
    entry_limit: int = typer.Option(
        20,
        "--entry-limit",
        min=1,
        help="Maximum preimage entries",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show archived preimage entries for one degraded compaction."""

    from opensquilla.cli.gateway_rpc import run_gateway_sync
    from opensquilla.cli.output import print_json
    from opensquilla.cli.ui import console

    async def _run(client):
        params: dict[str, object] = {"agentId": agent_id}
        if summary_id is not None:
            params["summaryId"] = summary_id
        if session_key:
            params["sessionKey"] = session_key
        if compaction_id:
            params["compactionId"] = compaction_id
        if entry_limit != 20:
            params["entryLimit"] = entry_limit
        return await client.call("memory.repair.show", params)

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return
    for row in payload.get("entries", []):
        console.print(f"[{row.get('role', '')}] {row.get('content', '')}")


@repair_app.command("run")
def memory_repair_run_cmd(
    summary_id: int | None = typer.Option(None, "--summary-id", help="Repair summary id"),
    session_key: str = typer.Option("", "--session-key", help="Session key to repair"),
    compaction_id: str = typer.Option("", "--compaction-id", help="Compaction id to repair"),
    agent_id: str = typer.Option("main", "--agent", help="Agent id (default: main)"),
    limit: int = typer.Option(50, "--limit", min=1, help="Maximum repairs to run"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    config_path: Path | None = typer.Option(None, "--config", help="Override config path."),
) -> None:
    """Retry extraction from archived compaction preimages."""

    from rich.table import Table

    from opensquilla.cli.gateway_rpc import run_gateway_sync
    from opensquilla.cli.output import print_json
    from opensquilla.cli.ui import console

    async def _run(client):
        params: dict[str, object] = {"agentId": agent_id, "limit": limit}
        if summary_id is not None:
            params["summaryId"] = summary_id
        if session_key:
            params["sessionKey"] = session_key
        if compaction_id:
            params["compactionId"] = compaction_id
        return await client.call("memory.repair.run", params)

    payload = run_gateway_sync(_run, json_output=json_output, config_path=config_path)
    if json_output:
        print_json(payload)
        return

    table = Table(title=f"Memory repair run - agent={agent_id}", show_header=True)
    table.add_column("Session")
    table.add_column("Compaction")
    table.add_column("Status")
    table.add_column("Reason")
    for row in payload.get("results", []):
        table.add_row(
            str(row.get("sessionKey") or ""),
            str(row.get("compactionId") or ""),
            str(row.get("status") or ""),
            str(row.get("reason") or ""),
        )
    console.print(table)


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
        pending = dream.pending_candidate_count()
        typer.echo(
            f"agent={agent} cursor={cursor} pending={pending} "
            f"memory_md_exists={dream.memory_md.exists()}"
        )
        return
    result = asyncio.run(dream.run())
    typer.echo(
        f"dream agent={agent} "
        f"processed={result.files_processed} "
        f"evidence={result.evidence_status} "
        f"apply={result.apply_status}"
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
    port: int | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Port to bind (default: config port, usually 18791)",
    ),
    bind: str | None = typer.Option(
        None,
        "--bind",
        "-b",
        help="Host to bind (default: config host, usually 127.0.0.1)",
    ),
    listen: str = typer.Option(
        "",
        "--listen",
        help="Host to bind (alias of --bind; wins over --bind when both supplied)",
    ),
    debug: bool = typer.Option(False, "--debug", help="Enable debug mode"),
    config_path: str | None = typer.Option(None, "--config", help="Override config path."),
) -> None:
    """Start the ASGI gateway server.

    Precedence for the bind address: --listen > --bind > OPENSQUILLA_LISTEN >
    OPENSQUILLA_GATEWAY_HOST > default (127.0.0.1). Binding to 0.0.0.0 or :: is
    opt-in only — the gateway's default auth assumes loopback scope.
    """
    from opensquilla.cli.gateway_cmd import run_gateway

    run_gateway(
        port=port,
        bind=bind,
        listen=listen,
        debug=debug,
        config_path=config_path,
    )


@gateway_app.command("start")
def gateway_start(
    port: int | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Port to bind (default: config port, usually 18791)",
    ),
    bind: str | None = typer.Option(
        None,
        "--bind",
        "-b",
        help="Host to bind (default: config host, usually 127.0.0.1)",
    ),
    listen: str = typer.Option("", "--listen", help="Host to bind (wins over --bind)"),
    config_path: str | None = typer.Option(None, "--config", help="Override config path."),
    health_timeout: float = typer.Option(60.0, "--timeout", help="Readiness wait timeout"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Start the gateway in the background and wait for readiness."""
    from opensquilla.cli.gateway_cmd import start_gateway

    start_gateway(
        port=port,
        bind=bind,
        listen=listen,
        config_path=config_path,
        health_timeout=health_timeout,
        json_output=json_output,
    )


@gateway_app.command("status")
def gateway_status(
    port: int | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Port to inspect (default: config port, usually 18791)",
    ),
    bind: str | None = typer.Option(
        None,
        "--bind",
        "-b",
        help="Host to inspect (default: config host, usually 127.0.0.1)",
    ),
    listen: str = typer.Option("", "--listen", help="Host to inspect (wins over --bind)"),
    config_path: str | None = typer.Option(None, "--config", help="Override config path."),
    gateway_url: str | None = typer.Option(
        None,
        "--gateway",
        help="Remote gateway URL to inspect instead of local lifecycle state.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Inspect the managed gateway process without mutating state."""
    from opensquilla.cli.gateway_cmd import status_gateway

    status_gateway(
        port=port,
        bind=bind,
        listen=listen,
        config_path=config_path,
        gateway_url=gateway_url,
        json_output=json_output,
    )


@gateway_app.command("stop")
def gateway_stop(
    port: int | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Port to stop (default: config port, usually 18791)",
    ),
    bind: str | None = typer.Option(
        None,
        "--bind",
        "-b",
        help="Host to stop (default: config host, usually 127.0.0.1)",
    ),
    listen: str = typer.Option("", "--listen", help="Host to stop (wins over --bind)"),
    config_path: str | None = typer.Option(None, "--config", help="Override config path."),
    shutdown_timeout: float = typer.Option(10.0, "--timeout", help="Shutdown wait timeout"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Stop the recorded gateway process."""
    from opensquilla.cli.gateway_cmd import stop_gateway

    stop_gateway(
        port=port,
        bind=bind,
        listen=listen,
        config_path=config_path,
        shutdown_timeout=shutdown_timeout,
        json_output=json_output,
    )


@gateway_app.command("restart")
def gateway_restart(
    port: int | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Port to restart (default: config port, usually 18791)",
    ),
    bind: str | None = typer.Option(
        None,
        "--bind",
        "-b",
        help="Host to restart (default: config host, usually 127.0.0.1)",
    ),
    listen: str = typer.Option("", "--listen", help="Host to restart (wins over --bind)"),
    config_path: str | None = typer.Option(None, "--config", help="Override config path."),
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
        config_path=config_path,
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
    workspace_lockdown: bool = typer.Option(
        False,
        "--workspace-lockdown",
        help=(
            "Opt in to automation write containment: writes must stay under "
            "--workspace or --scratch-dir."
        ),
    ),
    scratch_dir: str = typer.Option(
        "",
        "--scratch-dir",
        help="Directory for temporary scripts, logs, debug output, and candidate patches.",
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", "-T", help="Total agent timeout in seconds (0=unlimited)"
    ),
    max_iterations: int | None = typer.Option(
        None,
        "--max-iterations",
        min=0,
        help="Maximum agent model/tool loop iterations (0=unlimited)",
    ),
    iteration_timeout_seconds: float | None = typer.Option(
        None,
        "--iteration-timeout-seconds",
        help="Per-iteration timeout in seconds (one LLM call + its tool executions)",
    ),
    tool_timeout_seconds: float | None = typer.Option(
        None,
        "--tool-timeout-seconds",
        help="Per-tool execution timeout in seconds",
    ),
    request_timeout_seconds: float | None = typer.Option(
        None,
        "--request-timeout-seconds",
        help="Single LLM HTTP/streaming request timeout in seconds",
    ),
    max_provider_retries: int | None = typer.Option(
        None,
        "--max-provider-retries",
        min=0,
        help="Maximum provider-level retries for transient errors",
    ),
    length_capped_continuations: int | None = typer.Option(
        None,
        "--length-capped-continuations",
        min=1,
        help="Maximum automatic continuations after provider output reaches its length limit",
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
    stateless: bool = typer.Option(
        False,
        "--stateless/--no-stateless",
        help="Use clean-room prompt bootstrap; does not change --unattended semantics.",
    ),
    clean_room: bool = typer.Option(
        False,
        "--clean-room",
        help="Alias for --stateless.",
    ),
    stateless_keep_project_rules: bool = typer.Option(
        False,
        "--stateless-keep-project-rules",
        help="With clean-room bootstrap, keep AGENTS.md project rules only.",
    ),
    permissions: str | None = typer.Option(
        None,
        "--permissions",
        help=(
            "Permission profile for single-shot runs: restricted, bypass, or full. "
            "Defaults to OPENSQUILLA_AGENT_PERMISSIONS, then permissions.default_mode."
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
        workspace_lockdown=workspace_lockdown,
        scratch_dir=scratch_dir,
        thinking=thinking,
        timeout=timeout,
        max_iterations=max_iterations,
        iteration_timeout_seconds=iteration_timeout_seconds,
        tool_timeout_seconds=tool_timeout_seconds,
        request_timeout_seconds=request_timeout_seconds,
        max_provider_retries=max_provider_retries,
        length_capped_continuations=length_capped_continuations,
        transcript_path=transcript_path,
        usage_path=usage_path,
        session_db_path=session_db_path,
        no_memory_capture=no_memory_capture,
        file_paths=file_paths,
        unattended=unattended,
        stateless=stateless,
        clean_room=clean_room,
        stateless_keep_project_rules=stateless_keep_project_rules,
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
        "http://localhost:18791", "--gateway", envvar="OPENSQUILLA_GATEWAY_URL"
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
