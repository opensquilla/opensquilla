"""Gateway session create/patch RPC behavior."""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from opensquilla.gateway.rpc import RpcContext, RpcHandlerError, RpcUnavailableError
from opensquilla.gateway.session_services import get_session_storage
from opensquilla.session.keys import canonicalize_session_key, normalize_agent_id
from opensquilla.session.rpc_payload import (
    session_agent_not_found_details,
    session_create_response,
    session_create_stub_response,
    session_patch_response,
)

log = structlog.get_logger(__name__)


def require_session_key(params: dict | None) -> str:
    if not isinstance(params, dict) or "key" not in params:
        raise ValueError("params.key is required")
    key = params["key"]
    if not isinstance(key, str):
        raise ValueError("params.key must be a string")
    return canonicalize_session_key(key)


def model_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def agent_registry_model(ctx: RpcContext, agent_id: str) -> str | None:
    registry = getattr(ctx, "agent_registry", None)
    getter = getattr(registry, "get_agent_model", None)
    if not callable(getter):
        return None
    try:
        return model_value(getter(agent_id))
    except Exception:  # noqa: BLE001 - registry lookup must not break legacy sessions
        log.warning("sessions.agent_model_lookup_failed", agent_id=agent_id)
        return None


async def agent_registry_has(ctx: RpcContext, agent_id: str) -> bool:
    """Return True iff *agent_id* exists in the registry (built-in main always True).

    Returns ``True`` when no registry is wired so legacy code paths that ran
    without an agent registry continue to work - the validation only kicks in
    when a registry is available to consult.
    """
    if normalize_agent_id(agent_id) == "main":
        return True
    registry = getattr(ctx, "agent_registry", None)
    lister = getattr(registry, "list_agents", None)
    if not callable(lister):
        return True
    try:
        agents = await lister(include_builtin=True)
    except Exception:  # noqa: BLE001 - never block session create on registry hiccups
        log.warning("sessions.agent_registry_list_failed", agent_id=agent_id)
        return True
    target = normalize_agent_id(agent_id)
    for entry in agents:
        if normalize_agent_id(str(entry.get("id", ""))) == target:
            return True
    return False


def session_turn_model(ctx: RpcContext, session: Any | None, agent_id: str) -> str | None:
    return model_value(getattr(session, "model", None)) or agent_registry_model(ctx, agent_id)


def create_session_key(agent_id: str, kind: object = None) -> str:
    short_id = uuid.uuid4().hex[:8]
    normalized_kind = str(kind or "").strip().lower().replace("_", "-")
    if normalized_kind == "web":
        normalized_kind = "webchat"
    if normalized_kind in {"cli", "webchat"}:
        return f"agent:{agent_id}:{normalized_kind}:{short_id}"
    return f"agent:{agent_id}:{short_id}"


async def handle_sessions_create(params: dict | None, ctx: RpcContext) -> dict:
    if not isinstance(params, dict):
        params = {}
    agent_id = normalize_agent_id(params.get("agentId", "main"))
    display_name = params.get("displayName")
    message = params.get("message")
    model = model_value(params.get("model")) or agent_registry_model(ctx, agent_id)
    kind = params.get("kind") or params.get("sessionKind")
    if message is not None and not isinstance(message, str):
        raise ValueError("params.message must be a string")

    if not await agent_registry_has(ctx, agent_id):
        raise RpcHandlerError(
            "agent.not_found",
            f"Agent '{agent_id}' does not exist",
            details=session_agent_not_found_details(agent_id),
        )

    if ctx.session_manager is None:
        if message:
            raise RpcUnavailableError("sessions.create(message=...) requires a session manager")
        key = create_session_key(agent_id, kind)
        return session_create_stub_response(key)

    session = await ctx.session_manager.create(
        session_key=create_session_key(agent_id, kind),
        agent_id=agent_id,
        display_name=display_name,
        model=model,
    )
    seeded_message = False

    if message:
        persisted = await ctx.session_manager.append_message(
            session.session_key,
            role="user",
            content=message,
        )
        if persisted is not None and isinstance(persisted.content, str):
            message = persisted.content
        seeded_message = True

    return session_create_response(session, seeded_message=seeded_message)


async def handle_sessions_patch(params: dict | None, ctx: RpcContext) -> dict:
    key = require_session_key(params)

    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    storage = get_session_storage(ctx.session_manager)
    if storage is None:
        raise KeyError("No session storage available")

    session = await storage.get_session(key)
    if session is None:
        raise KeyError(f"Session not found: {key}")

    update_values: dict[str, Any] = {}
    assert isinstance(params, dict)
    field_map = {
        "displayName": "display_name",
        "model": "model",
        "thinkingLevel": "thinking_level",
        "metadata": "meta",
    }
    updated_fields: list[str] = []
    for field, attr in field_map.items():
        if field in params and hasattr(session, attr):
            update_values[attr] = params[field]
            updated_fields.append(field)

    if update_values:
        update = getattr(ctx.session_manager, "update", None)
        if update is not None:
            await update(key, **update_values)
        else:
            for attr, value in update_values.items():
                setattr(session, attr, value)
            upsert = getattr(storage, "upsert_session", None)
            if upsert is not None:
                await upsert(session)

    return session_patch_response(key, updated_fields)
