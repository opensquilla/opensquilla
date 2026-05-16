"""RPC handlers for the chat domain — wired to sessions engine bridge."""

from __future__ import annotations

from typing import cast

import structlog

from opensquilla.artifacts import artifact_payload
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.context_overflow import apply_context_overflow_policy
from opensquilla.gateway.rpc import RpcContext, RpcUnavailableError, get_dispatcher
from opensquilla.session.compaction import build_compaction_config_from_provider
from opensquilla.session.keys import build_webchat_key, canonicalize_session_key
from opensquilla.session.rpc_payload import (
    chat_abort_response,
    chat_abort_unavailable_response,
    chat_history_response,
    chat_inject_response,
    chat_send_instant_accept_response,
    chat_send_refusal_response,
    chat_send_response,
)

_d = get_dispatcher()
log = structlog.get_logger(__name__)

_WEBCHAT_SESSION_KEY = build_webchat_key()


def _canonical_webchat_session_key(value: object = None) -> str:
    """Map legacy WebChat defaults onto the canonical WebChat session."""
    raw = str(value or "").strip()
    if not raw or raw in {"default", "webchat:default", "unknown"}:
        return _WEBCHAT_SESSION_KEY
    if raw.startswith("sess-"):
        return f"agent:main:webchat:{raw[len('sess-') :]}"
    return canonicalize_session_key(raw)


def _require_chat_session_manager(ctx: RpcContext):
    if ctx.session_manager is None:
        raise RpcUnavailableError("Chat session manager not available")
    return ctx.session_manager


def _effective_compaction_model(session: object | None) -> str | None:
    if session is None:
        return None
    return getattr(session, "model_override", None) or getattr(session, "model", None)


def _resolve_compaction_provider(ctx: RpcContext, session: object | None) -> object | None:
    selector = getattr(ctx, "provider_selector", None)
    if selector is None:
        return None

    resolved_selector = selector
    clone = getattr(selector, "clone", None)
    if callable(clone):
        try:
            resolved_selector = clone()
        except Exception:  # noqa: BLE001
            resolved_selector = selector

    model = _effective_compaction_model(session)
    if model and resolved_selector is not selector:
        override = getattr(resolved_selector, "override_model", None)
        if callable(override):
            try:
                override(model)
            except Exception:  # noqa: BLE001
                pass

    resolver = getattr(resolved_selector, "resolve", None)
    if not callable(resolver):
        return None
    try:
        return cast(object | None, resolver())
    except Exception:  # noqa: BLE001
        return None


async def _build_context_overflow_compaction_config(ctx: RpcContext, session_key: str):
    session = None
    storage = getattr(getattr(ctx, "session_manager", None), "_storage", None)
    if storage is not None:
        try:
            session = await storage.get_session(session_key)
        except Exception:  # noqa: BLE001
            session = None
    return build_compaction_config_from_provider(
        _resolve_compaction_provider(ctx, session),
        model_override=_effective_compaction_model(session),
        compaction_config=getattr(getattr(ctx, "config", None), "compaction", None),
    )


async def _enforce_context_overflow(
    ctx: RpcContext,
    session_key: str,
    message: str,
) -> dict | None:
    """Apply the configured context-overflow policy before a turn runs.

    Returns a stable error envelope when the policy is REFUSE and the
    payload exceeds the budget; returns ``None`` for every other path
    (policy consults pass, HARD_TRUNCATE dropped some history in place,
    AUTO_SUMMARIZE kicked off a compaction). The caller short-circuits
    on a non-None return.
    """

    config = ctx.config if isinstance(ctx.config, GatewayConfig) else GatewayConfig()

    transcript: list = []
    if ctx.session_manager is not None:
        try:
            transcript = list(await ctx.session_manager.get_transcript(session_key))
        except Exception:  # noqa: BLE001 — missing transcript just means "no history"
            transcript = []

    # Per-session context-budget overrides are independent from runtime/request
    # timeout resolution, which happens in TurnRunner.
    # A session-scoped context_budget_tokens override is supported via
    # ctx.session_manager.get_config(session_key) if present.
    budget_override = None
    policy_override = None
    if ctx.session_manager is not None and hasattr(ctx.session_manager, "get_session_config"):
        try:
            session_cfg = await ctx.session_manager.get_session_config(session_key)
            if session_cfg is not None:
                budget_override = getattr(session_cfg, "context_budget_tokens", None)
                policy_override = getattr(session_cfg, "context_overflow_policy", None)
        except Exception:  # noqa: BLE001
            pass

    outcome = await apply_context_overflow_policy(
        config=config,
        message=message,
        transcript=transcript,
        session_key=session_key,
        session_manager=ctx.session_manager,
        compaction_config=await _build_context_overflow_compaction_config(ctx, session_key),
        policy_override=policy_override,
        budget_override=budget_override,
    )

    if outcome.refusal is not None:
        log.warning(
            "chat_send.context_overflow_refused",
            session_key=session_key,
            estimated_tokens=outcome.estimated_tokens,
            budget_tokens=outcome.budget_tokens,
        )
        return outcome.refusal

    return None


