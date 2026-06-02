"""RPC handlers for per-session sandbox run context."""

from __future__ import annotations

from typing import Any

from opensquilla.agents.scope import resolve_agent_workspace_dir
from opensquilla.gateway.rpc import (
    RpcContext,
    RpcHandlerError,
    RpcUnavailableError,
    get_dispatcher,
)
from opensquilla.gateway.session_services import get_session_storage
from opensquilla.sandbox.package_bundles import expand_package_bundle
from opensquilla.sandbox.run_context import RunContext, get_run_context, set_run_mode
from opensquilla.sandbox.run_context_service import (
    add_domain_grant,
    add_mount_grant,
    disable_bundle_grant,
    enable_bundle_grant,
    remove_domain_grant,
    remove_mount_grant,
    set_workspace,
)
from opensquilla.sandbox.run_mode import display_name, execution_target, normalize_run_mode
from opensquilla.sandbox.status import status_payload
from opensquilla.session.keys import parse_agent_id

_d = get_dispatcher()


def _require_params(params: dict | None) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    return params


def _require_session_key(params: dict[str, Any]) -> str:
    session_key = params.get("sessionKey")
    if not isinstance(session_key, str) or not session_key:
        raise ValueError("params.sessionKey is required")
    return session_key


def _require_string_param(
    params: dict[str, Any],
    name: str,
    message: str,
) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)
    return value


def _require_one_string_param(
    params: dict[str, Any],
    names: tuple[str, ...],
    message: str,
) -> str:
    for name in names:
        value = params.get(name)
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError(message)


def _require_bundle_id(params: dict[str, Any]) -> str:
    bundle_id = _require_one_string_param(
        params,
        ("bundleId", "bundle_id"),
        "params.bundleId is required",
    )
    if not expand_package_bundle(bundle_id.strip()):
        raise ValueError("unknown_package_bundle")
    return bundle_id


def _require_session_manager(ctx: RpcContext) -> Any:
    manager = getattr(ctx, "session_manager", None)
    if manager is None:
        raise RpcUnavailableError("Session manager is not configured")
    return manager


def _require_owner(ctx: RpcContext, method: str) -> None:
    if not getattr(ctx.principal, "is_owner", False):
        raise RpcHandlerError("UNAUTHORIZED", f"{method} requires owner principal.")


async def _session_for_key(session_manager: Any, session_key: str) -> Any | None:
    get_session = getattr(session_manager, "get_session", None)
    if callable(get_session):
        return await get_session(session_key)

    storage = get_session_storage(session_manager)
    if storage is not None:
        return await storage.get_session(session_key)
    return None


async def _ensure_session_for_set(session_manager: Any, session_key: str) -> Any | None:
    session = await _session_for_key(session_manager, session_key)
    if session is not None:
        return session

    agent_id = parse_agent_id(session_key)
    get_or_create = getattr(session_manager, "get_or_create", None)
    if callable(get_or_create):
        result = await get_or_create(session_key, agent_id=agent_id)
        return result[0] if isinstance(result, tuple) else result

    create = getattr(session_manager, "create", None)
    if callable(create):
        return await create(session_key, agent_id=agent_id)
    return None


async def _workspace_for_session(
    session_manager: Any,
    session_key: str,
    config: Any,
) -> str | None:
    agent_id = parse_agent_id(session_key)
    session = await _session_for_key(session_manager, session_key)
    if session is None:
        raise KeyError(f"Session not found: {session_key}")
    session_agent_id = getattr(session, "agent_id", None)
    if isinstance(session_agent_id, str) and session_agent_id:
        agent_id = session_agent_id
    workspace = resolve_agent_workspace_dir(agent_id, config)
    return str(workspace) if workspace is not None else None


def _payload(context: RunContext) -> dict[str, Any]:
    origin_payload = context.to_origin_payload()
    return {
        "runMode": context.run_mode.value,
        "runModeLabel": display_name(context.run_mode),
        "executionTarget": execution_target(context.run_mode),
        "workspace": context.workspace,
        "mounts": origin_payload["mounts"],
        "domains": origin_payload["domains"],
        "bundles": origin_payload.get("bundles", []),
        "temporaryGrants": origin_payload.get("temporary_grants", []),
        "source": context.source,
    }


