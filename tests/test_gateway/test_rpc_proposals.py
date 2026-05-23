"""Integration tests for the proposals RPC handlers.

These tests build a fake home dir under tmp_path, seed it with one or
two synthetic proposals, and call each handler through the live
``opensquilla.gateway.rpc`` dispatcher to verify the full path:
parameter validation → library call → JSON-ready return.

LLM is not involved — proposals_lib is deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensquilla.skills import proposals_lib


_SAMPLE_SKILL_MD = """---
name: synth-rpc-pipeline
description: "Sample meta-skill used by RPC proposals integration tests"
kind: meta
meta_priority: 50
triggers:
  - "synth rpc trigger"
provenance:
  origin: opensquilla-user
composition:
  steps:
    - id: a
      skill: summarize
      with:
        task: "{{ inputs.user_message }}"
---
"""


def _seed(home: Path) -> str:
    return proposals_lib.write_proposal(
        home,
        _SAMPLE_SKILL_MD,
        {"G1": {"passed": True}, "G2": {"passed": True}},
        {"G3": {"passed": True}, "G4": {"passed": True}},
    )["proposal_id"]


@pytest.fixture
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``default_opensquilla_home`` to a tmp dir so the RPC
    layer reads / writes there without touching the real ~/.opensquilla."""
    home = tmp_path / ".opensquilla"
    home.mkdir()
    # ``proposals_lib`` invokes ``default_opensquilla_home()`` through the
    # RPC module; patch the import surface used by rpc_proposals.
    monkeypatch.setattr(
        "opensquilla.gateway.rpc_proposals.default_opensquilla_home",
        lambda: home,
    )
    return home


def _make_ctx() -> object:
    """Minimal RpcContext stand-in — the handlers don't read any fields."""
    class _Ctx:
        scopes: list[str] = []
    return _Ctx()


@pytest.mark.asyncio
async def test_pending_count_reflects_seeded_proposals(_isolated_home: Path) -> None:
    from opensquilla.gateway.rpc_proposals import _handle_pending_count

    out = await _handle_pending_count(None, _make_ctx())
    assert out == {"count": 0}
    _seed(_isolated_home)
    _seed(_isolated_home)
    out2 = await _handle_pending_count(None, _make_ctx())
    assert out2 == {"count": 2}


@pytest.mark.asyncio
async def test_list_returns_proposal_rows(_isolated_home: Path) -> None:
    from opensquilla.gateway.rpc_proposals import _handle_list

    pid1 = _seed(_isolated_home)
    pid2 = _seed(_isolated_home)
    out = await _handle_list(None, _make_ctx())
    ids = sorted(r["proposal_id"] for r in out["proposals"])
    assert ids == sorted([pid1, pid2])


@pytest.mark.asyncio
async def test_show_happy_path(_isolated_home: Path) -> None:
    from opensquilla.gateway.rpc_proposals import _handle_show

    pid = _seed(_isolated_home)
    out = await _handle_show({"proposal_id": pid}, _make_ctx())
    assert out["status"] == "ok"
    assert out["proposal_id"] == pid
    assert "synth-rpc-pipeline" in out["skill_md"]


@pytest.mark.asyncio
async def test_show_camelcase_proposal_id_also_accepted(
    _isolated_home: Path,
) -> None:
    from opensquilla.gateway.rpc_proposals import _handle_show

    pid = _seed(_isolated_home)
    out = await _handle_show({"proposalId": pid}, _make_ctx())
    assert out["status"] == "ok"


@pytest.mark.asyncio
async def test_invalid_proposal_id_raises_value_error(_isolated_home: Path) -> None:
    from opensquilla.gateway.rpc_proposals import _handle_show

    with pytest.raises(ValueError):
        await _handle_show({"proposal_id": "../etc"}, _make_ctx())
    with pytest.raises(ValueError):
        await _handle_show({"proposal_id": "TOOLONGTOMATCH"}, _make_ctx())
    with pytest.raises(ValueError):
        await _handle_show(None, _make_ctx())


@pytest.mark.asyncio
async def test_accept_promotes_proposal(_isolated_home: Path) -> None:
    from opensquilla.gateway.rpc_proposals import _handle_accept

    pid = _seed(_isolated_home)
    out = await _handle_accept({"proposal_id": pid}, _make_ctx())
    assert out["status"] == "ok"
    assert out["name"] == "synth-rpc-pipeline"
    assert (_isolated_home / "skills" / "synth-rpc-pipeline" / "SKILL.md").is_file()
    assert not (_isolated_home / "proposals" / pid).exists()


@pytest.mark.asyncio
async def test_accept_with_force_overrides_gates(
    _isolated_home: Path,
) -> None:
    from opensquilla.gateway.rpc_proposals import _handle_accept

    bad_pid = proposals_lib.write_proposal(
        _isolated_home,
        _SAMPLE_SKILL_MD,
        {"G1": {"passed": False}, "G2": {"passed": True}},
        {"G3": {"passed": True}, "G4": {"passed": True}},
    )["proposal_id"]
    soft = await _handle_accept({"proposal_id": bad_pid}, _make_ctx())
    assert soft["status"] == "refused"
    hard = await _handle_accept(
        {"proposal_id": bad_pid, "force": True}, _make_ctx(),
    )
    assert hard["status"] == "ok"


@pytest.mark.asyncio
async def test_reject_removes_proposal(_isolated_home: Path) -> None:
    from opensquilla.gateway.rpc_proposals import _handle_reject

    pid = _seed(_isolated_home)
    out = await _handle_reject({"proposal_id": pid}, _make_ctx())
    assert out["status"] == "ok"
    assert not (_isolated_home / "proposals" / pid).exists()


@pytest.mark.asyncio
async def test_rejecting_unknown_proposal_returns_error(
    _isolated_home: Path,
) -> None:
    from opensquilla.gateway.rpc_proposals import _handle_reject

    out = await _handle_reject({"proposal_id": "deadbeef"}, _make_ctx())
    assert out["status"] == "error"
    assert "not found" in out["reason"]


def test_proposals_methods_classified_under_operator_proposals_scope() -> None:
    """Architecture invariant: scope drift would crash boot, but assert
    explicitly so the relationship between rpc_proposals.py and
    scopes.PROPOSALS_SCOPE is captured by a failing test if either side
    moves."""
    from opensquilla.gateway.scopes import (
        METHOD_SCOPES,
        PROPOSALS_SCOPE,
    )

    for name in (
        "exec.proposals.pending_count",
        "exec.proposals.list",
        "exec.proposals.show",
        "exec.proposals.accept",
        "exec.proposals.reject",
    ):
        assert METHOD_SCOPES.get(name) == PROPOSALS_SCOPE, name
