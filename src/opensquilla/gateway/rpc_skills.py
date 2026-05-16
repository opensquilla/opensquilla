"""Skills domain RPC handlers (Tier 3 stubs)."""

from __future__ import annotations

import asyncio
import weakref
from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.skills.hub.deps import install_deps
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.rpc_payload import (
    skill_deps_install_result_rpc_payload,
    skill_get_rpc_payload,
    skill_install_result_rpc_payload,
    skill_install_unavailable_rpc_payload,
    skill_missing_requirements_rpc_payload,
    skill_uninstall_result_rpc_payload,
    skill_uninstall_unavailable_rpc_payload,
    skills_bins_rpc_payload,
    skills_list_rpc_payload,
    skills_search_rpc_payload,
    skills_search_unavailable_rpc_payload,
    skills_status_rpc_payload,
    skills_update_empty_results_rpc_payload,
    skills_update_results_rpc_payload,
    skills_update_unavailable_rpc_payload,
    validate_skill_install_supported,
)

_d = get_dispatcher()

# Per-(name, install_id) install serialization. WeakValueDictionary prevents
# unbounded growth: once all coroutines release a lock it gets GC'd.
_deps_locks: weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


def _deps_lock_for(name: str, install_id: str) -> asyncio.Lock:
    key = (name, install_id)
    lock = _deps_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _deps_locks[key] = lock
    return lock


def _get_loader(ctx: RpcContext) -> SkillLoader | None:
    return getattr(ctx, "skill_loader", None)


@_d.method("skills.status", scope="operator.read")
async def _handle_skills_status(params: dict | None, ctx: RpcContext) -> list[dict[str, Any]]:
    """Return all skills with their eligibility status."""
    return skills_status_rpc_payload(_get_loader(ctx))


