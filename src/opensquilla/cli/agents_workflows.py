"""CLI workflows for durable agent commands."""

from __future__ import annotations

from pathlib import Path

from opensquilla.cli.agents_config_mutations import (
    create_agent_in_config,
    delete_agent_from_config,
)
from opensquilla.cli.agents_config_queries import (
    list_configured_agents,
    load_agent_registry,
)
from opensquilla.cli.agents_presenters import (
    confirm_agent_delete,
    emit_agent_config_error,
    emit_agent_deleted,
    emit_agent_saved,
    emit_agents,
)


def list_agents_for_cli(
    config_path: Path | None,
    *,
    json_output: bool,
) -> None:
    """Load and emit configured agents for the CLI."""

    context = load_agent_registry(config_path)
    agents = list_configured_agents(context)
    emit_agents(agents, config_path=context.config_path, json_output=json_output)


def add_agent_for_cli(
    agent_id: str,
    *,
    model: str | None,
    workspace: Path | None,
    name: str | None,
    description: str | None,
    json_output: bool,
    config_path: Path | None,
) -> None:
    """Create and persist a durable agent entry for the CLI."""

    context = load_agent_registry(config_path)
    try:
        result = create_agent_in_config(
            context,
            agent_id=agent_id,
            model=model,
            workspace=workspace,
            name=name,
            description=description,
            quiet=json_output,
        )
    except (ValueError, KeyError) as exc:
        emit_agent_config_error(exc)

    emit_agent_saved(
        result.payload,
        persist=result.persist,
        json_output=json_output,
    )


def delete_agent_for_cli(
    agent_id: str,
    *,
    force: bool,
    json_output: bool,
    config_path: Path | None,
) -> None:
    """Delete and persist a durable agent entry for the CLI."""

    context = load_agent_registry(config_path)
    confirm_agent_delete(agent_id, force=force)
    try:
        result = delete_agent_from_config(
            context,
            agent_id=agent_id,
            quiet=json_output,
        )
    except (ValueError, KeyError) as exc:
        emit_agent_config_error(exc)

    emit_agent_deleted(
        result.payload,
        agent_id=agent_id,
        persist=result.persist,
        json_output=json_output,
    )
