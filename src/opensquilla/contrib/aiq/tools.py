"""Register every bridged AIQ tool as a native OpenSquilla tool.

Each catalog entry becomes a :func:`opensquilla.tools.registry.tool`
registration with the tool's real schema (see ``catalog.json``). Handlers are
thin async shims over :func:`opensquilla.contrib.aiq.runtime.invoke_aiq_tool`,
so importing this module never touches the AIQ repo.

All bridged tools are registered with ``exposed_by_default=False`` — they are
invisible to every surface unless explicitly allow-listed, which the bundled
``aiq`` agent entry does (see :mod:`opensquilla.contrib.aiq.agent`).

Sandbox/policy declaration per catalog group:

- ``read``      network descriptor ``kind="aiq.read"`` — read-only Snowflake/
                Neo4j data queries.
- ``external``  network descriptor ``kind="aiq.external.read"`` plus
                ``result_budget_class="external"`` — third-party HTTP APIs
                (FRED, news, GitHub, FMP, EODHD).
- ``local``     custom descriptor ``kind="aiq.local"`` — pure computation or
                UI-payload assembly, no I/O.
- ``write``     custom descriptor ``kind="aiq.write"`` — mutates user-scoped
                state (portfolios, user facts) in AIQ's own stores.
"""

from __future__ import annotations

from typing import Any

from opensquilla.contrib.aiq.catalog import AiqToolDef, aiq_tool_names, load_catalog
from opensquilla.contrib.aiq.runtime import invoke_aiq_tool
from opensquilla.sandbox.operation_runtime import SandboxToolDescriptor
from opensquilla.tools.registry import ToolRegistry, get_default_registry
from opensquilla.tools.registry import tool as tool_decorator

__all__ = ["aiq_tool_names", "register_aiq_tools"]

_EXECUTION_TIMEOUT_SECONDS = 120.0

_registered_registries: set[int] = set()


def _sandbox_for(tool_def: AiqToolDef) -> SandboxToolDescriptor:
    name = tool_def.name
    if tool_def.group == "read":
        return SandboxToolDescriptor.network(
            kind="aiq.read",
            argv_factory=lambda a, _name=name: (_name,),
            record_payload=False,
        )
    if tool_def.group == "external":
        return SandboxToolDescriptor.network(
            kind="aiq.external.read",
            argv_factory=lambda a, _name=name: (_name,),
            record_payload=False,
        )
    if tool_def.group == "write":
        return SandboxToolDescriptor.custom(kind="aiq.write")
    return SandboxToolDescriptor.custom(kind="aiq.local")


def _make_handler(tool_def: AiqToolDef):
    async def handler(**arguments: Any) -> str:
        return await invoke_aiq_tool(
            tool_def.name,
            tool_def.module,
            tool_def.attr,
            arguments,
            tool_def.required,
        )

    handler.__name__ = tool_def.name
    handler.__qualname__ = tool_def.name
    handler.__doc__ = tool_def.description
    return handler


def register_aiq_tools(registry: ToolRegistry | None = None) -> list[str]:
    """Register all bridged AIQ tools into ``registry`` (default registry if None).

    Idempotent per registry: repeated calls do not re-register (which would
    log ``registry.tool_overwrite`` warnings). Returns the bridged tool names.
    """

    target = registry if registry is not None else get_default_registry()
    if id(target) in _registered_registries:
        return aiq_tool_names()
    for tool_def in load_catalog():
        decorate = tool_decorator(
            name=tool_def.name,
            description=tool_def.description,
            params=tool_def.params,
            required=tool_def.required,
            exposed_by_default=False,
            execution_timeout_seconds=_EXECUTION_TIMEOUT_SECONDS,
            result_budget_class="external" if tool_def.group == "external" else None,
            sandbox=_sandbox_for(tool_def),
            registry=target,
        )
        decorate(_make_handler(tool_def))
    _registered_registries.add(id(target))
    return aiq_tool_names()
