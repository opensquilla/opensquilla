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
from opensquilla.skills.hub.operations import (
    run_skill_install_operation,
    run_skill_uninstall_operation,
    run_skills_update_operation,
    skill_install_request,
    skill_uninstall_request,
    skills_update_request,
)
from opensquilla.skills.hub.search import search_skills, skill_search_request
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
    router = getattr(ctx, "_skill_router", None)
    if router is None:
        router = _get_default_router()
    outcome = await search_skills(router, skill_search_request(params))
    if outcome.unavailable:
        return skills_search_unavailable_rpc_payload()
    return skills_search_rpc_payload(outcome.results, outcome.installed_names)


@_d.method("skills.install", scope="operator.admin")
async def _handle_skills_install(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Install a skill from a Community source."""
    outcome = await run_skill_install_operation(
        _get_loader(ctx),
        _get_default_installer,
        skill_install_request(params),
    )
    if outcome.result is None:
        return skill_install_unavailable_rpc_payload(outcome.unavailable_message)
    result = outcome.result
    return skill_install_result_rpc_payload(result)


@_d.method("skills.update", scope="operator.admin")
async def _handle_skills_update(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Update installed skills from lockfile."""
    outcome = await run_skills_update_operation(
        _get_loader(ctx),
        _get_default_installer,
        skills_update_request(params),
    )
    if outcome.unavailable_message:
        if outcome.unavailable_payload == "unavailable":
            return skills_update_unavailable_rpc_payload(outcome.unavailable_message)
        return skills_update_empty_results_rpc_payload(outcome.unavailable_message)
    return skills_update_results_rpc_payload(outcome.results)


@_d.method("skills.uninstall", scope="operator.admin")
async def _handle_skills_uninstall(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Uninstall a managed skill."""
    outcome = await run_skill_uninstall_operation(
        _get_loader(ctx),
        _get_default_installer,
        skill_uninstall_request(params),
    )
    if outcome.result is None:
        return skill_uninstall_unavailable_rpc_payload(outcome.unavailable_message)
    result = outcome.result
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
