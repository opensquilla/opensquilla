"""Runtime assembly helpers for gateway-managed channel adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from starlette.routing import Route

from opensquilla.channels.registry import build_managed_channel
from opensquilla.channels.types import ManagedChannel

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ChannelRuntimeAssembly:
    """Adapters plus manager metadata derived from channel config entries."""

    channels: dict[str, ManagedChannel]
    agent_ids: dict[str, str]
    channel_types: dict[str, str]


def build_channel_runtime_assembly(
    entries: list[Any],
    *,
    logger: Any = log,
) -> ChannelRuntimeAssembly:
    """Build managed channel adapters and manager metadata from config entries."""

    channels: dict[str, ManagedChannel] = {}
    agent_ids: dict[str, str] = {}
    channel_types: dict[str, str] = {}
    for entry in entries:
        if not entry.enabled:
            logger.info("channel.skipped_disabled", name=entry.name)
            continue

        adapter = build_managed_channel(entry)
        if adapter is None:
            logger.warning("channel.unknown_type", type=entry.type, name=entry.name)
            continue

        channels[entry.name] = adapter
        agent_ids[entry.name] = getattr(entry, "agent_id", "main")
        channel_types[entry.name] = entry.type
        setattr(adapter, "debounce_window_s", getattr(entry, "debounce_window_s", 0.0))
        logger.info("channel.adapter_created", name=entry.name, type=entry.type)

    return ChannelRuntimeAssembly(
        channels=channels,
        agent_ids=agent_ids,
        channel_types=channel_types,
    )


def collect_channel_webhook_routes(
    channels: dict[str, ManagedChannel],
    *,
    logger: Any = log,
) -> list[Route]:
    """Extract Starlette routes from webhook-capable managed channels."""

    routes: list[Route] = []
    for name, adapter in channels.items():
        if getattr(adapter, "transport_name", "webhook") != "webhook":
            continue
        if hasattr(adapter, "create_webhook_route"):
            route = adapter.create_webhook_route()
            routes.append(route)
            logger.info("channel.webhook_route_collected", channel=name, path=route.path)
    return routes