@_d.method("skills.list", scope="operator.read")
async def _handle_skills_list(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """List installed skills."""
    return skills_list_rpc_payload(_get_loader(ctx))


@_d.method("skills.bins", scope="node")
async def _handle_skills_bins(params: dict | None, ctx: RpcContext) -> dict[str, bool]:
    """Return the availability status of required bins across all skills."""
    return skills_bins_rpc_payload(_get_loader(ctx))


@_d.method("skills.get", scope="operator.read")
async def _handle_skills_get(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Get a single skill by name, including its full content."""
    return skill_get_rpc_payload(params, _get_loader(ctx))


def _installed_names() -> set[str]:
    """Return the set of skill names currently recorded in the lockfile.

    Lockfile is the authoritative "installed via Community source" record —
    bundled or workspace skills with colliding names won't be mis-flagged
    as installed-from-ClawHub. Missing/corrupt lockfile returns an empty
    set (treat everything as not-yet-installed).
    """
    from opensquilla.paths import default_opensquilla_home
    from opensquilla.skills.hub.lockfile import Lockfile

    return set(Lockfile.load(default_opensquilla_home() / "skills-lock.json").installed.keys())


@_d.method("skills.search", scope="operator.read")
async def _handle_skills_search(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Search for skills across Community sources."""
    if not isinstance(params, dict) or "query" not in params:
        raise ValueError("params.query is required")

    router = getattr(ctx, "_skill_router", None)
    if router is None:
        router = _get_default_router()
    if router is None:
        return skills_search_unavailable_rpc_payload()

    query = params["query"]
    try:
        limit = min(int(params.get("limit", 20)), 100)
    except (TypeError, ValueError):
        limit = 20
    source_id = params.get("source")
    if source_id is not None and not isinstance(source_id, str):
        source_id = None
    results = await router.search(query, limit=limit, source_id=source_id)
    installed = _installed_names()
    # Lockfile keys are the installer's name — which for ClawHub is the
    # slug (``identifier``), not the human-readable ``displayName`` a
    # source may return as ``SkillMeta.name``. Check both so we catch
    # either convention; a future source that matches on name directly
    # still works.
    return skills_search_rpc_payload(results, installed)


def _invalidate_loader(ctx: RpcContext) -> None:
    """Drop the loader's in-memory cache so the next read re-scans disk.

    The disk snapshot has its own mtime/size manifest check, but the
    in-memory ``_cached`` field is populated at boot and would otherwise
    mask newly-installed (or removed) managed skills until the next
    restart.
    """
    loader = _get_loader(ctx)
    if loader is not None:
        loader.invalidate_cache()


@_d.method("skills.install", scope="operator.admin")
async def _handle_skills_install(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Install a skill from a Community source."""
    if not isinstance(params, dict) or "identifier" not in params:
        raise ValueError("params.identifier is required")
    if _get_loader(ctx) is None:
        return skill_install_unavailable_rpc_payload("No skill loader configured")

    installer = _get_default_installer()
    if installer is None:
        return skill_install_unavailable_rpc_payload("No skill installer configured")

    identifier = params["identifier"]
    source_id = params.get("source", "clawhub")
    force = params.get("force", False)
    result = await installer.install(identifier, source_id, force=force)
    if result.success:
        _invalidate_loader(ctx)
    return skill_install_result_rpc_payload(result)


@_d.method("skills.update", scope="operator.admin")
async def _handle_skills_update(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Update installed skills from lockfile."""
    if _get_loader(ctx) is None:
        return skills_update_empty_results_rpc_payload("No skill loader configured")
    installer = _get_default_installer()
    if installer is None:
        return skills_update_unavailable_rpc_payload("No skill installer configured")

    name = (params or {}).get("name")
    try:
        results = await installer.update(name)
    except OSError as exc:
        return skills_update_empty_results_rpc_payload(f"Skill update unavailable: {exc}")
    if any(r.success for r in results):
        _invalidate_loader(ctx)
    return skills_update_results_rpc_payload(results)


@_d.method("skills.uninstall", scope="operator.admin")
async def _handle_skills_uninstall(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Uninstall a managed skill."""
    if not isinstance(params, dict) or "name" not in params:
        raise ValueError("params.name is required")

    installer = _get_default_installer()
    if installer is None:
        return skill_uninstall_unavailable_rpc_payload("No skill installer configured")

    result = await installer.uninstall(params["name"])
    if result.success:
        _invalidate_loader(ctx)
    return skill_uninstall_result_rpc_payload(result)


@_d.method("skills.deps.install", scope="operator.admin")
async def _handle_skills_deps_install(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Install runtime dependencies for an already-loaded skill.

    Looks up the skill by name, finds the matching SkillInstallSpec by id in
    `metadata.install`, runs it via `install_deps`, then re-runs
    `diagnose_eligibility` and returns `missing_still` reflecting post-install state.

    Note: `kind == "download"` is non-idempotent — re-running re-downloads.
    Callers should consult `missing_still` before retrying.
    """
    if not isinstance(params, dict):
        raise ValueError("params must be a dict")
    if "name" not in params:
        raise ValueError("params.name is required")
    if "install_id" not in params:
        raise ValueError("params.install_id is required")

    name = params["name"]
    install_id = params["install_id"]
    loader = _get_loader(ctx)
    if loader is None:
        raise KeyError("No skill loader available")
    skill = loader.get_by_name(name)
    if skill is None:
        raise KeyError(f"Skill not found: {name}")

    specs = skill.metadata.install if skill.metadata else []
    spec = next((s for s in specs if s.id == install_id), None)
    if spec is None:
        raise KeyError(f"Install spec not found: {install_id}")

    validate_skill_install_supported(spec, install_id)

    async with _deps_lock_for(name, install_id):
        results = await install_deps([spec])
        r = results[0]
        missing_still = skill_missing_requirements_rpc_payload(skill)

    return skill_deps_install_result_rpc_payload(r, missing_still)


# ---------------------------------------------------------------------------
# Default router/installer (lazy init)
# ---------------------------------------------------------------------------

_default_router = None
_default_installer = None


def _get_default_router():
    global _default_router
    if _default_router is None:
        import os

        from opensquilla.skills.hub.clawhub import ClawHubSource
        from opensquilla.skills.hub.github import GitHubSource
        from opensquilla.skills.hub.router import SourceRouter

        sources = [
            ClawHubSource(token=os.environ.get("CLAWHUB_TOKEN")),
            GitHubSource(token=os.environ.get("GITHUB_TOKEN")),
        ]
        _default_router = SourceRouter(sources)
    return _default_router


def _get_default_installer():
    global _default_installer
    if _default_installer is None:
        router = _get_default_router()
        if router:
            from opensquilla.skills.hub.installer import SkillInstaller

            _default_installer = SkillInstaller(router=router)
    return _default_installer
