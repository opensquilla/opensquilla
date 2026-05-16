"""Cron domain RPC handlers (Tier 2)."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, RpcUnavailableError, get_dispatcher
from opensquilla.scheduler.payloads import (
    SYSTEM_EVENT_KIND,
    payload_agent_id,
    payload_kind,
    payload_text,
)
from opensquilla.scheduler.rpc_payload import (
    build_cron_payload,
    cron_job_to_wire,
    cron_run_to_wire,
    cron_subscription_error_response,
    cron_subscription_response,
    ensure_delivery_supported,
    manual_run_to_wire,
    parse_delivery_overrides,
    resolve_origin_session_key,
    resolve_session_target,
    resolve_target_session_key,
    resolve_wake_mode,
    tool_policy_from_params,
)
from opensquilla.scheduler.types import (
    DeliveryConfig,
    DeliveryMode,
    ReplyTargetSnapshot,
    SessionTarget,
)

_d = get_dispatcher()


def _require_scheduler(ctx: RpcContext) -> Any:
    scheduler = getattr(ctx, "cron_scheduler", None)
    if scheduler is None:
        raise RpcUnavailableError("Cron scheduler is not available")
    return scheduler


def _originating_reply_target(ctx: RpcContext) -> ReplyTargetSnapshot | None:
    envelope = getattr(ctx, "originating_envelope", None)
    target = getattr(envelope, "reply_target", None)
    if target is None or getattr(target, "kind", None) != "channel":
        return None
    return ReplyTargetSnapshot(
        channel_name=getattr(target, "channel_name", "") or "",
        channel_type=getattr(target, "channel_type", "") or "",
        to=getattr(target, "to", "") or "",
        account_id=getattr(target, "account_id", "") or "",
        thread_id=getattr(target, "thread_id", "") or "",
        request_id=getattr(envelope, "session_id", None),
    )


@_d.method("cron.list", scope="operator.read")
async def _handle_cron_list(params: dict | None, ctx: RpcContext) -> list[dict]:
    scheduler = getattr(ctx, "cron_scheduler", None)
    if scheduler is None:
        return []
    jobs = await scheduler.list_jobs()
    result = [cron_job_to_wire(j) for j in jobs]
    agent_id = (params or {}).get("agentId")
    if agent_id:
        result = [j for j in result if j.get("agentId") == agent_id]
    return result


@_d.method("cron.status", scope="operator.read")
async def _handle_cron_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")
    scheduler = _require_scheduler(ctx)
    job = await scheduler.get_job(params["id"])
    if job is None:
        raise KeyError(f"Cron job not found: {params['id']}")
    return cron_job_to_wire(job)


@_d.method("cron.add", scope="operator.admin")
async def _handle_cron_add(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params required: expression, text")
    if "expression" not in params:
        raise ValueError("params.expression is required")
    session_target = resolve_session_target(params)
    payload_kind_name, payload = build_cron_payload(
        params,
        session_target,
        require_text=True,
    )
    text = payload_text(payload, session_target)
    target_session_key = resolve_target_session_key(params, session_target)
    origin_session_key = resolve_origin_session_key(params, session_target)
    delivery_raw = params.get("delivery")
    ensure_delivery_supported(session_target=session_target, delivery_raw=delivery_raw)
    scheduler = _require_scheduler(ctx)
    # Infer or parse delivery config
    user_overrides = parse_delivery_overrides(delivery_raw)

    delivery = None
    try:
        from opensquilla.scheduler.delivery import infer_delivery

        sm = getattr(ctx, "session_manager", None)
        if sm is not None and session_target != SessionTarget.MAIN:
            storage = getattr(sm, "_storage", sm)
            sk = origin_session_key
            delivery = await infer_delivery(
                session_storage=storage,
                session_key=sk,
                user_overrides=user_overrides,
            )
    except Exception:
        pass
    if user_overrides is not None and delivery is None:
        delivery = DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name=user_overrides["channel_name"],
            channel_id=user_overrides["channel_id"],
            account_id=user_overrides["account_id"],
            thread_id=user_overrides["thread_id"],
        )
    elif (
        session_target != SessionTarget.MAIN
        and user_overrides is None
        and (snapshot := _originating_reply_target(ctx)) is not None
    ):
        delivery = delivery or DeliveryConfig()
        delivery.originating_reply_target = snapshot

    job = await scheduler.add_job(
        name=params.get("name") or text,
        schedule_raw=params.get("schedule") or params["expression"],
        handler_key="system_event" if payload_kind_name == SYSTEM_EVENT_KIND else "agent_run",
        payload=payload,
        session_target=session_target,
        session_key=target_session_key,
        timeout_seconds=float(params.get("timeout", 600)),
        wake_mode=resolve_wake_mode(params),
        delivery=delivery,
        origin_session_key=origin_session_key,
        tool_policy=tool_policy_from_params(params),
    )
    # Populate ws_topic
    if job.delivery and not job.delivery.ws_topic:
        job.delivery.ws_topic = f"cron:{job.id}"
        try:
            await scheduler.update_job(job.id, delivery=job.delivery)
        except Exception:
            pass
    return cron_job_to_wire(job)


# Alias: cron.js sends cron.create for new jobs
_d.method("cron.create", scope="operator.admin")(_handle_cron_add)


@_d.method("cron.update", scope="operator.admin")
async def _handle_cron_update(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")
    scheduler = _require_scheduler(ctx)

    patch = {}
    if "name" in params:
        patch["name"] = params["name"]

    if "expression" in params or "schedule" in params:
        patch["schedule_raw"] = params.get("schedule") or params.get("expression")

    if "enabled" in params:
        if params["enabled"]:
            # If currently paused, resume
            job = await scheduler.get_job(params["id"])
            if job and job.status.value == "paused":
                job = await scheduler.resume_job(params["id"])
                return cron_job_to_wire(job) if job else {}
        else:
            job = await scheduler.pause_job(params["id"])
            return cron_job_to_wire(job) if job else {}

    current_job = await scheduler.get_job(params["id"])
    if current_job is None:
        raise KeyError(f"Cron job not found: {params['id']}")

    payload_related = any(
        key in params
        for key in (
            "text",
            "prompt",
            "message",
            "payloadKind",
            "agentId",
            "sessionTarget",
            "targetSessionKey",
            "target_session_key",
            "originSessionKey",
            "sessionKey",
            "session_key",
        )
    )
    if payload_related:
        current_text = payload_text(current_job.payload, current_job.session_target)
        merged_params = {
            "text": params.get(
                "text",
                params.get("prompt", params.get("message", current_text)),
            ),
            "payloadKind": params.get(
                "payloadKind",
                payload_kind(current_job.payload, current_job.session_target),
            ),
            "agentId": params.get("agentId", payload_agent_id(current_job.payload)),
            "sessionTarget": params.get(
                "sessionTarget",
                getattr(current_job.session_target, "value", str(current_job.session_target)),
            ),
            "originSessionKey": params.get(
                "originSessionKey",
                params.get(
                    "sessionKey",
                    params.get("session_key", current_job.origin_session_key),
                ),
            ),
        }
        session_target = resolve_session_target(merged_params)
        if session_target == SessionTarget.MAIN:
            merged_params["targetSessionKey"] = params.get(
                "targetSessionKey",
                params.get(
                    "target_session_key",
                    params.get(
                        "sessionKey",
                        params.get("session_key", current_job.session_key),
                    ),
                ),
            )
        else:
            merged_params["targetSessionKey"] = params.get(
                "targetSessionKey",
                params.get("target_session_key", current_job.session_key),
            )
        payload_kind_name, payload = build_cron_payload(
            merged_params,
            session_target,
            require_text=False,
        )
        patch["handler_key"] = (
            "system_event" if payload_kind_name == SYSTEM_EVENT_KIND else "agent_run"
        )
        patch["payload"] = payload
        patch["session_target"] = session_target
        patch["session_key"] = resolve_target_session_key(merged_params, session_target)
        patch["origin_session_key"] = resolve_origin_session_key(
            merged_params,
            session_target,
        )
        if session_target == SessionTarget.MAIN and "delivery" not in params:
            patch["delivery"] = DeliveryConfig()

    if "timeout" in params:
        patch["timeout_seconds"] = float(params["timeout"])

    if "wakeMode" in params or "wake_mode" in params:
        patch["wake_mode"] = resolve_wake_mode(
            params,
            getattr(current_job, "wake_mode", "now"),
        )

    if "delivery" in params:
        delivery_raw = params.get("delivery")
        effective_target = patch.get("session_target", current_job.session_target)
        ensure_delivery_supported(session_target=effective_target, delivery_raw=delivery_raw)
        if isinstance(delivery_raw, dict) and delivery_raw.get("mode") == "none":
            patch["delivery"] = DeliveryConfig()
        elif isinstance(delivery_raw, dict) and delivery_raw.get("channelName"):
            patch["delivery"] = type(current_job.delivery)(
                mode=type(current_job.delivery.mode).CHANNEL,
                channel_name=delivery_raw["channelName"],
                channel_id=delivery_raw.get("channelId", ""),
                account_id=delivery_raw.get("accountId", ""),
                thread_id=delivery_raw.get("threadId", ""),
                ws_topic=current_job.delivery.ws_topic,
            )

    if "toolPolicy" in params or "tool_policy" in params:
        patch["tool_policy"] = tool_policy_from_params(params)

    if patch:
        job = await scheduler.update_job(params["id"], **patch)
    else:
        job = current_job
    if job is None:
        raise KeyError(f"Cron job not found: {params['id']}")
    return cron_job_to_wire(job)


@_d.method("cron.remove", scope="operator.admin")
async def _handle_cron_remove(params: dict | None, ctx: RpcContext) -> None:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")
    scheduler = _require_scheduler(ctx)
    await scheduler.remove_job(params["id"])
    return None


@_d.method("cron.run", scope="operator.admin")
async def _handle_cron_run(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict) or "id" not in params:
        raise ValueError("params.id is required")
    scheduler = _require_scheduler(ctx)
    result = await scheduler.run_job_now(params["id"])
    return manual_run_to_wire(result)


@_d.method("cron.runs", scope="operator.read")
async def _handle_cron_runs(params: dict | None, ctx: RpcContext) -> list[dict]:
    if not isinstance(params, dict):
        raise ValueError("params.id is required")
    job_id = params.get("id") or params.get("job_id")
    if not job_id:
        raise ValueError("params.id is required")
    limit = params.get("limit", 20)
    scheduler = getattr(ctx, "cron_scheduler", None)
    if scheduler is None:
        return []
    runs = await scheduler.get_runs(job_id, limit=limit)
    return [cron_run_to_wire(run) for run in runs]


@_d.method("cron.subscribe", scope="operator.read")
async def _handle_cron_subscribe(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Subscribe this connection to cron events."""
    sub_mgr = getattr(ctx, "subscription_manager", None)
    if sub_mgr is None:
        return cron_subscription_error_response("subscription_manager not available")
    conn_id = getattr(ctx, "conn_id", None)
    if not conn_id:
        return cron_subscription_error_response("no connection context")
    job_id = (params or {}).get("jobId")
    topic = f"cron:{job_id}" if job_id else "cron:*"
    sub_mgr.subscribe_topic(conn_id, topic)
    return cron_subscription_response(topic)


@_d.method("cron.unsubscribe", scope="operator.read")
async def _handle_cron_unsubscribe(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Unsubscribe this connection from cron events."""
    sub_mgr = getattr(ctx, "subscription_manager", None)
    if sub_mgr is None:
        return cron_subscription_error_response("subscription_manager not available")
    conn_id = getattr(ctx, "conn_id", None)
    if not conn_id:
        return cron_subscription_error_response("no connection context")
    job_id = (params or {}).get("jobId")
    topic = f"cron:{job_id}" if job_id else "cron:*"
    sub_mgr.unsubscribe_topic(conn_id, topic)
    return cron_subscription_response(topic)
