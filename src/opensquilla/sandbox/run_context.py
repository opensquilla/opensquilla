"""Per-session sandbox run context persistence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from opensquilla.sandbox.run_mode import RunMode, config_run_mode, normalize_run_mode

RUN_CONTEXT_ORIGIN_KEY = "sandbox_run_context"


@dataclass(frozen=True)
class MountGrant:
    path: str
    access: str = "ro"
    scope: str = "chat"


@dataclass(frozen=True)
class DomainGrant:
    domain: str
    scope: str = "chat"
    source: str = "manual"


@dataclass(frozen=True)
class RunContext:
    run_mode: RunMode
    workspace: str | None = None
    mounts: tuple[MountGrant, ...] = ()
    domains: tuple[DomainGrant, ...] = ()
    source: str = "default"

    def to_origin_payload(self) -> dict[str, Any]:
        return {
            "run_mode": self.run_mode.value,
            "workspace": self.workspace,
            "mounts": [
                {"path": grant.path, "access": grant.access, "scope": grant.scope}
                for grant in self.mounts
            ],
            "domains": [
                {
                    "domain": grant.domain,
                    "scope": grant.scope,
                    "source": grant.source,
                }
                for grant in self.domains
            ],
        }


async def _get_session_node(session_manager: Any, session_key: str) -> Any | None:
    get_session = getattr(session_manager, "get_session", None)
    if callable(get_session):
        return await get_session(session_key)

    storage = getattr(session_manager, "_storage", None)
    storage_get = getattr(storage, "get_session", None)
    if callable(storage_get):
        return await storage_get(session_key)
    return None


def _origin_dict(node: Any) -> dict[str, Any]:
    origin = getattr(node, "origin", None)
    return dict(origin) if isinstance(origin, dict) else {}


def _string_value(value: Any, default: str | None = None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _mounts_from_payload(value: Any) -> tuple[MountGrant, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return ()
    mounts: list[MountGrant] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        path = _string_value(item.get("path"))
        if path is None:
            continue
        mounts.append(
            MountGrant(
                path=path,
                access=_string_value(item.get("access"), "ro") or "ro",
                scope=_string_value(item.get("scope"), "chat") or "chat",
            )
        )
    return tuple(mounts)


def _domains_from_payload(value: Any) -> tuple[DomainGrant, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return ()
    domains: list[DomainGrant] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        domain = _string_value(item.get("domain"))
        if domain is None:
            continue
        domains.append(
            DomainGrant(
                domain=domain,
                scope=_string_value(item.get("scope"), "chat") or "chat",
                source=_string_value(item.get("source"), "manual") or "manual",
            )
        )
    return tuple(domains)


def _context_from_payload(payload: Any, source: str) -> RunContext | None:
    if not isinstance(payload, dict):
        return None
    if "run_mode" not in payload:
        return None
    try:
        run_mode = normalize_run_mode(payload.get("run_mode"))
    except ValueError:
        return None
    workspace = payload.get("workspace")
    return RunContext(
        run_mode=run_mode,
        workspace=workspace if isinstance(workspace, str) and workspace else None,
        mounts=_mounts_from_payload(payload.get("mounts")),
        domains=_domains_from_payload(payload.get("domains")),
        source=source,
    )


async def get_run_context(
    session_manager: Any,
    session_key: str,
    *,
    config: Any,
    workspace: str | None,
) -> RunContext:
    node = await _get_session_node(session_manager, session_key)
    if node is not None:
        origin = _origin_dict(node)
        saved = _context_from_payload(origin.get(RUN_CONTEXT_ORIGIN_KEY), "saved")
        if saved is not None:
            return saved
    return RunContext(
        run_mode=config_run_mode(config),
        workspace=workspace,
        source="default",
    )


async def persist_run_context(
    session_manager: Any,
    session_key: str,
    context: RunContext,
) -> RunContext:
    node = await _get_session_node(session_manager, session_key)
    if node is None:
        raise KeyError(f"Session not found: {session_key}")
    origin = _origin_dict(node)
    origin[RUN_CONTEXT_ORIGIN_KEY] = context.to_origin_payload()
    update = getattr(session_manager, "update", None)
    if not callable(update):
        raise RuntimeError("Session manager does not support update")
    await update(session_key, origin=origin)
    return context


async def set_run_mode(
    session_manager: Any,
    session_key: str,
    run_mode: RunMode | str,
    *,
    config: Any,
    workspace: str | None = None,
) -> RunContext:
    existing = await get_run_context(
        session_manager,
        session_key,
        config=config,
        workspace=workspace,
    )
    updated = RunContext(
        run_mode=normalize_run_mode(run_mode),
        workspace=existing.workspace,
        mounts=existing.mounts,
        domains=existing.domains,
        source="saved",
    )
    return await persist_run_context(session_manager, session_key, updated)


__all__ = [
    "RUN_CONTEXT_ORIGIN_KEY",
    "DomainGrant",
    "MountGrant",
    "RunContext",
    "get_run_context",
    "persist_run_context",
    "set_run_mode",
]
