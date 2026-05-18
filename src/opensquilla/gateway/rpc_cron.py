"""Cron domain RPC handlers (Tier 2)."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, RpcUnavailableError, get_dispatcher
from opensquilla.scheduler.rpc_payload import (
    build_cron_add_job_kwargs,
    build_cron_update_patch,
    cron_job_to_wire,
    cron_run_to_wire,
    cron_subscription_error_response,
    cron_subscription_response,
    manual_run_to_wire,
    reply_target_snapshot_from_envelope,
    require_cron_add_params,
)

_d = get_dispatcher()


def _require_scheduler(ctx: RpcContext) -> Any:
    scheduler = getattr(ctx, "cron_scheduler", None)
    if scheduler is None:
        raise RpcUnavailableError("Cron scheduler is not available")
    return scheduler


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
    params = require_cron_add_params(params)
    scheduler = _require_scheduler(ctx)
    session_manager = getattr(ctx, "session_manager", None)
    session_storage = (
        getattr(session_manager, "_storage", session_manager)
        if session_manager is not None
        else None
    )
    add_kwargs = await build_cron_add_job_kwargs(
        params,
        session_storage=session_storage,
        originating_reply_target=reply_target_snapshot_from_envelope(
            getattr(ctx, "originating_envelope", None)
        ),
    )
    job = await scheduler.add_job(**add_kwargs)
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

    patch = build_cron_update_patch(params, current_job)
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
