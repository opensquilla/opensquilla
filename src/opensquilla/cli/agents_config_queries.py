"""Config-backed agent queries for CLI workflows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opensquilla.agents.registry import AgentRegistry
from opensquilla.gateway.config import GatewayConfig
from opensquilla.onboarding.config_store import default_config_path, load_config


@dataclass(frozen=True)
class AgentRegistryContext:
    """Resolved config and registry objects for one CLI invocation."""

    config_path: Path
    config: GatewayConfig
    registry: AgentRegistry


def load_agent_registry(config_path: Path | None) -> AgentRegistryContext:
    """Load the configured agent registry without enabling registry self-persistence."""

    target = config_path or default_config_path()
    cfg = load_config(target)
    registry = AgentRegistry(cfg, config_path=target, persist_changes=False)
    return AgentRegistryContext(config_path=target, config=cfg, registry=registry)


def list_configured_agents(context: AgentRegistryContext) -> list[dict[str, Any]]:
    """Return configured agents plus the builtin main agent."""

    return asyncio.run(context.registry.list_agents(include_builtin=True))
