"""Static catalog of bridged AIQ tools.

``catalog.json`` is a build-time snapshot of every AIQ agent tool surface
(TraceAgent + PortfolioAgent first-class tools plus the long-tail registry),
with each tool's JSON-Schema properties converted to the OpenSquilla subset
(``type``/type arrays, ``enum``, ``items``; strict-mode ``anyOf`` nullability
folded into type arrays). Loading it requires neither the AIQ repo nor any of
its dependencies — the live implementations are imported lazily at tool-call
time by :mod:`opensquilla.contrib.aiq.runtime`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

# Sandbox/policy classification for a bridged tool:
#   read     — read-only Snowflake/Neo4j data query (network domain, aiq.read)
#   external — read-only third-party HTTP API (network domain, external budget)
#   local    — pure-Python / UI-payload tool, no I/O (custom domain)
#   write    — mutates user state (portfolios, user facts) in AIQ's stores
ToolGroup = str

_VALID_GROUPS = frozenset({"read", "external", "local", "write"})


@dataclass(frozen=True)
class AiqToolDef:
    """One bridged AIQ tool: schema plus its lazy import location."""

    name: str
    module: str
    attr: str
    group: ToolGroup
    description: str
    params: dict[str, Any]
    required: list[str]


@cache
def load_catalog() -> tuple[AiqToolDef, ...]:
    """Load and validate the bridged-tool catalog (cached)."""

    raw = resources.files(__package__).joinpath("catalog.json").read_text(encoding="utf-8")
    entries = json.loads(raw)
    tools: list[AiqToolDef] = []
    for entry in entries:
        tool = AiqToolDef(
            name=entry["name"],
            module=entry["module"],
            attr=entry["attr"],
            group=entry["group"],
            description=entry["description"],
            params=entry["params"],
            required=list(entry["required"]),
        )
        if tool.group not in _VALID_GROUPS:
            raise ValueError(f"catalog.json: unknown group {tool.group!r} for {tool.name!r}")
        tools.append(tool)
    return tuple(tools)


def aiq_tool_names() -> list[str]:
    """Names of every bridged AIQ tool, in catalog order."""

    return [tool.name for tool in load_catalog()]
