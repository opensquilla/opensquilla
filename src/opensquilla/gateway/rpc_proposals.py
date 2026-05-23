"""Proposals domain RPC handlers backed by opensquilla.skills.proposals_lib.

Five JSON-RPC methods drive the WebUI proposals panel:

* ``exec.proposals.pending_count`` — cheap badge count
* ``exec.proposals.list``         — table of pending proposals
* ``exec.proposals.show``         — full SKILL.md + gates payload
* ``exec.proposals.accept``       — promote to MANAGED layer
* ``exec.proposals.reject``       — delete the proposal directory

All five run in-process by calling ``proposals_lib`` directly (no
subprocess fork per click). All five validate ``proposal_id`` with
the 8-hex regex BEFORE touching the filesystem — accept/reject are
irreversible.
"""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.paths import default_opensquilla_home
from opensquilla.skills import proposals_lib

_d = get_dispatcher()


def _require_proposal_id(params: dict | None) -> str:
    if not isinstance(params, dict):
        raise ValueError("params object required")
    pid = params.get("proposal_id") or params.get("proposalId")
    if not isinstance(pid, str) or not proposals_lib.is_valid_proposal_id(pid):
        raise ValueError(
            "proposal_id must be 8 lowercase hex chars",
        )
    return pid


@_d.method("exec.proposals.pending_count", scope="operator.proposals")
async def _handle_pending_count(
    params: dict | None, ctx: RpcContext,
) -> dict[str, Any]:
    return proposals_lib.pending_count(default_opensquilla_home())


@_d.method("exec.proposals.list", scope="operator.proposals")
async def _handle_list(
    params: dict | None, ctx: RpcContext,
) -> dict[str, Any]:
    return proposals_lib.list_proposals(default_opensquilla_home())


@_d.method("exec.proposals.show", scope="operator.proposals")
async def _handle_show(
    params: dict | None, ctx: RpcContext,
) -> dict[str, Any]:
    pid = _require_proposal_id(params)
    return proposals_lib.show_proposal(default_opensquilla_home(), pid)


@_d.method("exec.proposals.accept", scope="operator.proposals")
async def _handle_accept(
    params: dict | None, ctx: RpcContext,
) -> dict[str, Any]:
    pid = _require_proposal_id(params)
    force = bool((params or {}).get("force", False))
    return proposals_lib.accept_proposal(
        default_opensquilla_home(), pid, force=force,
    )


@_d.method("exec.proposals.reject", scope="operator.proposals")
async def _handle_reject(
    params: dict | None, ctx: RpcContext,
) -> dict[str, Any]:
    pid = _require_proposal_id(params)
    return proposals_lib.reject_proposal(default_opensquilla_home(), pid)


# ─── Settings: WebUI toggle for the auto-propose feature ──────────────


def _settings_payload(cfg: Any, available: bool) -> dict[str, Any]:
    return {
        "available": available,
        "enabled": bool(getattr(cfg, "enabled", False)) if cfg is not None else False,
        "on_dream_complete": (
            bool(getattr(cfg, "on_dream_complete", False))
            if cfg is not None
            else False
        ),
        "cron": getattr(cfg, "cron", "0 5 * * *") if cfg is not None else "0 5 * * *",
        "window_days": (
            int(getattr(cfg, "window_days", 30)) if cfg is not None else 30
        ),
        "min_freq": int(getattr(cfg, "min_freq", 3)) if cfg is not None else 3,
        "top_k": int(getattr(cfg, "top_k", 5)) if cfg is not None else 5,
    }


@_d.method("exec.proposals.settings.get", scope="operator.proposals")
async def _handle_settings_get(
    params: dict | None, ctx: RpcContext,
) -> dict[str, Any]:
    """Return the live auto-propose runtime settings.

    When the runtime isn't registered (provider not configured, or the
    feature surface failed to wire at boot), ``available`` is ``False``
    and the UI shows a "feature unavailable" hint instead of toggles.
    """
    from opensquilla.gateway.auto_propose_bridge import get_runtime

    rt = get_runtime()
    if rt is None:
        return _settings_payload(cfg=None, available=False)
    return _settings_payload(cfg=rt.config, available=True)


@_d.method("exec.proposals.settings.set", scope="operator.proposals")
async def _handle_settings_set(
    params: dict | None, ctx: RpcContext,
) -> dict[str, Any]:
    """Mutate the live runtime config + persist to JSON state file.

    Side effect: when ``enabled`` transitions ``False → True`` the
    per-agent cron jobs are added; the reverse transition pauses them
    (idempotent re-register-or-pause). Dream-hook is purely
    predicate-gated so its toggle has no scheduler side effect.

    Accepts partial updates — clients may pass only the keys they want
    to change.
    """
    from opensquilla.gateway.auto_propose_bridge import get_runtime
    from opensquilla.skills.proposals_lib import write_auto_propose_settings

    rt = get_runtime()
    if rt is None:
        return {"status": "error", "reason": "auto_propose runtime not available"}
    if not isinstance(params, dict):
        raise ValueError("params object required")

    cfg = rt.config
    was_enabled = bool(getattr(cfg, "enabled", False))
    requested: dict[str, bool] = {}
    for key in ("enabled", "on_dream_complete"):
        if key in params:
            v = params[key]
            if not isinstance(v, bool):
                raise ValueError(f"{key} must be a boolean")
            requested[key] = v

    # Apply to the live object the predicate reads
    for key, value in requested.items():
        setattr(cfg, key, value)

    # Persist so the toggle survives restart
    persisted = {
        "enabled": bool(getattr(cfg, "enabled", False)),
        "on_dream_complete": bool(getattr(cfg, "on_dream_complete", False)),
    }
    try:
        write_auto_propose_settings(rt.home, persisted)
    except OSError as exc:
        return {
            "status": "error",
            "reason": f"failed to persist settings: {exc}",
            "settings": _settings_payload(cfg, available=True),
        }

    # Side effect on cron jobs only when ``enabled`` actually flipped
    now_enabled = bool(getattr(cfg, "enabled", False))
    if now_enabled and not was_enabled:
        await rt.register_crons()
    elif was_enabled and not now_enabled:
        await rt.pause_crons()

    return {"status": "ok", "settings": _settings_payload(cfg, available=True)}
