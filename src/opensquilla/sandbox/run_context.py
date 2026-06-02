"""Per-session sandbox run context persistence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opensquilla.sandbox.domain_validation import validate_domain_pattern
from opensquilla.sandbox.package_bundles import expand_package_bundle
from opensquilla.sandbox.path_validation import (
    decide_path_access,
    normalize_mount_access,
    normalize_path,
)
from opensquilla.sandbox.run_mode import RunMode, config_run_mode, normalize_run_mode
from opensquilla.sandbox.sensitive_paths import sensitive_path_marker

RUN_CONTEXT_ORIGIN_KEY = "sandbox_run_context"
DEFAULT_ROOT_WORKSPACE = "/root/.opensquilla/workspace"
_DEFAULT_WORKSPACE_CREDENTIAL_PARTS: tuple[tuple[str, ...], ...] = (
    (".aws", "credentials"),
    (".kube", "config"),
    (".docker", "config"),
    (".docker", "config.json"),
    (".gnupg",),
)


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
class PackageBundleGrant:
    bundle_id: str
    scope: str = "workspace"
    source: str = "manual"


@dataclass(frozen=True)
class TemporaryGrant:
    kind: str
    value: str
    fingerprint: str
    expires_after: str = "once"


@dataclass(frozen=True)
class RunContext:
    run_mode: RunMode
    workspace: str | None = None
    mounts: tuple[MountGrant, ...] = ()
    domains: tuple[DomainGrant, ...] = ()
    bundles: tuple[PackageBundleGrant, ...] = ()
    temporary_grants: tuple[TemporaryGrant, ...] = ()
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
            "bundles": [
                {
                    "bundle_id": grant.bundle_id,
                    "scope": grant.scope,
                    "source": grant.source,
                }
                for grant in self.bundles
            ],
            "temporary_grants": [
                {
                    "kind": grant.kind,
                    "value": grant.value,
                    "fingerprint": grant.fingerprint,
                    "expires_after": grant.expires_after,
                }
                for grant in self.temporary_grants
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


def normalize_scope(scope: Any, default: str = "chat") -> str:
    value = str(scope or default).strip().lower()
    return value if value in {"chat", "workspace", "once"} else default


def _is_filesystem_root(path: str) -> bool:
    try:
        normalized = Path(path)
        return normalized == Path(normalized.anchor)
    except (OSError, RuntimeError, ValueError):
        return False


def _is_relative_to_path(candidate: str, root: str) -> bool:
    try:
        Path(candidate).relative_to(Path(root))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _is_sensitive_default_workspace_target(path: str, workspace: str) -> bool:
    marker = sensitive_path_marker(path, workspace=workspace)
    if marker is not None:
        return True
    try:
        relative_parts = tuple(
            part.casefold() for part in Path(path).relative_to(Path(workspace)).parts
        )
    except (OSError, RuntimeError, ValueError):
        return True
    for blocked in _DEFAULT_WORKSPACE_CREDENTIAL_PARTS:
        limit = len(relative_parts) - len(blocked) + 1
        for start in range(max(limit, 0)):
            if relative_parts[start : start + len(blocked)] == blocked:
                return True
    return False


def normalize_workspace_path(value: Any) -> str:
    workspace = _string_value(value)
    if workspace is None:
        raise ValueError("empty_workspace_path")
    try:
        normalized_workspace = str(normalize_path(workspace))
    except (OSError, RuntimeError, ValueError):
        raise ValueError("invalid_workspace_path")
    if _is_filesystem_root(normalized_workspace):
        raise ValueError("sensitive_path")
    default_root_workspace = str(normalize_path(DEFAULT_ROOT_WORKSPACE))
    if _is_relative_to_path(normalized_workspace, default_root_workspace):
        if _is_sensitive_default_workspace_target(
            normalized_workspace,
            default_root_workspace,
        ):
            raise ValueError("sensitive_path")
        return normalized_workspace
    decision = decide_path_access(
        normalized_workspace,
        workspace=None,
        mounts=(),
        write=True,
    )
    if decision.status == "blocked":
        raise ValueError("sensitive_path")
    return normalized_workspace


def _workspace_from_payload(value: Any) -> str | None:
    try:
        return normalize_workspace_path(value)
    except ValueError:
        return None


def _mounts_from_payload(
    value: Any,
    *,
    workspace: str | None = None,
) -> tuple[MountGrant, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return ()
    mounts: dict[str, MountGrant] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        path = _string_value(item.get("path"))
        if path is None:
            continue
        access = normalize_mount_access(_string_value(item.get("access"), "ro"))
        try:
            decision = decide_path_access(
                path,
                workspace=workspace,
                mounts=(),
                write=access == "rw",
            )
        except (OSError, RuntimeError, ValueError):
            continue
        if decision.status == "blocked":
            continue
        grant = MountGrant(
            path=decision.normalized_path,
            access=access,
            scope=normalize_scope(item.get("scope"), "chat"),
        )
        mounts.pop(grant.path, None)
        mounts[grant.path] = grant
    return tuple(mounts.values())


def _domains_from_payload(value: Any) -> tuple[DomainGrant, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return ()
    domains: dict[str, DomainGrant] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        domain = _string_value(item.get("domain"))
        if domain is None:
            continue
        decision = validate_domain_pattern(domain)
        if decision.status == "blocked":
            continue
        grant = DomainGrant(
            domain=decision.normalized,
            scope=normalize_scope(item.get("scope"), "chat"),
            source=_string_value(item.get("source"), "manual") or "manual",
        )
        domains.pop(grant.domain, None)
        domains[grant.domain] = grant
    return tuple(domains.values())


def _bundles_from_payload(value: Any) -> tuple[PackageBundleGrant, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return ()
    bundles: dict[str, PackageBundleGrant] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        bundle_id = _string_value(item.get("bundle_id") or item.get("bundleId"))
        if bundle_id is None:
            continue
        if not expand_package_bundle(bundle_id):
            continue
        grant = PackageBundleGrant(
            bundle_id=bundle_id,
            scope=normalize_scope(item.get("scope"), "workspace"),
            source=_string_value(item.get("source"), "manual") or "manual",
        )
        bundles.pop(grant.bundle_id, None)
        bundles[grant.bundle_id] = grant
    return tuple(bundles.values())


def _temporary_grants_from_payload(value: Any) -> tuple[TemporaryGrant, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return ()
    grants: list[TemporaryGrant] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = _string_value(item.get("kind"))
        grant_value = _string_value(item.get("value"))
        fingerprint = _string_value(item.get("fingerprint"))
        if kind is None or grant_value is None or fingerprint is None:
            continue
        grants.append(
            TemporaryGrant(
                kind=kind,
                value=grant_value,
                fingerprint=fingerprint,
                expires_after=(
                    _string_value(
                        item.get("expires_after") or item.get("expiresAfter"),
                        "once",
                    )
                    or "once"
                ),
            )
        )
    return tuple(grants)


def _context_from_payload(payload: Any, source: str) -> RunContext | None:
    if not isinstance(payload, dict):
        return None
    if "run_mode" not in payload:
        return None
    try:
        run_mode = normalize_run_mode(payload.get("run_mode"))
    except ValueError:
        return None
    workspace = _workspace_from_payload(payload.get("workspace"))
    return RunContext(
        run_mode=run_mode,
        workspace=workspace,
        mounts=_mounts_from_payload(payload.get("mounts"), workspace=workspace),
        domains=_domains_from_payload(payload.get("domains")),
        bundles=_bundles_from_payload(payload.get("bundles")),
        temporary_grants=_temporary_grants_from_payload(payload.get("temporary_grants")),
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
        workspace=_workspace_from_payload(workspace),
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
        bundles=existing.bundles,
        temporary_grants=existing.temporary_grants,
        source="saved",
    )
    return await persist_run_context(session_manager, session_key, updated)


__all__ = [
    "RUN_CONTEXT_ORIGIN_KEY",
    "DEFAULT_ROOT_WORKSPACE",
    "DomainGrant",
    "MountGrant",
    "PackageBundleGrant",
    "RunContext",
    "TemporaryGrant",
    "get_run_context",
    "normalize_scope",
    "normalize_workspace_path",
    "persist_run_context",
    "set_run_mode",
]
