"""RPC payload helpers for scheduler cron surfaces."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from opensquilla.scheduler.payloads import (
    AGENT_TURN_KIND,
    SYSTEM_EVENT_KIND,
    make_agent_turn_payload,
    make_system_event_payload,
    payload_agent_id,
    payload_kind,
    payload_text,
)
from opensquilla.scheduler.types import SessionTarget


def cron_job_to_wire(job: Any) -> dict[str, Any]:
    """Map an internal CronJob/dataclass/dict to the Cron UI wire format."""

    row = asdict(job) if hasattr(job, "__dataclass_fields__") else dict(job)
    status = row.get("status", "pending")
    status_str = status.value if hasattr(status, "value") else str(status)
    payload = row.get("payload") or {}
    session_target = str(row.get("session_target", "isolated"))
    wake_mode = row.get("wake_mode", "now")
    wake_mode_str = wake_mode.value if hasattr(wake_mode, "value") else str(wake_mode)
    delivery = None if session_target == "main" else row.get("delivery")
    text = payload_text(payload, session_target)
    kind = payload_kind(payload, session_target)
    return {
        "id": row.get("id"),
        "name": row.get("name", ""),
        "expression": row.get("schedule_raw") or row.get("cron_expr", ""),
        "prompt": text,
        "message": text,
        "text": text,
        "payloadKind": kind,
        "agentId": payload_agent_id(payload, "main"),
        "enabled": (
            bool(row.get("enabled", True))
            and status_str not in ("paused", "disabled", "deleted")
        ),
        "next_run": iso_datetime(row.get("next_run_at")),
        "last_run": iso_datetime(row.get("last_run_at")),
        "lastResult": row.get("last_error"),
        "run_count": row.get("run_count", 0),
        "error_count": row.get("error_count", 0),
        "created_at": iso_datetime(row.get("created_at")),
        "schedule_kind": str(row.get("schedule_kind", "cron")),
        "schedule_raw": row.get("schedule_raw", ""),
        "session_target": session_target,
        "sessionTarget": session_target,
        "targetSessionKey": row.get("session_key", ""),
        "originSessionKey": row.get("origin_session_key", ""),
        "timeout_seconds": row.get("timeout_seconds", 600),
        "wakeMode": wake_mode_str,
        "consecutive_errors": row.get("consecutive_errors", 0),
        "delivery": delivery_to_wire(delivery),
        "toolPolicy": tool_policy_to_wire(row.get("tool_policy")),
    }


def delivery_to_wire(delivery: Any) -> dict[str, Any]:
    if delivery is None:
        return {"mode": "none"}
    if isinstance(delivery, dict):
        return {
            "mode": delivery.get("mode", "none"),
            "channelName": delivery.get("channel_name", ""),
            "channelId": delivery.get("channel_id", ""),
            "accountId": delivery.get("account_id", ""),
            "threadId": delivery.get("thread_id", ""),
        }
    return {
        "mode": (
            getattr(delivery.mode, "value", str(delivery.mode))
            if hasattr(delivery, "mode")
            else "none"
        ),
        "channelName": getattr(delivery, "channel_name", ""),
        "channelId": getattr(delivery, "channel_id", ""),
        "accountId": getattr(delivery, "account_id", ""),
        "threadId": getattr(delivery, "thread_id", ""),
    }


def as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item) for item in value if str(item).strip()]
    raise ValueError("toolPolicy list fields must be strings or arrays")


def normalize_tool_policy(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("toolPolicy must be an object")
    result: dict[str, Any] = {}
    if "profile" in raw:
        profile = raw.get("profile")
        result["profile"] = None if profile is None else str(profile)
    for key in ("allow", "deny"):
        if key in raw:
            result[key] = as_string_list(raw.get(key))
    if "alsoAllow" in raw or "also_allow" in raw:
        result["also_allow"] = as_string_list(raw.get("alsoAllow", raw.get("also_allow")))
    return result


def tool_policy_from_params(params: dict[str, Any]) -> dict[str, Any]:
    if "toolPolicy" not in params and "tool_policy" not in params:
        return {}
    return normalize_tool_policy(params.get("toolPolicy", params.get("tool_policy")))


def tool_policy_to_wire(policy: Any) -> dict[str, Any]:
    normalized = normalize_tool_policy(policy or {})
    return {
        "profile": normalized.get("profile"),
        "allow": normalized.get("allow", []),
        "alsoAllow": normalized.get("also_allow", []),
        "deny": normalized.get("deny", []),
    }


def reply_target_snapshot_from_envelope(envelope: Any) -> Any | None:
    target = getattr(envelope, "reply_target", None)
    if target is None or getattr(target, "kind", None) != "channel":
        return None
    from opensquilla.scheduler.types import ReplyTargetSnapshot

    return ReplyTargetSnapshot(
        channel_name=getattr(target, "channel_name", "") or "",
        channel_type=getattr(target, "channel_type", "") or "",
        to=getattr(target, "to", "") or "",
        account_id=getattr(target, "account_id", "") or "",
        thread_id=getattr(target, "thread_id", "") or "",
        request_id=getattr(envelope, "session_id", None),
    )


def require_cron_add_params(params: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params required: expression, text")
    if "expression" not in params:
        raise ValueError("params.expression is required")
    return params


async def build_cron_add_job_kwargs(
    params: dict[str, Any] | None,
    *,
    session_storage: Any | None = None,
    originating_reply_target: Any | None = None,
) -> dict[str, Any]:
    params = require_cron_add_params(params)

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
    user_overrides = parse_delivery_overrides(delivery_raw)
    delivery = None

    if session_storage is not None and session_target != SessionTarget.MAIN:
        try:
            from opensquilla.scheduler.delivery import infer_delivery

            delivery = await infer_delivery(
                session_storage=session_storage,
                session_key=origin_session_key,
                user_overrides=user_overrides,
            )
        except Exception:
            pass
    if user_overrides is not None and delivery is None:
        from opensquilla.scheduler.types import DeliveryConfig, DeliveryMode

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
        and originating_reply_target is not None
    ):
        from opensquilla.scheduler.types import DeliveryConfig

        delivery = delivery or DeliveryConfig()
        delivery.originating_reply_target = originating_reply_target

    return {
        "name": params.get("name") or text,
        "schedule_raw": params.get("schedule") or params["expression"],
        "handler_key": "system_event" if payload_kind_name == SYSTEM_EVENT_KIND else "agent_run",
        "payload": payload,
        "session_target": session_target,
        "session_key": target_session_key,
        "timeout_seconds": float(params.get("timeout", 600)),
        "wake_mode": resolve_wake_mode(params),
        "delivery": delivery,
        "origin_session_key": origin_session_key,
        "tool_policy": tool_policy_from_params(params),
    }


def build_cron_update_patch(params: dict[str, Any], current_job: Any) -> dict[str, Any]:
    from opensquilla.scheduler.types import DeliveryConfig

    patch: dict[str, Any] = {}
    if "name" in params:
        patch["name"] = params["name"]

    if "expression" in params or "schedule" in params:
        patch["schedule_raw"] = params.get("schedule") or params.get("expression")

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
            current_delivery = current_job.delivery or DeliveryConfig()
            delivery_cls = type(current_delivery)
            mode_cls = type(current_delivery.mode)
            patch["delivery"] = delivery_cls(
                mode=mode_cls.CHANNEL,
                channel_name=delivery_raw["channelName"],
                channel_id=delivery_raw.get("channelId", ""),
                account_id=delivery_raw.get("accountId", ""),
                thread_id=delivery_raw.get("threadId", ""),
                ws_topic=current_delivery.ws_topic,
            )

    if "toolPolicy" in params or "tool_policy" in params:
        patch["tool_policy"] = tool_policy_from_params(params)

    return patch


def manual_run_to_wire(result: Any) -> dict[str, Any]:
    status = getattr(result, "status", "")
    status_str = status.value if hasattr(status, "value") else str(status)
    execution = getattr(result, "execution", None)
    if status_str == "accepted" and execution is not None:
        return {
            "success": execution.success,
            "status": status_str,
            "reply": execution.summary,
            "error": execution.error,
            "duration_ms": (
                int((execution.finished_at - execution.started_at).total_seconds() * 1000)
                if execution.finished_at and execution.started_at
                else None
            ),
        }

    body = {
        "success": False,
        "status": status_str or "blocked",
        "reason": getattr(result, "reason", "") or status_str,
        "error": getattr(result, "error", None),
    }
    current_status = getattr(result, "current_status", "")
    if current_status:
        body["currentStatus"] = current_status
    backoff_until = getattr(result, "backoff_until", None)
    if backoff_until is not None:
        body["backoffUntil"] = iso_datetime(backoff_until)
    return body


def cron_run_to_wire(run: Any) -> dict[str, Any]:
    return {
        "id": run.id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "success": run.success,
        "status": "ok" if run.success else "error",
        "duration_ms": (
            int((run.finished_at - run.started_at).total_seconds() * 1000)
            if run.started_at and run.finished_at
            else None
        ),
        "error": run.error,
        "summary": run.summary,
        "sessionKey": run.session_key or None,
        "deliveryStatus": run.delivery_status or None,
    }


def cron_subscription_error_response(error: str) -> dict[str, Any]:
    return {"ok": False, "error": error}


def cron_subscription_response(topic: str) -> dict[str, Any]:
    return {"ok": True, "topic": topic}


def iso_datetime(value: object) -> str | None:
    """Convert datetime-like values to ISO strings."""

    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def resolve_session_target(params: dict[str, Any]) -> SessionTarget:
    raw = params.get("sessionTarget")
    if isinstance(raw, str) and raw.strip():
        return SessionTarget(raw)
    payload_kind_param = params.get("payloadKind")
    if payload_kind_param == SYSTEM_EVENT_KIND:
        return SessionTarget.MAIN
    return SessionTarget.ISOLATED


def resolve_target_session_key(
    params: dict[str, Any],
    session_target: SessionTarget,
) -> str:
    if session_target == SessionTarget.MAIN:
        return (
            params.get("targetSessionKey")
            or params.get("target_session_key")
            or params.get("sessionKey")
            or params.get("session_key")
            or ""
        )
    if session_target in (SessionTarget.CURRENT, SessionTarget.SESSION):
        return (
            params.get("targetSessionKey")
            or params.get("target_session_key")
            or params.get("sessionKey")
            or params.get("session_key")
            or params.get("originSessionKey")
            or ""
        )
    return params.get("targetSessionKey") or params.get("target_session_key") or ""


def resolve_origin_session_key(params: dict[str, Any], session_target: SessionTarget) -> str:
    if session_target == SessionTarget.MAIN:
        return ""
    return (
        params.get("originSessionKey")
        or params.get("sessionKey")
        or params.get("session_key")
        or ""
    )


def resolve_wake_mode(params: dict[str, Any], current: Any = "now") -> str:
    raw = params.get("wakeMode", params.get("wake_mode", current))
    value = raw.value if hasattr(raw, "value") else str(raw or "now")
    value = value.strip().lower()
    if value not in {"now", "next-heartbeat"}:
        raise ValueError("wakeMode must be 'now' or 'next-heartbeat'")
    return value


def parse_delivery_overrides(delivery_raw: Any) -> dict[str, str] | None:
    if not isinstance(delivery_raw, dict) or not delivery_raw.get("channelName"):
        return None
    return {
        "channel_name": delivery_raw["channelName"],
        "channel_id": delivery_raw.get("channelId", ""),
        "account_id": delivery_raw.get("accountId", ""),
        "thread_id": delivery_raw.get("threadId", ""),
    }


def ensure_delivery_supported(
    *,
    session_target: SessionTarget,
    delivery_raw: Any,
) -> None:
    if session_target != SessionTarget.MAIN:
        return
    if isinstance(delivery_raw, dict) and delivery_raw.get("mode") == "none":
        return
    if parse_delivery_overrides(delivery_raw) is not None:
        raise ValueError(
            'cron channel delivery config is only supported for sessionTarget="isolated"'
        )


def build_cron_payload(
    params: dict[str, Any],
    session_target: SessionTarget,
    *,
    require_text: bool = True,
) -> tuple[str, dict[str, str]]:
    raw_text = params.get("text")
    if raw_text is None:
        raw_text = params.get("prompt")
    if raw_text is None:
        raw_text = params.get("message")
    text = raw_text if isinstance(raw_text, str) else ""
    kind = params.get("payloadKind")
    if not isinstance(kind, str) or not kind:
        kind = SYSTEM_EVENT_KIND if session_target == SessionTarget.MAIN else AGENT_TURN_KIND
    agent_id = params.get("agentId", "main")
    if require_text and not text.strip():
        raise ValueError("Cron text is required")
    if kind == SYSTEM_EVENT_KIND:
        if session_target != SessionTarget.MAIN:
            raise ValueError("payloadKind='system_event' requires sessionTarget='main'")
        return kind, make_system_event_payload(text, agent_id)
    if session_target == SessionTarget.MAIN:
        raise ValueError("payloadKind='agent_turn' cannot use sessionTarget='main'")
    return kind, make_agent_turn_payload(text, agent_id)


__all__ = [
    "as_string_list",
    "build_cron_payload",
    "build_cron_add_job_kwargs",
    "build_cron_update_patch",
    "cron_job_to_wire",
    "cron_run_to_wire",
    "cron_subscription_error_response",
    "cron_subscription_response",
    "delivery_to_wire",
    "ensure_delivery_supported",
    "iso_datetime",
    "manual_run_to_wire",
    "normalize_tool_policy",
    "parse_delivery_overrides",
    "reply_target_snapshot_from_envelope",
    "require_cron_add_params",
    "resolve_origin_session_key",
    "resolve_session_target",
    "resolve_target_session_key",
    "resolve_wake_mode",
    "tool_policy_from_params",
    "tool_policy_to_wire",
]
