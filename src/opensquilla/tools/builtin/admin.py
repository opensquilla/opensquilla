"""Admin tools: cron scheduler and gateway control."""

from __future__ import annotations

import json
from typing import Any, Protocol

import structlog

from opensquilla.scheduler.payloads import (
    REMINDER_KIND,
    SYSTEM_EVENT_KIND,
    make_agent_turn_payload,
    make_reminder_payload,
    make_system_event_payload,
)
from opensquilla.scheduler.prompt_safety import scan_cron_prompt as _scan_cron_prompt
from opensquilla.scheduler.schedule_normalizer import coerce_schedule_from_params
from opensquilla.scheduler.types import (
    DeliveryConfig,
    DeliveryMode,
    ReplyTargetSnapshot,
    ScheduleKind,
    SessionTarget,
)
from opensquilla.tools.registry import tool
from opensquilla.tools.types import ToolError

log = structlog.get_logger(__name__)

_VALID_CRON_ACTIONS = ("list", "add", "remove", "run")


_VALID_GATEWAY_ACTIONS = ("restart", "config_get", "config_set")


class _SchedulerProtocol(Protocol):
    async def list_jobs(self) -> list[Any]: ...

    async def add_job(
        self,
        name: str,
        *,
        schedule_kind: Any,
        schedule_value: str,
        schedule_tz: str = "",
        handler_key: str = "agent_run",
        payload: dict[Any, Any] | None = None,
        session_target: SessionTarget = SessionTarget.ISOLATED,
        session_key: str = "",
        timeout_seconds: float = 600.0,
        wake_mode: Any = "now",
        max_retries: int = 3,
        origin_session_key: str = "",
        delivery: DeliveryConfig | None = None,
        tool_policy: dict[str, Any] | None = None,
        tz: str = "",
        jitter_seconds: float | None = None,
        creator_session_key: str = "",
        creator_sender_id: str = "",
        creator_is_owner: bool = False,
    ) -> Any: ...

    async def update_job(self, job_id: str, **patch: Any) -> Any: ...

    async def get_job(self, job_id: str) -> Any | None: ...

    async def remove_job(self, job_id: str) -> bool: ...

    async def run_job_now(self, job_id: str) -> Any: ...


# Setter-injected dependencies (gateway boot calls these)
_scheduler: _SchedulerProtocol | None = None
_gateway_config = None


def set_scheduler(engine: _SchedulerProtocol) -> None:
    """Inject the SchedulerEngine (called from gateway boot)."""
    global _scheduler
    _scheduler = engine


def set_gateway_config(config: object) -> None:
    """Inject the GatewayConfig (called from gateway boot)."""
    global _gateway_config
    _gateway_config = config


def scheduler_available() -> bool:
    return _scheduler is not None


def gateway_config_available() -> bool:
    return _gateway_config is not None


# ---------------------------------------------------------------------------
# cron
# ---------------------------------------------------------------------------


def _coerce_tool_schedule(
    schedule: Any,
    *,
    tz: str = "",
) -> tuple[ScheduleKind, str, str]:
    """Validate the structured `schedule` param from the LLM tool call.

    Returns ``(ScheduleKind, schedule_value, schedule_tz)`` ready for
    ``add_job(schedule_kind=..., schedule_value=..., schedule_tz=...)``.

    Raises ``ToolError`` whose message names the offending field and shows the
    accepted shape so the model can self-correct on the next turn.
    """
    if not isinstance(schedule, dict):
        raise ToolError(
            "schedule must be an object with shape "
            "{kind: 'cron'|'every'|'at', ...}; "
            f"got {type(schedule).__name__}"
        )
    try:
        return coerce_schedule_from_params({"schedule": schedule, "tz": tz})
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _owns_cron_job(job: Any, sender_id: str, session_key: str) -> bool:
    """Caller-ownership test for non-owner cron actions.

    Prefer the stable channel sender_id; fall back to session_key for jobs
    created before sender_id tracking existed (or for non-channel sessions).
    """
    job_sender = (getattr(job, "creator_sender_id", "") or "")
    job_session = (getattr(job, "creator_session_key", "") or "")
    if sender_id and job_sender:
        return job_sender == sender_id
    if session_key and job_session:
        return job_session == session_key
    return False


