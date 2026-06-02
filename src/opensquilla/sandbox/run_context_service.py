"""Validated mutation helpers for sandbox Run Context."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from opensquilla.sandbox.domain_validation import validate_domain_pattern
from opensquilla.sandbox.package_bundles import expand_package_bundle
from opensquilla.sandbox.path_validation import (
    decide_path_access,
    normalize_mount_access,
)
from opensquilla.sandbox.run_context import (
    DomainGrant,
    MountGrant,
    PackageBundleGrant,
    RunContext,
    get_run_context,
    normalize_scope,
    normalize_workspace_path,
    persist_run_context,
)


def _normalize_bundle_id(bundle_id: Any) -> str:
    return str(bundle_id or "").strip()


async def set_workspace(
    session_manager: Any,
    session_key: str,
    *,
    workspace_path: str,
    config: Any,
    current_workspace: str | None,
) -> RunContext:
    normalized_workspace = normalize_workspace_path(workspace_path)
    existing = await get_run_context(
        session_manager,
        session_key,
        config=config,
        workspace=current_workspace,
    )
    existing_workspace = None
    if existing.workspace is not None:
        try:
            existing_workspace = normalize_workspace_path(existing.workspace)
        except ValueError:
            existing_workspace = existing.workspace
    if existing_workspace == normalized_workspace:
        return existing
    updated = replace(existing, workspace=normalized_workspace, source="saved")
    return await persist_run_context(session_manager, session_key, updated)


async def add_mount_grant(
    session_manager: Any,
    session_key: str,
    *,
    path: str,
    access: str,
    scope: str,
    config: Any,
    workspace: str | None,
) -> RunContext:
    existing = await get_run_context(
        session_manager,
        session_key,
        config=config,
        workspace=workspace,
    )
    mount_access = normalize_mount_access(access)
    decision = decide_path_access(
        path,
        workspace=existing.workspace or workspace,
        mounts=existing.mounts,
        write=mount_access == "rw",
    )
    if decision.status == "blocked":
        raise ValueError(decision.reason or "mount_blocked")
    grant = MountGrant(
        path=decision.normalized_path,
        access=mount_access,
        scope=normalize_scope(scope),
    )
    if grant in existing.mounts:
        return existing
    mounts = tuple(m for m in existing.mounts if m.path != grant.path) + (grant,)
    if mounts == existing.mounts:
        return existing
    return await persist_run_context(
        session_manager,
        session_key,
        replace(existing, mounts=mounts, source="saved"),
    )


async def remove_mount_grant(
    session_manager: Any,
    session_key: str,
    *,
    path: str,
    config: Any,
    workspace: str | None,
) -> RunContext:
    existing = await get_run_context(
        session_manager,
        session_key,
        config=config,
        workspace=workspace,
    )
    decision = decide_path_access(
        path,
        workspace=existing.workspace or workspace,
        mounts=existing.mounts,
    )
    if decision.status == "blocked":
        raise ValueError(decision.reason or "mount_blocked")
    normalized_path = decision.normalized_path
    removal_paths = {normalized_path, path}
    mounts = tuple(m for m in existing.mounts if m.path not in removal_paths)
    if mounts == existing.mounts:
        return existing
    return await persist_run_context(
        session_manager,
        session_key,
        replace(existing, mounts=mounts, source="saved"),
    )


async def add_domain_grant(
    session_manager: Any,
    session_key: str,
    *,
    domain: str,
    scope: str,
    config: Any,
    workspace: str | None,
    source: str = "manual",
) -> RunContext:
    decision = validate_domain_pattern(domain)
    if decision.status == "blocked":
        raise ValueError(decision.reason)
    existing = await get_run_context(
        session_manager,
        session_key,
        config=config,
        workspace=workspace,
    )
    grant = DomainGrant(
        domain=decision.normalized,
        scope=normalize_scope(scope),
        source=source,
    )
    if grant in existing.domains:
        return existing
    domains = tuple(d for d in existing.domains if d.domain != grant.domain) + (grant,)
    if domains == existing.domains:
        return existing
    return await persist_run_context(
        session_manager,
        session_key,
        replace(existing, domains=domains, source="saved"),
    )


async def remove_domain_grant(
    session_manager: Any,
    session_key: str,
    *,
    domain: str,
    config: Any,
    workspace: str | None,
) -> RunContext:
    decision = validate_domain_pattern(domain)
    if decision.status == "blocked":
        raise ValueError(decision.reason)
    normalized = decision.normalized
    existing = await get_run_context(
        session_manager,
        session_key,
        config=config,
        workspace=workspace,
    )
    domains = tuple(d for d in existing.domains if d.domain != normalized)
    if domains == existing.domains:
        return existing
    return await persist_run_context(
        session_manager,
        session_key,
        replace(existing, domains=domains, source="saved"),
    )


async def enable_bundle_grant(
    session_manager: Any,
    session_key: str,
    *,
    bundle_id: str,
    scope: str,
    config: Any,
    workspace: str | None,
) -> RunContext:
    normalized_bundle_id = _normalize_bundle_id(bundle_id)
    if not expand_package_bundle(normalized_bundle_id):
        raise ValueError("unknown_package_bundle")
    existing = await get_run_context(
        session_manager,
        session_key,
        config=config,
        workspace=workspace,
    )
    grant = PackageBundleGrant(
        bundle_id=normalized_bundle_id,
        scope=normalize_scope(scope, "workspace"),
        source="manual",
    )
    if grant in existing.bundles:
        return existing
    bundles = tuple(b for b in existing.bundles if b.bundle_id != grant.bundle_id) + (
        grant,
    )
    if bundles == existing.bundles:
        return existing
    return await persist_run_context(
        session_manager,
        session_key,
        replace(existing, bundles=bundles, source="saved"),
    )


async def disable_bundle_grant(
    session_manager: Any,
    session_key: str,
    *,
    bundle_id: str,
    config: Any,
    workspace: str | None,
) -> RunContext:
    normalized_bundle_id = _normalize_bundle_id(bundle_id)
    if not expand_package_bundle(normalized_bundle_id):
        raise ValueError("unknown_package_bundle")
    existing = await get_run_context(
        session_manager,
        session_key,
        config=config,
        workspace=workspace,
    )
    bundles = tuple(b for b in existing.bundles if b.bundle_id != normalized_bundle_id)
    if bundles == existing.bundles:
        return existing
    return await persist_run_context(
        session_manager,
        session_key,
        replace(existing, bundles=bundles, source="saved"),
    )


__all__ = [
    "add_domain_grant",
    "add_mount_grant",
    "disable_bundle_grant",
    "enable_bundle_grant",
    "normalize_scope",
    "remove_domain_grant",
    "remove_mount_grant",
    "set_workspace",
]
