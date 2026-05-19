"""Result payload and rendering helpers for the agent CLI command."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import typer

from opensquilla.cli.agent_outputs import AgentRunResult, _public_artifacts

__all__ = ("agent_result_payload", "render_agent_result")


def agent_result_payload(result: AgentRunResult) -> dict[str, Any]:
    artifacts = _public_artifacts(result.artifacts)
    return {
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


def render_agent_result(
    result: AgentRunResult,
    *,
    json_output: bool,
    no_provider_printer: Callable[[], None],
) -> None:
    payload = agent_result_payload(result)
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False))
        return

    if result.text:
        typer.echo(result.text)
    for artifact in payload["artifacts"]:
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
                no_provider_printer()
                raise typer.Exit(1)
            typer.echo(f"Error: {error['message']}", err=True)
