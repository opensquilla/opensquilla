"""Config-backed agent mutations for CLI workflows."""

from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from opensquilla.cli.agents_config_queries import AgentRegistryContext
from opensquilla.onboarding.config_store import PersistResult, persist_config
from opensquilla.session.keys import normalize_agent_id


@dataclass(frozen=True)
class AgentConfigMutationResult:
    """Mutation payload plus persistence metadata."""

    payload: dict[str, Any]
    persist: PersistResult


def create_agent_in_config(
    context: AgentRegistryContext,
    *,
    agent_id: str,
    model: str | None,
    workspace: Path | None,
    name: str | None,
    description: str | None,
    quiet: bool,
) -> AgentConfigMutationResult:
    """Create a durable agent entry and persist the containing config."""

    agent = asyncio.run(
        context.registry.create_agent(
            agent_id=agent_id,
            name=name,
            description=description,
            model=model,
            workspace=str(workspace) if workspace is not None else None,
        )
    )
    persist = persist_agents_config(context, quiet=quiet)
    return AgentConfigMutationResult(payload=agent, persist=persist)


def delete_agent_from_config(
    context: AgentRegistryContext,
    *,
    agent_id: str,
    quiet: bool,
) -> AgentConfigMutationResult:
    """Delete a durable agent entry and persist the containing config."""

    asyncio.run(context.registry.delete_agent(agent_id))
    persist = persist_agents_config(context, quiet=quiet)
    payload = {
        "id": normalize_agent_id(agent_id),
        "deleted": True,
        "workspaceDeleted": False,
        "stateDeleted": False,
    }
    return AgentConfigMutationResult(payload=payload, persist=persist)


def persist_agents_config(
    context: AgentRegistryContext,
    *,
    quiet: bool,
) -> PersistResult:
    """Persist agent config changes, optionally suppressing incidental stdout."""

    if not quiet:
        return persist_config(
            context.config,
            path=context.config_path,
            restart_required=True,
        )
    with redirect_stdout(StringIO()):
        return persist_config(
            context.config,
            path=context.config_path,
            restart_required=True,
        )
