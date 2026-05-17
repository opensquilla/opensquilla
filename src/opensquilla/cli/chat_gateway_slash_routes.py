"""Gateway slash-command route matching for interactive chat."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GatewaySlashRouteKind = Literal["exact", "prefix"]


@dataclass(frozen=True)
class GatewaySlashRoute:
    name: str
    kind: GatewaySlashRouteKind
    commands: tuple[str, ...]


@dataclass(frozen=True)
class GatewaySlashRouteMatch:
    name: str
    command: str
    parts: list[str]
    route: GatewaySlashRoute


GATEWAY_SLASH_ROUTES: tuple[GatewaySlashRoute, ...] = (
    GatewaySlashRoute("help", "exact", ("/help",)),
    GatewaySlashRoute("new", "prefix", ("/new",)),
    GatewaySlashRoute("status", "exact", ("/status", "/session")),
    GatewaySlashRoute("sessions", "prefix", ("/sessions",)),
    GatewaySlashRoute("resume", "prefix", ("/resume",)),
    GatewaySlashRoute("delete", "prefix", ("/delete",)),
    GatewaySlashRoute("clear", "exact", ("/clear", "/reset")),
    GatewaySlashRoute("compact", "exact", ("/compact",)),
    GatewaySlashRoute("models", "prefix", ("/models",)),
    GatewaySlashRoute("model", "prefix", ("/model",)),
    GatewaySlashRoute("cost", "exact", ("/cost",)),
    GatewaySlashRoute("usage", "exact", ("/usage",)),
    GatewaySlashRoute("tool_compress", "prefix", ("/tool-compress",)),
    GatewaySlashRoute("save", "prefix", ("/save",)),
    GatewaySlashRoute("image", "prefix", ("/image",)),
    GatewaySlashRoute("path", "prefix", ("/path",)),
    GatewaySlashRoute("file", "prefix", ("/file",)),
    GatewaySlashRoute("permissions", "prefix", ("/permissions", "/elevated")),
    GatewaySlashRoute("forget", "prefix", ("/forget",)),
    GatewaySlashRoute("approvals", "prefix", ("/approvals",)),
)


def _match_prefix(command: str, name: str) -> list[str] | None:
    if command == name or command.startswith(f"{name} "):
        return command.split(maxsplit=1)
    return None


def match_gateway_slash_route(command: str) -> GatewaySlashRouteMatch | None:
    """Return the first gateway slash route matching ``command``."""

    for route in GATEWAY_SLASH_ROUTES:
        for candidate in route.commands:
            if route.kind == "exact":
                if command == candidate:
                    return GatewaySlashRouteMatch(route.name, candidate, [command], route)
                continue
            parts = _match_prefix(command, candidate)
            if parts is not None:
                return GatewaySlashRouteMatch(route.name, candidate, parts, route)
    return None
