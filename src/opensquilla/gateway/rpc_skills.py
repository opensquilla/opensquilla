"""Skills domain RPC handlers (Tier 3 stubs)."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.skills.hub.defaults import (
    get_default_skill_installer,
    get_default_skill_router,
)
from opensquilla.skills.hub.deps import (
    install_loaded_skill_dependency,
    skill_deps_install_request,
)
from opensquilla.skills.hub.lockfile import installed_skill_names
from opensquilla.skills.hub.operations import (
    install_skill,
    skill_install_request,
    skill_uninstall_request,
    skills_update_request,
    uninstall_skill,
    update_skills,
)
from opensquilla.skills.rpc_payload import (
    skill_deps_install_result_rpc_payload,
    skill_get_rpc_payload,
    skill_install_result_rpc_payload,
    skill_install_unavailable_rpc_payload,
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
)

_d = get_dispatcher()


def _get_loader(ctx: RpcContext) -> Any | None:
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
    return skills_search_rpc_payload(results, installed_skill_names())


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
    request = skill_install_request(params)
    if _get_loader(ctx) is None:
        return skill_install_unavailable_rpc_payload("No skill loader configured")

    installer = _get_default_installer()
    if installer is None:
        return skill_install_unavailable_rpc_payload("No skill installer configured")

    result = await install_skill(installer, request)
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

    outcome = await update_skills(installer, skills_update_request(params))
    if outcome.unavailable_message:
        return skills_update_empty_results_rpc_payload(outcome.unavailable_message)
    if any(r.success for r in outcome.results):
        _invalidate_loader(ctx)
    return skills_update_results_rpc_payload(outcome.results)


@_d.method("skills.uninstall", scope="operator.admin")
async def _handle_skills_uninstall(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Uninstall a managed skill."""
    request = skill_uninstall_request(params)

    installer = _get_default_installer()
    if installer is None:
        return skill_uninstall_unavailable_rpc_payload("No skill installer configured")

    result = await uninstall_skill(installer, request)
    if result.success:
        _invalidate_loader(ctx)
    return skill_uninstall_result_rpc_payload(result)


@_d.method("skills.deps.install", scope="operator.admin")
async def _handle_skills_deps_install(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Install runtime dependencies for an already-loaded skill.

    The skills boundary owns request parsing, loaded-skill lookup,
    install-spec lookup, platform validation, per-spec serialization, and
    post-install missing-requirement reporting.
    """
    outcome = await install_loaded_skill_dependency(
        _get_loader(ctx),
        skill_deps_install_request(params),
    )
    return skill_deps_install_result_rpc_payload(outcome.result, outcome.missing_still)


def _get_default_router():
    return get_default_skill_router()


def _get_default_installer():
    return get_default_skill_installer()
