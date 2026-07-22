"""Register all built-in tools by importing each submodule."""

from __future__ import annotations

from importlib import import_module

import structlog

_FATAL_MODULES = frozenset({"shell", "patch", "filesystem"})
_NAMES = [
    "admin",
    "agents",
    "artifacts",
    "code_exec",
    "file_authoring",
    "filesystem",
    "git",
    "media",
    "messaging",
    "meta_tools",
    "nodes",
    "patch",
    "router_control",
    "sessions",
    "session_search",
    "shell",
    "tool_results",
    "web",
    "web_fetch",
]

log = structlog.get_logger(__name__)

for _name in _NAMES:
    try:
        globals()[_name] = import_module(f"{__name__}.{_name}")
    except Exception as exc:
        if _name in _FATAL_MODULES:
            raise
        log.warning("builtin_tool.import_failed", module=_name, error=str(exc))
        continue

# Contrib bridges register alongside the builtins so config-driven agents can
# allow-list them; their tools are hidden (exposed_by_default=False) unless
# surfaced. Never fatal: a broken contrib bridge must not take down the core
# tool surface.
try:
    import_module("opensquilla.contrib.aiq")
except Exception as exc:  # pragma: no cover - defensive
    log.warning("contrib_tool.import_failed", module="opensquilla.contrib.aiq", error=str(exc))

__all__ = _NAMES
