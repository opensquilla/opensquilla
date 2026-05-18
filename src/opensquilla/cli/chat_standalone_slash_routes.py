"""Standalone slash-command route matching for interactive chat."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StandaloneSlashRouteKind = Literal["exact", "prefix"]


@dataclass(frozen=True)
class StandaloneSlashRoute:
    name: str
    kind: StandaloneSlashRouteKind
    commands: tuple[str, ...]


@dataclass(frozen=True)
class StandaloneSlashRouteMatch:
    name: str
    command: str
    parts: list[str]
    route: StandaloneSlashRoute


STANDALONE_SLASH_ROUTES: tuple[StandaloneSlashRoute, ...] = (
    StandaloneSlashRoute("help", "exact", ("/help",)),
    StandaloneSlashRoute("new", "prefix", ("/new",)),
    StandaloneSlashRoute("status", "exact", ("/status", "/session")),
    StandaloneSlashRoute("models", "exact", ("/models",)),
    StandaloneSlashRoute("model", "prefix", ("/model",)),
    StandaloneSlashRoute("cost", "exact", ("/cost",)),
    StandaloneSlashRoute("tool_compress", "prefix", ("/tool-compress",)),
    StandaloneSlashRoute("clear", "exact", ("/clear", "/reset")),
    StandaloneSlashRoute("compact", "exact", ("/compact",)),
    StandaloneSlashRoute("save", "prefix", ("/save",)),
    StandaloneSlashRoute("image", "prefix", ("/image",)),
    StandaloneSlashRoute("path", "prefix", ("/path",)),
)

STANDALONE_SLASH_ROUTE_NAMES: frozenset[str] = frozenset(
    route.name for route in STANDALONE_SLASH_ROUTES
)


def _match_prefix(command: str, name: str) -> list[str] | None:
    if command == name or command.startswith(f"{name} "):
        return command.split(maxsplit=1)
    return None


def match_standalone_slash_route(command: str) -> StandaloneSlashRouteMatch | None:
    """Return the first standalone slash route matching ``command``."""

    for route in STANDALONE_SLASH_ROUTES:
        for candidate in route.commands:
            if route.kind == "exact":
                if command == candidate:
                    return StandaloneSlashRouteMatch(route.name, candidate, [command], route)
                continue
            parts = _match_prefix(command, candidate)
            if parts is not None:
                return StandaloneSlashRouteMatch(route.name, candidate, parts, route)
    return None