def _explain_messages(status: dict[str, Any]) -> list[dict[str, str]]:
    managed_network = str(status.get("managed_network", "blocked"))
    if managed_network == "ready":
        network_message = "Managed network allowlist is ready."
    else:
        network_message = "Managed network allowlist is blocked."
    return [
        {"kind": "run_mode", "message": f"Run mode is {status['run_mode']}."},
        {"kind": "managed_network", "message": network_message},
    ]


@_d.method("sandbox.status", scope="operator.read")
async def _handle_sandbox_status(params: dict | None, ctx: RpcContext) -> dict:
    return status_payload(ctx.config)


@_d.method("sandbox.explain", scope="operator.read")
async def _handle_sandbox_explain(params: dict | None, ctx: RpcContext) -> dict:
    params = params if isinstance(params, dict) else {}
    status = status_payload(ctx.config)
    result: dict[str, Any] = {
        "status": status,
        "messages": _explain_messages(status),
    }
    session_key = params.get("sessionKey")
    if isinstance(session_key, str) and session_key:
        manager = _require_session_manager(ctx)
        workspace = await _workspace_for_session(manager, session_key, ctx.config)
        context = await get_run_context(
            manager,
            session_key,
            config=ctx.config,
            workspace=workspace,
        )
        result["runContext"] = _payload(context)
    return result


@_d.method("sandbox.run_context.get", scope="operator.read")
async def _handle_sandbox_run_context_get(params: dict | None, ctx: RpcContext) -> dict:
    params = _require_params(params)
    session_key = _require_session_key(params)
    manager = _require_session_manager(ctx)
    workspace = await _workspace_for_session(manager, session_key, ctx.config)
    context = await get_run_context(
        manager,
        session_key,
        config=ctx.config,
        workspace=workspace,
    )
    return _payload(context)


@_d.method("sandbox.run_context.set", scope="operator.write")
async def _handle_sandbox_run_context_set(params: dict | None, ctx: RpcContext) -> dict:
    params = _require_params(params)
    session_key = _require_session_key(params)
    _require_owner(ctx, "sandbox.run_context.set")
    manager = _require_session_manager(ctx)
    session = await _ensure_session_for_set(manager, session_key)
    if session is None:
        raise KeyError(f"Session not found: {session_key}")
    run_mode = normalize_run_mode(params.get("runMode"))
    context = await set_run_mode(
        manager,
        session_key,
        run_mode,
        config=ctx.config,
        workspace=await _workspace_for_session(manager, session_key, ctx.config),
    )
    return _payload(context)


@_d.method("sandbox.mount.add", scope="operator.write")
async def _handle_sandbox_mount_add(params: dict | None, ctx: RpcContext) -> dict:
    params = _require_params(params)
    session_key = _require_session_key(params)
    _require_owner(ctx, "sandbox.mount.add")
    path = _require_string_param(params, "path", "params.path is required")
    manager = _require_session_manager(ctx)
    session = await _ensure_session_for_set(manager, session_key)
    if session is None:
        raise KeyError(f"Session not found: {session_key}")
    workspace = await _workspace_for_session(manager, session_key, ctx.config)
    context = await add_mount_grant(
        manager,
        session_key,
        path=path,
        access=str(params.get("access") or "ro"),
        scope=str(params.get("scope") or "chat"),
        config=ctx.config,
        workspace=workspace,
    )
    return _payload(context)


@_d.method("sandbox.mount.remove", scope="operator.write")
async def _handle_sandbox_mount_remove(params: dict | None, ctx: RpcContext) -> dict:
    params = _require_params(params)
    session_key = _require_session_key(params)
    _require_owner(ctx, "sandbox.mount.remove")
    path = _require_string_param(params, "path", "params.path is required")
    manager = _require_session_manager(ctx)
    session = await _ensure_session_for_set(manager, session_key)
    if session is None:
        raise KeyError(f"Session not found: {session_key}")
    workspace = await _workspace_for_session(manager, session_key, ctx.config)
    context = await remove_mount_grant(
        manager,
        session_key,
        path=path,
        config=ctx.config,
        workspace=workspace,
    )
    return _payload(context)


