"""Agent command — one-shot agent runner for automation."""

from __future__ import annotations

import asyncio
import getpass
import json
import os
from typing import Any

import typer

from opensquilla.cli.agent_outputs import (
    AgentRunResult,
    _entry_timestamp,
    _message_event,
    _print_no_provider_error,
    _public_artifacts,
    _to_benchmark_transcript,
    _to_transcript_usage,
    _usage_from_done,
    _write_json,
    _write_jsonl,
)
from opensquilla.cli.agent_runtime_config import (
    _agent_model_from_config,
    _parse_bool,
    _resolve_permissions_profile,
    _resolve_workspace_strict,
    _with_agent_model_config,
    _with_agent_thinking_config,
    _with_agent_workspace_config,
)
from opensquilla.cli.attachments import attachments_from_paths

_AGENT_OUTPUT_COMPAT_ALIASES = (
    AgentRunResult,
    _entry_timestamp,
    _message_event,
    _print_no_provider_error,
    _public_artifacts,
    _to_benchmark_transcript,
    _to_transcript_usage,
    _usage_from_done,
    _write_json,
    _write_jsonl,
)

_AGENT_RUNTIME_CONFIG_COMPAT_ALIASES = (
    _agent_model_from_config,
    _parse_bool,
    _resolve_permissions_profile,
    _resolve_workspace_strict,
    _with_agent_model_config,
    _with_agent_thinking_config,
    _with_agent_workspace_config,
)


def _cli_sender_id() -> str:
    raw = os.environ.get("USER")
    if raw and raw.strip():
        return raw.strip()
    try:
        return getpass.getuser() or "cli-user"
    except Exception:
        return "cli-user"


async def run_agent_once(
    *,
    message: str,
    agent_id: str = "main",
    session_id: str = "",
    model: str | None = None,
    workspace: str | None = None,
    workspace_strict: bool | None = None,
    thinking: str | None = None,
    timeout: float | None = None,
    max_iterations: int | None = None,
    transcript_path: str | None = None,
    usage_path: str | None = None,
    config: Any | None = None,
    session_db_path: str = ":memory:",
    no_memory_capture: bool = False,
    attachments: list[dict[str, Any]] | None = None,
    attachment_paths: list[str] | tuple[str, ...] | None = None,
    unattended: bool = True,
    permissions: str | None = None,
) -> AgentRunResult:
    """Run a single agent turn through build_services() and TurnRunner.run()."""
    from opensquilla.agents.scope import resolve_agent_workspace_dir
    from opensquilla.artifacts import artifact_payload
    from opensquilla.engine.types import ArtifactEvent, DoneEvent, ErrorEvent, TextDeltaEvent
    from opensquilla.gateway import attachment_ingest as _attachment_ingest
    from opensquilla.gateway import build_services, build_turn_runner_from_services
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.gateway.routing import build_cli_route_envelope, tool_context_from_envelope
    from opensquilla.paths import media_root_from_config
    from opensquilla.session.keys import canonicalize_session_key, normalize_agent_id
    from opensquilla.tools.types import InteractionMode

    agent_id = normalize_agent_id(agent_id)
    if max_iterations is not None and max_iterations < 1:
        raise ValueError("max_iterations must be an integer >= 1")
    permissions_profile = _resolve_permissions_profile(permissions)
    elevated = permissions_profile if permissions_profile in {"bypass", "full"} else None
    run_attachments: list[dict[str, Any]] = list(attachments or [])
    if attachment_paths:
        run_attachments.extend(attachments_from_paths(tuple(attachment_paths)))
    cfg = config or GatewayConfig.load(os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))
    effective_model = model or _agent_model_from_config(cfg, agent_id)
    active_workspace = workspace or getattr(cfg, "workspace_dir", None)
    service_cfg = _with_agent_workspace_config(cfg, active_workspace) if active_workspace else cfg
    if effective_model:
        service_cfg = _with_agent_model_config(service_cfg, effective_model)
    if thinking:
        service_cfg = _with_agent_thinking_config(service_cfg, thinking)
    effective_workspace_strict = _resolve_workspace_strict(
        cli_value=workspace_strict,
        config_value=getattr(service_cfg, "workspace_strict", None),
        entrypoint_default=bool(active_workspace),
    )
    # Per-agent workspace isolation: gateway resolves this for channel-driven
    # turns; the CLI ToolContext must do the same so file tools target
    # <root>/agents/<id> for non-main agents instead of stepping on the root
    # workspace. Legacy ``default`` is normalized to ``main`` above.
    tool_workspace_dir: str | None
    if active_workspace and agent_id != "main":
        resolved_path = resolve_agent_workspace_dir(agent_id, service_cfg)
        # Mirror gateway boot.py:594 — pre-create the per-agent dir so
        # shell/cwd-based tools do not hit FileNotFoundError on first use.
        resolved_path.mkdir(parents=True, exist_ok=True)
        tool_workspace_dir = str(resolved_path)
    else:
        tool_workspace_dir = active_workspace

    # Hand the runtime agent_id to build_services so its memory store /
    # retriever / sync manager / turn capture are pre-built for that agent.
    # Without this the memory manager only registers ``main`` (channel-derived
    # ids), so non-main CLI invocations would write to the per-agent workspace
    # but the index would never see those writes.
    extra_agents = [agent_id] if agent_id and agent_id != "main" else None
    svc = await build_services(
        config=service_cfg,
        session_db_path=session_db_path,
        extra_agent_ids=extra_agents,
    )
    assert svc.session_manager is not None
    session_key = canonicalize_session_key(session_id or f"agent:{agent_id}:main")

    text_parts: list[str] = []
    errors: list[dict[str, str]] = []
    artifacts: list[dict[str, Any]] = []
    done: DoneEvent | None = None

    try:
        await svc.session_manager.get_or_create(session_key, agent_id=agent_id)
        ingested_attachments = await _attachment_ingest.ingest_attachments(
            message,
            run_attachments,
            failure_mode="raise",
        )
        message = ingested_attachments.text
        run_attachments = ingested_attachments.attachments
        if run_attachments:
            from opensquilla.gateway.transcripts import build_transcript_attachment_envelope

            if hasattr(svc.session_manager, "stamp_user_text"):
                _stamped = svc.session_manager.stamp_user_text(message)
                if isinstance(_stamped, str):
                    message = _stamped

            attachments_cfg = getattr(service_cfg, "attachments", None)
            persist_enabled = bool(getattr(attachments_cfg, "persist_transcripts", True))
            media_root = media_root_from_config(service_cfg)
            disk_budget = getattr(attachments_cfg, "transcript_disk_budget_bytes", None)
            persist_content, _writes = build_transcript_attachment_envelope(
                text=message,
                attachments=run_attachments,
                session_id=session_key.split(":")[-1] or session_key,
                media_root=media_root,
                persist_enabled=persist_enabled,
                disk_budget_bytes=disk_budget if isinstance(disk_budget, int) else None,
            )
            await svc.session_manager.append_message(
                session_key, role="user", content=persist_content
            )
        else:
            _persisted = await svc.session_manager.append_message(
                session_key, role="user", content=message
            )
            if _persisted is not None and isinstance(_persisted.content, str):
                message = _persisted.content

        route_envelope = build_cli_route_envelope(
            session_key=session_key,
            agent_id=agent_id,
            channel_id="cli:agent",
            sender_id=_cli_sender_id(),
            source_name="run",
            interaction_mode=(
                InteractionMode.UNATTENDED if unattended else InteractionMode.INTERACTIVE
            ),
            elevated=elevated,
        )
        tool_ctx = tool_context_from_envelope(
            route_envelope,
            is_owner=True,
            workspace_dir=tool_workspace_dir,
            workspace_strict=effective_workspace_strict,
        )

        runner = build_turn_runner_from_services(svc)

        async for event in runner.run(
            message,
            session_key,
            tool_context=tool_ctx,
            agent_id=agent_id,
            model=effective_model,
            timeout=timeout,
            max_iterations=max_iterations,
            history_has_persisted_user=True,
            no_memory_capture=no_memory_capture,
            attachments=run_attachments,
            bootstrap_context_mode="unattended" if unattended else None,
        ):
            if isinstance(event, TextDeltaEvent):
                text_parts.append(event.text)
            elif isinstance(event, ErrorEvent):
                errors.append({"message": event.message, "code": event.code})
            elif isinstance(event, ArtifactEvent):
                artifacts.append(artifact_payload(event))
            elif isinstance(event, DoneEvent):
                done = event
        usage = _usage_from_done(done, effective_model)
        transcript_usage = _to_transcript_usage(usage)
        if transcript_path:
            transcript = await svc.session_manager.get_transcript(session_key)
            _write_jsonl(transcript_path, _to_benchmark_transcript(transcript, transcript_usage))
    finally:
        await svc.close()

    if usage_path:
        _write_json(usage_path, usage)

    return AgentRunResult(
        status="error" if errors else "ok",
        agent_id=agent_id,
        session_key=session_key,
        text=done.text if done and done.text else "".join(text_parts),
        usage=usage,
        errors=errors,
        workspace=tool_workspace_dir,
        workspace_strict=effective_workspace_strict,
        thinking=thinking or getattr(getattr(service_cfg, "llm", None), "thinking", None),
        transcript_path=transcript_path,
        usage_path=usage_path,
        artifacts=artifacts,
    )


