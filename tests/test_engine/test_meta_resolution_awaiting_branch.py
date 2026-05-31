"""meta_resolution awaiting-branch tests (PR3, design §8.2)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from yoyo import get_backend, read_migrations

from opensquilla.engine.steps.meta_resolution import meta_resolution
from opensquilla.persistence.meta_run_writer import MetaRunWriter
from opensquilla.skills.meta.plan_serde import to_jsonable
from opensquilla.skills.meta.types import (
    ClarifyField,
    ClarifyStepConfig,
    MetaPlan,
    MetaStep,
)


def _writer(tmp_path: Path) -> MetaRunWriter:
    db = tmp_path / "x.sqlite"
    get_backend(f"sqlite:///{db}").apply_migrations(read_migrations("migrations"))
    conn = sqlite3.connect(db, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return MetaRunWriter(conn)


def _seed_awaiting(writer, *, run_id="r1", session_key="S1",
                   timeout_hours=24, since: float | None = None,
                   cancel_keywords=("取消", "cancel")):
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="x", type="string", required=True),),
        timeout_hours=timeout_hours,
        cancel_keywords=cancel_keywords,
    )
    plan = MetaPlan(
        name="t",
        triggers=(),
        priority=0,
        steps=(
            MetaStep(id="collect", skill="collect", kind="user_input",
                     clarify_config=cfg),
        ),
    )
    snapshot = to_jsonable(plan)
    with writer._lock:
        writer._conn.execute(
            "INSERT INTO meta_skill_runs "
            "(run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json, "
            " triggered_by, session_key, status, started_at_ms, inputs_json, "
            " awaiting_step_id, awaiting_schema_json, awaiting_since, "
            " awaiting_filled_json, step_outputs_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "t", "d", json.dumps(snapshot),
             "soft_meta_invoke", session_key, "awaiting_user", 0,
             json.dumps({"user_message": "original trigger", "collected": {}}),
             "collect",
             json.dumps(snapshot["plan"]["steps"][0]["clarify_config"]),
             since if since is not None else time.time(),
             "{}", "{}"),
        )
        writer._conn.commit()
    return plan


def _ctx(writer, *, message="hi", session_id="S1"):
    loader = MagicMock()
    loader.load_all.return_value = []
    return SimpleNamespace(
        message=message,
        session_key=session_id,
        metadata={"skill_loader": loader, "meta_run_writer": writer},
        system_prompt="",
        config=SimpleNamespace(squilla_router=SimpleNamespace(tiers={})),
        surface_kind="cli",
    )


@pytest.mark.asyncio
async def test_awaiting_branch_takes_precedence_over_trigger_match(tmp_path):
    writer = _writer(tmp_path)
    _seed_awaiting(writer)
    ctx = _ctx(writer, message="hi", session_id="S1")
    out = await meta_resolution(ctx)
    assert "meta_match" not in out.metadata
    awaiting_markers = {
        "meta_clarify_errors", "meta_clarify_cancelled",
        "meta_clarify_expired", "meta_clarify_reprompt",
        "meta_resume",
    }
    assert any(k in out.metadata for k in awaiting_markers)


@pytest.mark.asyncio
async def test_expired_awaiting_run_marked_and_reported(tmp_path):
    writer = _writer(tmp_path)
    _seed_awaiting(writer, since=time.time() - (100 * 3600), timeout_hours=24)

    ctx = _ctx(writer, message="any text", session_id="S1")
    out = await meta_resolution(ctx)
    assert "meta_clarify_expired" in out.metadata

    with writer._lock:
        row = writer._conn.execute(
            "SELECT status FROM meta_skill_runs WHERE run_id='r1'",
        ).fetchone()
    assert row["status"] == "expired"


@pytest.mark.asyncio
async def test_cancel_keyword_marks_cancelled(tmp_path):
    writer = _writer(tmp_path)
    _seed_awaiting(writer, cancel_keywords=("取消",))
    ctx = _ctx(writer, message="算了我取消", session_id="S1")
    out = await meta_resolution(ctx)
    assert "meta_clarify_cancelled" in out.metadata


@pytest.mark.asyncio
async def test_parse_failure_strikes_increment(tmp_path):
    writer = _writer(tmp_path)
    _seed_awaiting(writer)
    # Seed schema has one required string field "x". Real parser rejects
    # unknown keys, so "bogus: x" triggers a parse error.
    ctx = _ctx(writer, message="bogus: x", session_id="S1")

    out = await meta_resolution(ctx)
    assert "meta_clarify_errors" in out.metadata
    with writer._lock:
        row = writer._conn.execute(
            "SELECT parse_failure_count, status FROM meta_skill_runs "
            "WHERE run_id='r1'",
        ).fetchone()
    assert row["parse_failure_count"] == 1
    assert row["status"] == "awaiting_user"


@pytest.mark.asyncio
async def test_three_consecutive_parse_failures_auto_cancel(tmp_path):
    writer = _writer(tmp_path)
    _seed_awaiting(writer)
    # Seed schema has one required string field "x". Real parser rejects
    # unknown keys, so "bogus: x" triggers a parse error.
    ctx = _ctx(writer, message="bogus: x", session_id="S1")

    for _ in range(3):
        ctx.metadata.pop("meta_clarify_errors", None)
        ctx.metadata.pop("meta_clarify_reprompt", None)
        await meta_resolution(ctx)

    with writer._lock:
        row = writer._conn.execute(
            "SELECT status, error FROM meta_skill_runs WHERE run_id='r1'",
        ).fetchone()
    assert row["status"] == "cancelled"
    assert "parse_failure_limit" in (row["error"] or "")


@pytest.mark.asyncio
async def test_parse_success_calls_try_claim_resume_and_sets_meta_resume(tmp_path, monkeypatch):
    """When the (stub) parser returns success, meta_resolution MUST perform
    try_claim_resume CAS and stash the ResumePayload on ctx.metadata."""
    import importlib
    mr_module = importlib.import_module("opensquilla.engine.steps.meta_resolution")

    writer = _writer(tmp_path)
    _seed_awaiting(writer)

    def _fake_parser(message, schema, *, surface):
        return {"x": "Tokyo"}, []

    monkeypatch.setattr(mr_module, "parse_clarify_reply", _fake_parser)

    ctx = _ctx(writer, message="Tokyo", session_id="S1")
    out = await meta_resolution(ctx)

    assert "meta_resume" in out.metadata
    claim, parsed = out.metadata["meta_resume"]
    assert claim.run_id == "r1"
    assert parsed == {"x": "Tokyo"}

    assert writer.peek_awaiting(session_id="S1") is None


@pytest.mark.asyncio
async def test_parse_success_race_lost_sets_marker(tmp_path, monkeypatch):
    """Two concurrent calls: first wins CAS; second has no awaiting run to peek."""
    import importlib
    mr_module = importlib.import_module("opensquilla.engine.steps.meta_resolution")

    writer = _writer(tmp_path)
    _seed_awaiting(writer)

    monkeypatch.setattr(
        mr_module, "parse_clarify_reply",
        lambda message, schema, *, surface: ({"x": "Tokyo"}, []),
    )

    ctx1 = _ctx(writer, message="Tokyo", session_id="S1")
    out1 = await meta_resolution(ctx1)
    assert "meta_resume" in out1.metadata

    ctx2 = _ctx(writer, message="Tokyo", session_id="S1")
    out2 = await meta_resolution(ctx2)
    assert "meta_resume" not in out2.metadata
    awaiting_keys = [k for k in out2.metadata if k.startswith("meta_clarify")]
    assert not awaiting_keys


@pytest.mark.asyncio
async def test_db_outage_falls_through_to_trigger_match(tmp_path):
    """Fail-open: peek_awaiting raising should NOT abort the turn."""
    broken = MagicMock()
    broken.peek_awaiting.side_effect = RuntimeError("db down")

    loader = MagicMock()
    loader.load_all.return_value = []
    ctx = SimpleNamespace(
        message="hi",
        session_key="S1",
        metadata={"skill_loader": loader, "meta_run_writer": broken},
        system_prompt="",
        config=SimpleNamespace(squilla_router=SimpleNamespace(tiers={})),
        surface_kind="cli",
    )
    out = await meta_resolution(ctx)
    awaiting_keys = [k for k in out.metadata if k.startswith("meta_clarify")]
    assert not awaiting_keys


# ── PR9: nl_extract fallback integration ──

def _seed_awaiting_with_nl_extract(writer, **kwargs):
    """Variant of _seed_awaiting that enables nl_extract on the schema."""
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="x", type="string", required=True),),
        timeout_hours=24,
        cancel_keywords=(),
        nl_extract=True,
    )
    plan = MetaPlan(
        name="t",
        triggers=(),
        priority=0,
        steps=(
            MetaStep(id="collect", skill="collect", kind="user_input",
                     clarify_config=cfg),
        ),
    )
    snapshot = to_jsonable(plan)
    with writer._lock:
        writer._conn.execute(
            "INSERT INTO meta_skill_runs "
            "(run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json, "
            " triggered_by, session_key, status, started_at_ms, inputs_json, "
            " awaiting_step_id, awaiting_schema_json, awaiting_since, "
            " awaiting_filled_json, step_outputs_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("r1", "t", "d", json.dumps(snapshot),
             "soft_meta_invoke", "S1", "awaiting_user", 0,
             json.dumps({"user_message": "original trigger", "collected": {}}),
             "collect",
             json.dumps(snapshot["plan"]["steps"][0]["clarify_config"]),
             time.time(), "{}", "{}"),
        )
        writer._conn.commit()
    return plan


def _ctx_with_nl_chat(writer, *, message, llm_response):
    """Build ctx with both meta_run_writer and a mock llm_chat callable."""
    loader = MagicMock()
    loader.load_all.return_value = []

    async def _nl_chat(system, user):
        return llm_response

    return SimpleNamespace(
        message=message,
        session_key="S1",
        metadata={
            "skill_loader": loader,
            "meta_run_writer": writer,
            "meta_llm_chat": _nl_chat,
        },
        system_prompt="",
        config=SimpleNamespace(squilla_router=SimpleNamespace(tiers={})),
        surface_kind="cli",
    )


@pytest.mark.asyncio
async def test_nl_extract_fills_field_when_deterministic_parser_fails(tmp_path):
    """A 3-line natural-language reply causes positional parser to reject
    (too many lines for a 1-field schema); nl_extract LLM picks up the
    structured JSON and resumes the DAG."""
    writer = _writer(tmp_path)
    _seed_awaiting_with_nl_extract(writer)

    ctx = _ctx_with_nl_chat(
        writer,
        # 3 lines → positional rejects (schema has 1 field) →
        # nl_extract fallback is invoked.
        message="I have been thinking\nabout my next vacation\nand want to visit Tokyo!",
        llm_response=json.dumps({"x": "Tokyo"}),
    )
    out = await meta_resolution(ctx)
    assert "meta_resume" in out.metadata, (
        f"expected nl_extract to fill field; got metadata={dict(out.metadata)}"
    )
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {"x": "Tokyo"}


@pytest.mark.asyncio
async def test_nl_extract_preferred_when_deterministic_parser_would_succeed(tmp_path):
    """When nl_extract is enabled, the LLM extraction owns reply parsing."""
    writer = _writer(tmp_path)
    _seed_awaiting_with_nl_extract(writer)

    llm_called = {"count": 0}

    async def _nl_chat(system, user):
        llm_called["count"] += 1
        return json.dumps({"x": "LLM Tokyo"})

    loader = MagicMock()
    loader.load_all.return_value = []
    ctx = SimpleNamespace(
        message="x: Tokyo",  # deterministic parser succeeds here
        session_key="S1",
        metadata={
            "skill_loader": loader,
            "meta_run_writer": writer,
            "meta_llm_chat": _nl_chat,
        },
        system_prompt="",
        config=SimpleNamespace(squilla_router=SimpleNamespace(tiers={})),
        surface_kind="cli",
    )
    out = await meta_resolution(ctx)
    assert "meta_resume" in out.metadata
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {"x": "LLM Tokyo"}
    assert llm_called["count"] == 1


@pytest.mark.asyncio
async def test_nl_extract_maps_natural_language_to_enum_choice(tmp_path):
    """Natural-language option replies are handled by LLM extraction, not exact matching."""
    writer = _writer(tmp_path)
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(
                name="paper_mode",
                type="enum",
                required=True,
                choices=("FULL_MANUSCRIPT", "COMPACT_SKELETON"),
            ),
        ),
        timeout_hours=24,
        cancel_keywords=(),
        nl_extract=True,
    )
    plan = MetaPlan(
        name="t",
        triggers=(),
        priority=0,
        steps=(
            MetaStep(id="collect", skill="collect", kind="user_input",
                     clarify_config=cfg),
        ),
    )
    snapshot = to_jsonable(plan)
    with writer._lock:
        writer._conn.execute(
            "INSERT INTO meta_skill_runs "
            "(run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json, "
            " triggered_by, session_key, status, started_at_ms, inputs_json, "
            " awaiting_step_id, awaiting_schema_json, awaiting_since, "
            " awaiting_filled_json, step_outputs_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("r1", "t", "d", json.dumps(snapshot),
             "soft_meta_invoke", "S1", "awaiting_user", 0,
             json.dumps({"user_message": "original trigger", "collected": {}}),
             "collect",
             json.dumps(snapshot["plan"]["steps"][0]["clarify_config"]),
             time.time(), "{}", "{}"),
        )
        writer._conn.commit()

    llm_called = {"count": 0}

    async def _nl_chat(system, user):
        llm_called["count"] += 1
        assert "FULL_MANUSCRIPT" in system
        assert "我选完整论文" in user
        return json.dumps({"paper_mode": "FULL_MANUSCRIPT"})

    loader = MagicMock()
    loader.load_all.return_value = []
    ctx = SimpleNamespace(
        message="我选完整论文",
        session_key="S1",
        metadata={
            "skill_loader": loader,
            "meta_run_writer": writer,
            "meta_llm_chat": _nl_chat,
        },
        system_prompt="",
        config=SimpleNamespace(squilla_router=SimpleNamespace(tiers={})),
        surface_kind="cli",
    )

    out = await meta_resolution(ctx)
    assert "meta_resume" in out.metadata
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {"paper_mode": "FULL_MANUSCRIPT"}
    assert llm_called["count"] == 1


@pytest.mark.asyncio
async def test_nl_extract_receives_prior_step_context_for_referential_replies(tmp_path):
    writer = _writer(tmp_path)
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="accounts", type="string", required=True),
            ClarifyField(name="dimensions", type="string", required=True),
            ClarifyField(
                name="time_window",
                type="enum",
                choices=("LAST_WEEK", "LAST_MONTH", "LAST_QUARTER"),
                default="LAST_MONTH",
            ),
        ),
        timeout_hours=24,
        cancel_keywords=(),
        nl_extract=True,
    )
    plan = MetaPlan(
        name="t",
        triggers=(),
        priority=0,
        steps=(
            MetaStep(
                id="watch_clarify",
                skill="watch_clarify",
                kind="user_input",
                clarify_config=cfg,
            ),
        ),
    )
    snapshot = to_jsonable(plan)
    preferences = (
        "ACCOUNTS:\n"
        "  - 月之暗面\n"
        "  - minimax\n"
        "MISSING_FIELDS:\n"
        "  - dimensions\n"
        "  - time_window"
    )
    with writer._lock:
        writer._conn.execute(
            "INSERT INTO meta_skill_runs "
            "(run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json, "
            " triggered_by, session_key, status, started_at_ms, inputs_json, "
            " awaiting_step_id, awaiting_schema_json, awaiting_since, "
            " awaiting_filled_json, step_outputs_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "r1",
                "t",
                "d",
                json.dumps(snapshot),
                "soft_meta_invoke",
                "S1",
                "awaiting_user",
                0,
                json.dumps({
                    "user_message": "帮我盯一下月之暗面和minimax",
                    "collected": {},
                }),
                "watch_clarify",
                json.dumps(snapshot["plan"]["steps"][0]["clarify_config"]),
                time.time(),
                "{}",
                json.dumps({"preferences": preferences}, ensure_ascii=False),
            ),
        )
        writer._conn.commit()

    async def _nl_chat(system, user):
        assert "<trusted_context>" in user
        assert "帮我盯一下月之暗面和minimax" in user
        assert "MISSING_FIELDS" in user
        assert "time_window" in user
        assert "上面已经提过了" in user
        return json.dumps({
            "accounts": "月之暗面, minimax",
            "dimensions": "PRICING, PRODUCT, LEADERSHIP, HIRING, NEWS",
        })

    loader = MagicMock()
    loader.load_all.return_value = []
    ctx = SimpleNamespace(
        message="1. 上面已经提过了；2. 这些都关注一下；",
        session_key="S1",
        metadata={
            "skill_loader": loader,
            "meta_run_writer": writer,
            "meta_llm_chat": _nl_chat,
        },
        system_prompt="",
        config=SimpleNamespace(squilla_router=SimpleNamespace(tiers={})),
        surface_kind="cli",
    )

    out = await meta_resolution(ctx)
    assert "meta_resume" in out.metadata
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {
        "accounts": "月之暗面, minimax",
        "dimensions": "PRICING, PRODUCT, LEADERSHIP, HIRING, NEWS",
    }


@pytest.mark.asyncio
async def test_nl_extract_disabled_when_flag_false(tmp_path):
    """nl_extract: false (default) → no LLM fallback, even if llm_chat is wired."""
    writer = _writer(tmp_path)
    _seed_awaiting(writer)  # default schema does NOT have nl_extract enabled

    llm_called = {"count": 0}

    async def _nl_chat(system, user):
        llm_called["count"] += 1
        return json.dumps({"x": "Tokyo"})

    loader = MagicMock()
    loader.load_all.return_value = []
    ctx = SimpleNamespace(
        message="multi\nline\nhybrid: x",  # forces deterministic failure
        session_key="S1",
        metadata={
            "skill_loader": loader,
            "meta_run_writer": writer,
            "meta_llm_chat": _nl_chat,
        },
        system_prompt="",
        config=SimpleNamespace(squilla_router=SimpleNamespace(tiers={})),
        surface_kind="cli",
    )
    out = await meta_resolution(ctx)
    # Should be in error state (strike incremented), NOT resumed.
    assert "meta_resume" not in out.metadata
    assert llm_called["count"] == 0


# ── PR4: real parser happy-path integration ──

@pytest.mark.asyncio
async def test_real_parser_key_value_success_claims_resume(tmp_path):
    """End-to-end: with the real clarify_text parser, a valid 'key: value'
    reply succeeds → try_claim_resume CAS fires → meta_resume metadata set."""
    writer = _writer(tmp_path)
    _seed_awaiting(writer)
    # Schema has one required string field "x".
    ctx = _ctx(writer, message="x: Tokyo", session_id="S1")
    out = await meta_resolution(ctx)
    assert "meta_resume" in out.metadata
    claim, parsed = out.metadata["meta_resume"]
    assert claim.run_id == "r1"
    assert parsed == {"x": "Tokyo"}
    assert writer.peek_awaiting(session_id="S1") is None


@pytest.mark.asyncio
async def test_real_parser_positional_success_claims_resume(tmp_path):
    """Positional-mode reply also succeeds end-to-end."""
    writer = _writer(tmp_path)
    _seed_awaiting(writer)
    ctx = _ctx(writer, message="Shanghai", session_id="S1")
    out = await meta_resolution(ctx)
    assert "meta_resume" in out.metadata
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {"x": "Shanghai"}