@_d.method("sandbox.domain.add", scope="operator.write")
async def _handle_sandbox_domain_add(params: dict | None, ctx: RpcContext) -> dict:
    params = _require_params(params)
    session_key = _require_session_key(params)
    _require_owner(ctx, "sandbox.domain.add")
    domain = _require_string_param(params, "domain", "params.domain is required")
    manager = _require_session_manager(ctx)
    session = await _ensure_session_for_set(manager, session_key)
    if session is None:
        raise KeyError(f"Session not found: {session_key}")
    workspace = await _workspace_for_session(manager, session_key, ctx.config)
    context = await add_domain_grant(
        manager,
        session_key,
        domain=domain,
        scope=str(params.get("scope") or "workspace"),
        config=ctx.config,
        workspace=workspace,
    )
    return _payload(context)


@_d.method("sandbox.domain.remove", scope="operator.write")
async def _handle_sandbox_domain_remove(params: dict | None, ctx: RpcContext) -> dict:
    params = _require_params(params)
    session_key = _require_session_key(params)
    _require_owner(ctx, "sandbox.domain.remove")
    domain = _require_string_param(params, "domain", "params.domain is required")
    manager = _require_session_manager(ctx)
    session = await _ensure_session_for_set(manager, session_key)
    if session is None:
        raise KeyError(f"Session not found: {session_key}")
    workspace = await _workspace_for_session(manager, session_key, ctx.config)
    context = await remove_domain_grant(
        manager,
        session_key,
        domain=domain,
        config=ctx.config,
        workspace=workspace,
    )
    return _payload(context)


@_d.method("sandbox.bundle.enable", scope="operator.write")
async def _handle_sandbox_bundle_enable(params: dict | None, ctx: RpcContext) -> dict:
    params = _require_params(params)
    session_key = _require_session_key(params)
    _require_owner(ctx, "sandbox.bundle.enable")
    bundle_id = _require_bundle_id(params)
    manager = _require_session_manager(ctx)
    session = await _ensure_session_for_set(manager, session_key)
    if session is None:
        raise KeyError(f"Session not found: {session_key}")
    workspace = await _workspace_for_session(manager, session_key, ctx.config)
    context = await enable_bundle_grant(
        manager,
        session_key,
        bundle_id=bundle_id,
        scope=str(params.get("scope") or "workspace"),
        config=ctx.config,
        workspace=workspace,
    )
    return _payload(context)


@_d.method("sandbox.bundle.disable", scope="operator.write")
async def _handle_sandbox_bundle_disable(params: dict | None, ctx: RpcContext) -> dict:
    params = _require_params(params)
    session_key = _require_session_key(params)
    _require_owner(ctx, "sandbox.bundle.disable")
    bundle_id = _require_bundle_id(params)
    manager = _require_session_manager(ctx)
    session = await _ensure_session_for_set(manager, session_key)
    if session is None:
        raise KeyError(f"Session not found: {session_key}")
    workspace = await _workspace_for_session(manager, session_key, ctx.config)
    context = await disable_bundle_grant(
        manager,
        session_key,
        bundle_id=bundle_id,
        config=ctx.config,
        workspace=workspace,
    )
    return _payload(context)


@_d.method("sandbox.workspace.set", scope="operator.write")
async def _handle_sandbox_workspace_set(params: dict | None, ctx: RpcContext) -> dict:
    params = _require_params(params)
    session_key = _require_session_key(params)
    _require_owner(ctx, "sandbox.workspace.set")
    workspace_path = _require_one_string_param(
        params,
        ("workspace", "workspacePath"),
        "params.workspace is required",
    )
    manager = _require_session_manager(ctx)
    session = await _ensure_session_for_set(manager, session_key)
    if session is None:
        raise KeyError(f"Session not found: {session_key}")
    current_workspace = await _workspace_for_session(manager, session_key, ctx.config)
    context = await set_workspace(
        manager,
        session_key,
        workspace_path=workspace_path,
        config=ctx.config,
        current_workspace=current_workspace,
    )
    return _payload(context)
