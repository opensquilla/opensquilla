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
from opensquilla.sandbox.run_context import RunContext, get_run_context, set_run_mode
from opensquilla.sandbox.run_mode import display_name, execution_target, normalize_run_mode
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


def _require_session_manager(ctx: RpcContext) -> Any:
    manager = getattr(ctx, "session_manager", None)
    if manager is None:
        raise RpcUnavailableError("Session manager is not configured")
    return manager


async def _session_for_key(session_manager: Any, session_key: str) -> Any | None:
    get_session = getattr(session_manager, "get_session", None)
    if callable(get_session):
        return await get_session(session_key)

    storage = get_session_storage(session_manager)
    if storage is not None:
        return await storage.get_session(session_key)
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
        "source": context.source,
    }


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
    if not getattr(ctx.principal, "is_owner", False):
        raise RpcHandlerError(
            "UNAUTHORIZED",
            "sandbox.run_context.set requires owner principal.",
        )
    manager = _require_session_manager(ctx)
    run_mode = normalize_run_mode(params.get("runMode"))
    context = await set_run_mode(
        manager,
        session_key,
        run_mode,
        config=ctx.config,
        workspace=await _workspace_for_session(manager, session_key, ctx.config),
    )
    return _payload(context)