def run_agent_command(
    message: str = typer.Option(..., "--message", "-m", help="Message to send"),
    agent_id: str = typer.Option("main", "--agent", help="Agent identifier"),
    session_id: str = typer.Option("", "--session-id", help="Session key/id to use"),
    model: str = typer.Option("", "--model", help="Model override (provider/model)"),
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
    result = asyncio.run(
        run_agent_once(
            message=message,
            agent_id=agent_id,
            session_id=session_id,
            model=model or None,
            workspace=workspace or None,
            workspace_strict=workspace_strict,
            thinking=thinking or None,
            timeout=timeout,
            max_iterations=max_iterations,
            transcript_path=transcript_path or None,
            usage_path=usage_path or None,
            session_db_path=session_db_path,
            no_memory_capture=no_memory_capture,
            attachment_paths=file_paths,
            unattended=unattended,
            permissions=permissions,
        )
    )
    artifacts = _public_artifacts(result.artifacts)
    payload = {
        "status": result.status,
        "agent_id": result.agent_id,
        "session_key": result.session_key,
        "text": result.text,
        "usage": result.usage,
        "errors": result.errors,
        "workspace": result.workspace,
        "workspace_strict": result.workspace_strict,
        "thinking": result.thinking,
        "transcript_path": result.transcript_path,
        "usage_path": result.usage_path,
        "artifacts": artifacts,
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        if result.text:
            typer.echo(result.text)
        for artifact in artifacts:
            name = artifact.get("name") if isinstance(artifact.get("name"), str) else "artifact"
            target = (
                artifact.get("download_url")
                if isinstance(artifact.get("download_url"), str)
                else artifact.get("id", "")
            )
            typer.echo(f"Generated file: {name} -> {target}")
        if result.errors:
            for error in result.errors:
                if error.get("code") == "no_provider":
                    _print_no_provider_error()
                    raise typer.Exit(1)
                typer.echo(f"Error: {error['message']}", err=True)