@tool(
    name="cron",
    description=(
        "Create, list, remove, or trigger scheduled cron jobs. "
        "Use this tool (NOT exec_command or background_process) for any recurring/timed "
        "task scheduling or reminders."
    ),
    params={
        "action": {
            "type": "string",
            "description": "Action: list, add, remove, run",
        },
        "schedule": {
            "type": "object",
            "description": (
                "Structured schedule. Choose one shape. "
                "Do not pass human language in schedule; translate it before the tool call. "
                "Examples: "
                "for '每5分钟提醒我喝水' call schedule={kind:'cron', expr:'*/5 * * * *'}, "
                "job_kind='reminder', session_target='isolated'; "
                "for '45分钟后提醒我' call "
                "schedule={kind:'at', at:'<now+45min as ISO-8601 with timezone>'}; "
                "for '每30秒打印一次' call schedule={kind:'every', every_seconds:30}; "
                "for 'every weekday at 9 AM Shanghai time' call "
                "schedule={kind:'cron', expr:'0 9 * * 1-5', tz:'Asia/Shanghai'}."
            ),
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["cron", "every", "at"],
                },
                "expr": {
                    "type": "string",
                    "description": "5-field POSIX cron (kind=cron)",
                },
                "tz": {
                    "type": "string",
                    "description": "Optional IANA timezone (kind=cron)",
                },
                "every_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Interval in seconds (kind=every)",
                },
                "at": {
                    "type": "string",
                    "description": "ISO-8601 with timezone (kind=at)",
                },
            },
            "required": ["kind"],
        },
        "task": {
            "type": "string",
            "description": "Message to execute on trigger (required for add)",
        },
        "job_kind": {
            "type": "string",
            "description": (
                "Use reminder for static user-facing reminders; it does not call "
                "the model. Use agent_turn only for scheduled background tasks "
                "that need the agent/model to work. Use system_event only for "
                "internal main-session events."
            ),
            "enum": ["reminder", "system_event", "agent_turn"],
        },
        "session_target": {
            "type": "string",
            "description": (
                "Target session mode for add. Use main for internal system events, "
                "isolated for proactive reminders that should deliver back to the "
                "caller, current only when the user explicitly wants the scheduled "
                "run to continue the current transcript as a conversation, or session "
                "with target_session_key for a named session."
            ),
            "enum": ["main", "isolated", "current", "session"],
        },
        "target_session_key": {
            "type": "string",
            "description": "Named session key when session_target=session.",
        },
        "job_id": {
            "type": "string",
            "description": "Job ID (required for remove and run)",
        },
        "agent_id": {
            "type": "string",
            "description": "Agent to run the task as (for add)",
            "default": "main",
        },
        "wake_mode": {
            "type": "string",
            "description": (
                "Main-session heartbeat mode: now runs one "
                "heartbeat immediately; next-heartbeat only queues a wake."
            ),
            "enum": ["now", "next-heartbeat"],
            "default": "now",
        },
        "tool_policy": {
            "type": "object",
            "description": (
                "Optional per-job cron tool policy with profile, allow, also_allow, and deny."
            ),
        },
        "tz": {
            "type": "string",
            "description": (
                "Optional IANA timezone (e.g. 'America/Los_Angeles', 'Asia/Shanghai'). "
                "Applies to cron expressions; '0 9 * * *' with tz='America/Los_Angeles' "
                "fires at 09:00 LA wall time. Empty string keeps the legacy UTC behaviour."
            ),
        },
    },
    required=["action"],
    owner_only=False,
)
async def cron(
    action: str,
    schedule: dict[str, Any] | None = None,
    task: str | None = None,
    job_kind: str = "reminder",
    session_target: str = "isolated",
    target_session_key: str | None = None,
    job_id: str | None = None,
    agent_id: str = "main",
    wake_mode: str = "now",
    tool_policy: dict[str, Any] | None = None,
    tz: str = "",
) -> str:
    if action not in _VALID_CRON_ACTIONS:
        raise ToolError(f"Invalid action: {action}. Must be list|add|remove|run")

    if action == "add" and (schedule is None or not task):
        raise ToolError("'schedule' and 'task' required for add")
    if action in ("remove", "run") and not job_id:
        raise ToolError(f"'job_id' required for {action}")

    # Dispatch to injected scheduler
    if _scheduler is None:
        raise ToolError("Scheduler not available")

    sched = _scheduler

    # Resolve caller context. Owner-context calls (loopback CLI, owner WebUI,
    # channel_admin_senders) pass through unchanged. Non-owner channel callers
    # get caller-scoped list / remove / run filtering and have target_session_key
    # / tool_policy blocked (privilege escalation knobs the model should not
    # synthesise on a normal channel turn).
    from opensquilla.tools.types import current_tool_context

    ctx = current_tool_context.get()
    is_owner_caller = bool(getattr(ctx, "is_owner", False)) if ctx is not None else True
    caller_session_key = (
        ctx.session_key if ctx is not None and ctx.session_key else ""
    )
    caller_sender_id = str(getattr(ctx, "sender_id", "") or "") if ctx is not None else ""

    if not is_owner_caller:
        if not caller_session_key:
            raise ToolError(
                "cron requires a session context for non-owner callers; "
                "call from a channel-bound session"
            )
        if action == "add":
            if target_session_key:
                raise ToolError(
                    "target_session_key is reserved for owner callers; "
                    "non-owner reminders are scoped to your current session"
                )
            if tool_policy:
                raise ToolError(
                    "tool_policy is reserved for owner callers"
                )

    if action == "list":
        jobs = await sched.list_jobs()
        if not is_owner_caller:
            jobs = [
                j
                for j in jobs
                if _owns_cron_job(j, caller_sender_id, caller_session_key)
            ]
        items = [
            {
                "job_id": j.id,
                "name": j.name,
                "cron_expr": j.cron_expr,
                "status": j.status.value if hasattr(j.status, "value") else str(j.status),
            }
            for j in jobs
        ]
        return json.dumps({"action": "list", "jobs": items})

    if action == "add":
        assert schedule is not None
        assert task is not None
        wake_mode = str(wake_mode or "now").strip().lower()
        schedule_kind, schedule_value, schedule_tz = _coerce_tool_schedule(
            schedule,
            tz=tz,
        )

        # Scan prompt for injection/exfiltration before scheduling
        blocked, reason = _scan_cron_prompt(task)
        if blocked:
            raise ToolError(reason)

        if job_kind not in ("reminder", "system_event", "agent_turn"):
            raise ToolError("job_kind must be reminder, system_event, or agent_turn")
        if session_target not in ("main", "isolated", "current", "session"):
            raise ToolError("session_target must be main, isolated, current, or session")
        if job_kind == "system_event" and session_target == "current":
            job_kind = REMINDER_KIND
            session_target = "isolated"
        if job_kind == "system_event" and session_target != "main":
            raise ToolError("system_event jobs must use session_target=main")
        if job_kind == REMINDER_KIND and session_target == "main":
            raise ToolError("reminder jobs cannot use session_target=main")
        if job_kind == "agent_turn" and session_target == "main":
            raise ToolError("agent_turn jobs cannot use session_target=main")
        if session_target == "current" and not caller_session_key:
            raise ToolError(
                "session_target=current requires a caller session context"
            )
        if session_target == "session" and not target_session_key:
            raise ToolError("target_session_key is required when session_target=session")
        if wake_mode not in ("now", "next-heartbeat"):
            raise ToolError("wake_mode must be now or next-heartbeat")

        # Auto-detect delivery target from session storage.
        delivery = None
        if caller_session_key:
            try:
                from opensquilla.scheduler.delivery import infer_delivery
                from opensquilla.tools.builtin.sessions import _get_session_manager

                mgr = _get_session_manager()
                storage = getattr(mgr, "_storage", mgr)
                inferred = await infer_delivery(
                    session_storage=storage,
                    session_key=caller_session_key,
                    user_overrides=None,
                )
                if (
                    inferred.mode == DeliveryMode.ORIGIN
                    and inferred.channel_name
                    and inferred.originating_reply_target is None
                ):
                    inferred.originating_reply_target = ReplyTargetSnapshot(
                        channel_name=inferred.channel_name,
                        channel_type=inferred.channel_name,
                        to=inferred.channel_id,
                        account_id=inferred.account_id,
                        thread_id=inferred.thread_id,
                    )
                if session_target == "main":
                    # Main heartbeat ignores the channel mode (persistence forces
                    # NONE for main) but uses the snapshot to pin the reply target.
                    if inferred.originating_reply_target is not None:
                        delivery = DeliveryConfig(
                            mode=DeliveryMode.NONE,
                            originating_reply_target=inferred.originating_reply_target,
                        )
                else:
                    delivery = inferred
            except Exception:
                pass

        # Snapshot fallback: when session storage did not yield a channel-
        # routable target (fresh session before last_channel was written), build
        # one from the live ToolContext so the first cron call still binds.
        if (
            ctx is not None
            and getattr(ctx, "channel_kind", None)
            and getattr(delivery, "originating_reply_target", None) is None
        ):
            snapshot = ReplyTargetSnapshot(
                channel_name=ctx.channel_kind or "",
                channel_type=ctx.channel_kind or "",
                to=ctx.channel_id or "",
            )
            if delivery is None:
                if session_target == "main":
                    delivery_mode = DeliveryMode.NONE
                    channel_name = ""
                    channel_id = ""
                else:
                    delivery_mode = DeliveryMode.ORIGIN
                    channel_name = ctx.channel_kind or ""
                    channel_id = ctx.channel_id or ""
                delivery = DeliveryConfig(
                    mode=delivery_mode,
                    channel_name=channel_name,
                    channel_id=channel_id,
                    originating_reply_target=snapshot,
                )
            else:
                delivery.originating_reply_target = snapshot
                if session_target != "main" and delivery.mode == DeliveryMode.NONE:
                    delivery.mode = DeliveryMode.ORIGIN
                    delivery.channel_name = ctx.channel_kind or ""
                    delivery.channel_id = ctx.channel_id or ""

        if job_kind == SYSTEM_EVENT_KIND:
            payload = make_system_event_payload(task, agent_id)
            handler_key = "system_event"
        elif job_kind == REMINDER_KIND:
            payload = make_reminder_payload(task, agent_id)
            handler_key = "static_message"
        else:
            payload = make_agent_turn_payload(task, agent_id)
            handler_key = "agent_run"
        effective_tz = (schedule_tz or tz or "").strip()
        job = await sched.add_job(
            name=task or "cron-tool-job",
            handler_key=handler_key,
            payload=payload,
            session_target=SessionTarget(session_target),
            session_key=(
                caller_session_key
                if session_target == "current"
                else (target_session_key or "")
            ),
            wake_mode=wake_mode,
            delivery=delivery,
            origin_session_key=caller_session_key,
            tool_policy=tool_policy,
            tz=effective_tz,
            creator_session_key=caller_session_key,
            creator_sender_id=caller_sender_id,
            creator_is_owner=is_owner_caller,
            schedule_kind=schedule_kind,
            schedule_value=schedule_value,
            schedule_tz=effective_tz,
        )
        # Populate ws_topic
        if job.delivery and not job.delivery.ws_topic:
            job.delivery.ws_topic = f"cron:{job.id}"
            try:
                await sched.update_job(job.id, delivery=job.delivery)
            except Exception:
                pass  # best-effort
        return json.dumps(
            {
                "action": "add",
                "job_id": job.id,
                "schedule_kind": schedule_kind.value,
                "schedule_value": schedule_value,
                "task": task,
                "payload_kind": job_kind,
                "session_target": session_target,
                "wake_mode": wake_mode,
                "tz": effective_tz,
                "status": "scheduled",
            }
        )

    if action == "remove":
        assert job_id is not None
        if not is_owner_caller:
            target_job = await sched.get_job(job_id)
            if target_job is None:
                raise ToolError(f"Job not found: {job_id}")
            if not _owns_cron_job(target_job, caller_sender_id, caller_session_key):
                raise ToolError(
                    "permission denied: you can only remove cron jobs you created"
                )
        removed = await sched.remove_job(job_id)
        if not removed:
            raise ToolError(f"Job not found: {job_id}")
        return json.dumps({"action": "remove", "job_id": job_id, "status": "removed"})

    # run
    assert job_id is not None
    if not is_owner_caller:
        target_job = await sched.get_job(job_id)
        if target_job is None:
            raise ToolError(f"Job not found: {job_id}")
        if not _owns_cron_job(target_job, caller_sender_id, caller_session_key):
            raise ToolError(
                "permission denied: you can only run cron jobs you created"
            )
    result = await sched.run_job_now(job_id)
    status = getattr(result, "status", "")
    status_str = status.value if hasattr(status, "value") else str(status)
    execution = getattr(result, "execution", None)
    run_payload: dict[str, Any] = {
        "action": "run",
        "job_id": job_id,
        "status": status_str,
    }
    if execution is not None:
        run_payload["success"] = execution.success
        run_payload["summary"] = execution.summary
        run_payload["error"] = execution.error
    else:
        run_payload["success"] = False
        run_payload["reason"] = getattr(result, "reason", "") or status_str
        run_payload["error"] = getattr(result, "error", None)
        current_status = getattr(result, "current_status", "")
        if current_status:
            run_payload["current_status"] = current_status
        backoff_until = getattr(result, "backoff_until", None)
        if backoff_until is not None:
            run_payload["backoff_until"] = backoff_until.isoformat()
    return json.dumps(
        run_payload
    )


