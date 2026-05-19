"""Agent command — one-shot agent runner for automation."""

from __future__ import annotations

import asyncio

import typer

from opensquilla.cli.agent_command_output import agent_result_payload, render_agent_result
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
from opensquilla.cli.agent_run_runtime import _cli_sender_id, run_agent_once
from opensquilla.cli.agent_runtime_config import (
    _agent_model_from_config,
    _parse_bool,
    _resolve_permissions_profile,
    _resolve_workspace_strict,
    _with_agent_model_config,
    _with_agent_thinking_config,
    _with_agent_workspace_config,
)

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

_AGENT_RUN_RUNTIME_COMPAT_ALIASES = (_cli_sender_id, run_agent_once)

_AGENT_COMMAND_OUTPUT_COMPAT_ALIASES = (agent_result_payload, render_agent_result)


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
    render_agent_result(
        result,
        json_output=json_output,
        no_provider_printer=_print_no_provider_error,
    )
