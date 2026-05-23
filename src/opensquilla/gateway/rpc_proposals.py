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
