"""Integration tests for the proposals RPC handlers.

These tests build a fake home dir under tmp_path, seed it with one or
two synthetic proposals, and call each handler through the live
``opensquilla.gateway.rpc`` dispatcher to verify the full path:
parameter validation → library call → JSON-ready return.

LLM is not involved — proposals_lib is deterministic.
"""

from __future__ import annotations

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


def _mark_auto_enabled(home: Path, pid: str) -> None:
    gates_path = home / "proposals" / pid / "gates.json"
    import json
    gates = json.loads(gates_path.read_text())
    gates["auto_enable"] = {
        "status": "enabled",
        "proposal_id": pid,
        "risk_level": "low",
        "max_risk": "low",
        "triggered_by": "manual",
        "enabled_at_ms": 123,
        "details": {
            "validation_profile": "static-safety-v2",
            "reason": "ok",
            "skills": ["summarize"],
            "tools": [],
            "reasons": [],
        },
    }
    gates_path.write_text(json.dumps(gates))


@pytest.fixture
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``default_opensquilla_home`` to a tmp dir so the RPC
    layer reads / writes there without touching the real ~/.opensquilla."""
    from opensquilla.gateway.auto_propose_bridge import reset_runtime_for_test

    reset_runtime_for_test()
    home = tmp_path / ".opensquilla"
    home.mkdir()
    # ``proposals_lib`` invokes ``default_opensquilla_home()`` through the
    # RPC module; patch the import surface used by rpc_proposals.
    monkeypatch.setattr(
        "opensquilla.gateway.rpc_proposals.default_opensquilla_home",
        lambda: home,
    )
    return home


def _make_ctx(skill_loader: object | None = None) -> object:
    """Minimal RpcContext stand-in for proposal handlers."""
    class _Ctx:
        scopes: list[str] = []
        skill_loader = None

    ctx = _Ctx()
    ctx.skill_loader = skill_loader
    return ctx


class _CountingLoader:
    def __init__(self) -> None:
        self.invalidations = 0

    def invalidate_cache(self) -> None:
        self.invalidations += 1


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
    _mark_auto_enabled(_isolated_home, pid)
    out = await _handle_show({"proposal_id": pid}, _make_ctx())
    assert out["status"] == "ok"
    assert out["proposal_id"] == pid
    assert "synth-rpc-pipeline" in out["skill_md"]
    assert out["auto_enable_audit"] == {
        "status": "enabled",
        "reason": "ok",
        "risk_level": "low",
        "max_risk": "low",
        "validation_profile": "static-safety-v2",
        "skills": ["summarize"],
        "tools": [],
        "reasons": [],
    }


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

    loader = _CountingLoader()
    pid = _seed(_isolated_home)
    out = await _handle_accept({"proposal_id": pid}, _make_ctx(loader))
    assert out["status"] == "ok"
    assert out["name"] == "synth-rpc-pipeline"
    assert (_isolated_home / "skills" / "synth-rpc-pipeline" / "SKILL.md").is_file()
    assert not (_isolated_home / "proposals" / pid).exists()
    assert loader.invalidations == 1


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


@pytest.mark.asyncio
async def test_auto_enabled_list_and_disable_round_trip(_isolated_home: Path) -> None:
    from opensquilla.gateway.rpc_proposals import (
        _handle_accept,
        _handle_auto_enabled_disable,
        _handle_auto_enabled_list,
    )

    pid = _seed(_isolated_home)
    _mark_auto_enabled(_isolated_home, pid)
    loader = _CountingLoader()
    accepted = await _handle_accept({"proposal_id": pid}, _make_ctx(loader))
    assert accepted["status"] == "ok"
    assert loader.invalidations == 1

    listed = await _handle_auto_enabled_list(None, _make_ctx())
    assert listed["skills"][0]["name"] == "synth-rpc-pipeline"
    assert listed["skills"][0]["proposal_id"] == pid
    assert listed["skills"][0]["validation_profile"] == "static-safety-v2"
    assert listed["skills"][0]["skills"] == ["summarize"]

    disabled = await _handle_auto_enabled_disable(
        {"name": "synth-rpc-pipeline"}, _make_ctx(loader),
    )
    assert disabled["status"] == "ok"
    assert (_isolated_home / "proposals" / pid / "SKILL.md").is_file()
    assert loader.invalidations == 2


@pytest.mark.asyncio
async def test_settings_get_returns_unavailable_when_runtime_not_registered(
    _isolated_home: Path,
) -> None:
    from opensquilla.gateway.auto_propose_bridge import reset_runtime_for_test
    from opensquilla.gateway.rpc_proposals import _handle_settings_get

    reset_runtime_for_test()
    out = await _handle_settings_get(None, _make_ctx())
    assert out["available"] is False
    assert out["enabled"] is False


@pytest.mark.asyncio
async def test_settings_get_and_set_full_round_trip(
    _isolated_home: Path,
) -> None:
    from opensquilla.gateway.auto_propose_bridge import (
        AutoProposeRuntime,
        register_runtime,
        reset_runtime_for_test,
    )
    from opensquilla.gateway.config import MetaSkillAutoProposeConfig
    from opensquilla.gateway.rpc_proposals import (
        _handle_settings_get,
        _handle_settings_set,
    )
    from opensquilla.skills.proposals_lib import (
        read_auto_propose_settings,
    )

    reset_runtime_for_test()
    cfg = MetaSkillAutoProposeConfig()
    register_events: list[str] = []

    async def register_crons() -> None:
        register_events.append("register")

    async def pause_crons() -> None:
        register_events.append("pause")

    register_runtime(AutoProposeRuntime(
        config=cfg,
        home=_isolated_home,
        register_crons=register_crons,
        pause_crons=pause_crons,
    ))

    out = await _handle_settings_get(None, _make_ctx())
    assert out["available"] is True
    assert out["enabled"] is False
    assert out["auto_enable"] is False
    assert out["auto_enable_max_risk"] == "low"

    # Flip on
    out = await _handle_settings_set(
        {
            "enabled": True,
            "auto_enable": True,
            "auto_enable_max_risk": "medium",
        }, _make_ctx(),
    )
    assert out["status"] == "ok"
    assert out["settings"]["enabled"] is True
    assert out["settings"]["auto_enable"] is True
    assert out["settings"]["auto_enable_max_risk"] == "medium"
    assert register_events == ["register"]
    # Persisted
    assert read_auto_propose_settings(_isolated_home) == {
        "enabled": True,
        "on_dream_complete": False,
        "auto_enable": True,
        "auto_enable_max_risk": "medium",
    }

    # Flip off
    register_events.clear()
    out = await _handle_settings_set({"enabled": False}, _make_ctx())
    assert out["settings"]["enabled"] is False
    assert register_events == ["pause"]
    assert read_auto_propose_settings(_isolated_home) == {
        "enabled": False,
        "on_dream_complete": False,
        "auto_enable": True,
        "auto_enable_max_risk": "medium",
    }


@pytest.mark.asyncio
async def test_settings_set_partial_update_only_changes_supplied_keys(
    _isolated_home: Path,
) -> None:
    from opensquilla.gateway.auto_propose_bridge import (
        AutoProposeRuntime,
        register_runtime,
        reset_runtime_for_test,
    )
    from opensquilla.gateway.config import MetaSkillAutoProposeConfig
    from opensquilla.gateway.rpc_proposals import _handle_settings_set

    reset_runtime_for_test()
    cfg = MetaSkillAutoProposeConfig(enabled=True, on_dream_complete=True)
    register_runtime(AutoProposeRuntime(
        config=cfg,
        home=_isolated_home,
        register_crons=lambda: _noop(),
        pause_crons=lambda: _noop(),
    ))
    # Only toggle dream; enabled must stay True (no register/pause event)
    out = await _handle_settings_set(
        {"on_dream_complete": False}, _make_ctx(),
    )
    assert out["status"] == "ok"
    assert out["settings"]["enabled"] is True
    assert out["settings"]["on_dream_complete"] is False
    assert out["settings"]["auto_enable"] is False


@pytest.mark.asyncio
async def test_settings_set_rolls_back_when_scheduler_update_fails(
    _isolated_home: Path,
) -> None:
    from opensquilla.gateway.auto_propose_bridge import (
        AutoProposeRuntime,
        register_runtime,
        reset_runtime_for_test,
    )
    from opensquilla.gateway.config import MetaSkillAutoProposeConfig
    from opensquilla.gateway.rpc_proposals import _handle_settings_set
    from opensquilla.skills.proposals_lib import read_auto_propose_settings

    reset_runtime_for_test()
    cfg = MetaSkillAutoProposeConfig(enabled=False, on_dream_complete=False)

    async def register_crons() -> None:
        raise RuntimeError("scheduler unavailable")

    register_runtime(AutoProposeRuntime(
        config=cfg,
        home=_isolated_home,
        register_crons=register_crons,
        pause_crons=lambda: _noop(),
    ))

    out = await _handle_settings_set({"enabled": True}, _make_ctx())

    assert out["status"] == "error"
    assert "scheduler unavailable" in out["reason"]
    assert cfg.enabled is False
    assert read_auto_propose_settings(_isolated_home) == {}


async def _noop() -> None:  # helper for partial-update test
    return None


@pytest.mark.asyncio
async def test_settings_set_rejects_non_boolean_values(
    _isolated_home: Path,
) -> None:
    from opensquilla.gateway.auto_propose_bridge import (
        AutoProposeRuntime,
        register_runtime,
        reset_runtime_for_test,
    )
    from opensquilla.gateway.config import MetaSkillAutoProposeConfig
    from opensquilla.gateway.rpc_proposals import _handle_settings_set

    reset_runtime_for_test()
    register_runtime(AutoProposeRuntime(
        config=MetaSkillAutoProposeConfig(),
        home=_isolated_home,
        register_crons=lambda: _noop(),
        pause_crons=lambda: _noop(),
    ))
    with pytest.raises(ValueError):
        await _handle_settings_set({"enabled": "yes"}, _make_ctx())
    with pytest.raises(ValueError):
        await _handle_settings_set({"auto_enable": "yes"}, _make_ctx())
    with pytest.raises(ValueError):
        await _handle_settings_set({"auto_enable_max_risk": "dangerous"}, _make_ctx())


def test_proposal_read_methods_classified_under_operator_proposals_scope() -> None:
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
        "exec.proposals.settings.get",
        "exec.proposals.auto_enabled.list",
    ):
        assert METHOD_SCOPES.get(name) == PROPOSALS_SCOPE, name


def test_proposal_mutation_methods_require_admin_scope() -> None:
    """Proposal promotion changes the managed skill layer, so remote
    no-auth operators must not be able to perform these mutations."""
    from opensquilla.gateway.scopes import (
        ADMIN_SCOPE,
        METHOD_SCOPES,
    )

    for name in (
        "exec.proposals.accept",
        "exec.proposals.reject",
        "exec.proposals.settings.set",
        "exec.proposals.auto_enabled.disable",
    ):
        assert METHOD_SCOPES.get(name) == ADMIN_SCOPE, name