# ---------------------------------------------------------------------------
# gateway
# ---------------------------------------------------------------------------


@tool(
    name="gateway",
    description="Gateway control: restart and configuration management.",
    params={
        "action": {
            "type": "string",
            "description": "Action: restart, config_get, config_set",
        },
        "key": {
            "type": "string",
            "description": "Config key path (required for config_get and config_set)",
        },
        "value": {
            "type": "string",
            "description": "Config value as JSON string (required for config_set)",
        },
    },
    required=["action"],
    owner_only=True,
)
async def gateway(
    action: str,
    key: str | None = None,
    value: str | None = None,
) -> str:
    if action not in _VALID_GATEWAY_ACTIONS:
        raise ToolError(f"Invalid action: {action}. Must be restart|config_get|config_set")

    if action in ("config_get", "config_set") and not key:
        raise ToolError(f"'key' required for {action}")
    if action == "config_set" and value is None:
        raise ToolError("'value' required for config_set")

    # Parse JSON value for config_set
    parsed_value = None
    if action == "config_set":
        assert value is not None
        try:
            parsed_value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            raise ToolError("'value' must be valid JSON")

    if _gateway_config is None:
        raise ToolError("Gateway config not available")

    config = _gateway_config

    if action == "restart":
        raise ToolError("Gateway restart not supported via tool")

    if action == "config_get":
        assert key is not None
        cfg_dict = config.to_toml_dict() if hasattr(config, "to_toml_dict") else {}
        # Navigate dot-path key
        parts = key.split(".")
        val = cfg_dict
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p)
            else:
                val = None
                break
        if val is None:
            raise ToolError(f"Config key not found: {key}")
        return json.dumps({"action": "config_get", "key": key, "value": val})

    # config_set
    if hasattr(config, "patch"):
        await config.patch({key: parsed_value})
        return json.dumps(
            {
                "action": "config_set",
                "key": key,
                "value": parsed_value,
            }
        )
    raise ToolError("Config modification not supported")