@_d.method("chat.send", scope="operator.write")
async def _handle_chat_send(params: dict | None, ctx: RpcContext) -> dict:
    if not isinstance(params, dict) or "message" not in params:
        raise ValueError("params.message is required")

    message = params["message"]
    session_key = _canonical_webchat_session_key(params.get("sessionKey"))

    # Fresh-WebUI / smoke path: when no session manager is wired (webui
    # simulator, dispatcher-only boot), instant-accept without kicking off a
    # turn. This matches the roundtrip the WebUI observes on first paint
    # before the sessions engine is attached.
    if ctx.session_manager is None:
        return chat_send_instant_accept_response(session_key)

    mgr = _require_chat_session_manager(ctx)
    intent = params.get("intent")

    # Gate the turn on the configured context-overflow policy.
    refusal = await _enforce_context_overflow(ctx, session_key, message)
    if refusal is not None:
        return chat_send_refusal_response(session_key, refusal)

    if intent != "new_chat":
        # Ensure session exists — auto-create if needed
        try:
            await mgr.get_or_create(
                session_key=session_key,
                agent_id="main",
                display_name="WebChat",
            )
        except Exception as exc:
            raise RpcUnavailableError(f"Failed to initialize chat session: {exc}") from exc

    from opensquilla.gateway.rpc_sessions import _handle_sessions_send

    incoming_source = params.get("_source")
    if not isinstance(incoming_source, dict):
        incoming_source = {}

    send_params: dict = {
        "key": session_key,
        "message": message,
        "_source": {
            "caller_kind": "web",
            "channel_kind": "webchat",
            "channel_id": f"webchat:{session_key}",
            "sender_id": ctx.principal.role,
            "source_kind": "webui",
            "source_name": "WebChat",
        },
    }
    elevated_hint = incoming_source.get("elevated")
    if elevated_hint in ("on", "bypass", "full"):
        send_params["_source"]["elevated"] = elevated_hint
    attachments = params.get("attachments")
    if attachments:
        send_params["attachments"] = attachments
    if intent is not None:
        send_params["intent"] = intent
    for source_key, target_key in (
        ("noMemoryCapture", "noMemoryCapture"),
        ("no_memory_capture", "no_memory_capture"),
        ("inputProvenance", "inputProvenance"),
        ("input_provenance", "input_provenance"),
        ("inputProvenanceKind", "inputProvenanceKind"),
        ("input_provenance_kind", "input_provenance_kind"),
        ("provenance_kind", "provenance_kind"),
        ("runKind", "runKind"),
        ("run_kind", "run_kind"),
    ):
        if source_key in params:
            send_params[target_key] = params[source_key]
    result = await _handle_sessions_send(send_params, ctx)
    return chat_send_response(session_key, result)


@_d.method("chat.abort", scope="operator.write")
async def _handle_chat_abort(params: dict | None, ctx: RpcContext) -> dict:
    session_key = _canonical_webchat_session_key((params or {}).get("sessionKey"))
    # Fresh-WebUI / smoke path: abort always returns an ok envelope keyed by
    # sessionKey, regardless of whether a live task exists to cancel.
    if ctx.session_manager is None:
        return chat_abort_unavailable_response(session_key)
    _require_chat_session_manager(ctx)
    from opensquilla.gateway.rpc_sessions import _handle_sessions_abort

    result = await _handle_sessions_abort({"key": session_key}, ctx)
    return chat_abort_response(session_key, result)


@_d.method("chat.history", scope="operator.read")
async def _handle_chat_history(params: dict | None, ctx: RpcContext) -> dict:
    session_key = _canonical_webchat_session_key((params or {}).get("sessionKey"))
    limit = (params or {}).get("limit", 50)

    mgr = _require_chat_session_manager(ctx)

    transcript = await mgr.get_transcript(session_key)
    return chat_history_response(transcript, limit=limit, artifact_payload_fn=artifact_payload)


@_d.method("chat.inject", scope="operator.admin")
async def _handle_chat_inject(params: dict | None, ctx: RpcContext) -> dict:
    if not isinstance(params, dict):
        raise ValueError("params required: sessionKey, role, content")
    for field in ("sessionKey", "role", "content"):
        if field not in params:
            raise ValueError(f"params.{field} is required")

    role = params["role"]
    if role not in ("user", "assistant", "system"):
        raise ValueError(f"Invalid role: {role}")

    session_key = _canonical_webchat_session_key(params["sessionKey"])

    if ctx.session_manager is None:
        raise KeyError("No session manager available")

    storage = getattr(ctx.session_manager, "_storage", None)
    if storage is not None:
        existing = await storage.get_session(session_key)
        if existing is None:
            raise KeyError(f"Session not found: {session_key}")

    await ctx.session_manager.append_message(session_key, role=role, content=params["content"])
    return chat_inject_response(session_key)
