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


@pytest.fixture(autouse=True)
def _inline_to_thread_for_meta_resolution_tests(monkeypatch):
    """Keep meta_resolution CAS tests deterministic in the sandbox."""
    import importlib

    mr_module = importlib.import_module("opensquilla.engine.steps.meta_resolution")

    async def _inline_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(mr_module.asyncio, "to_thread", _inline_to_thread)


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
async def test_clarify_form_submit_autofills_delegated_required_answer(tmp_path):
    """Structured form submissions skip nl_extract, but delegated required
    answers like ``都可以`` still need concrete server-side completion."""
    writer = _writer(tmp_path)
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="topic", type="string", required=True),
            ClarifyField(
                name="age_band",
                type="enum",
                required=True,
                choices=("PRE_K", "EARLY_GRADE"),
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
                id="collect",
                skill="collect",
                kind="user_input",
                clarify_config=cfg,
            ),
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
            (
                "r1",
                "t",
                "d",
                json.dumps(snapshot),
                "soft_meta_invoke",
                "S1",
                "awaiting_user",
                0,
                json.dumps({"user_message": "original trigger", "collected": {}}),
                "collect",
                json.dumps(snapshot["plan"]["steps"][0]["clarify_config"]),
                time.time(),
                "{}",
                "{}",
            ),
        )
        writer._conn.commit()

    llm_called = {"count": 0}

    async def _nl_chat(system, user):
        llm_called["count"] += 1
        return json.dumps({"topic": "磁力迷宫"})

    loader = MagicMock()
    loader.load_all.return_value = []
    ctx = SimpleNamespace(
        message="topic: 都可以\nage_band: PRE_K",
        session_key="S1",
        metadata={
            "skill_loader": loader,
            "meta_run_writer": writer,
            "meta_llm_chat": _nl_chat,
            "input_provenance": {"kind": "clarify_form", "source": "webui"},
        },
        system_prompt="",
        config=SimpleNamespace(squilla_router=SimpleNamespace(tiers={})),
        surface_kind="web",
    )

    out = await meta_resolution(ctx)

    assert "meta_resume" in out.metadata
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {"topic": "磁力迷宫", "age_band": "PRE_K"}
    assert llm_called["count"] == 1
    assert out.metadata["meta_clarify_autofilled_fields"] == ["topic"]


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


# ── Bug-X (required completeness) + Bug-Y (awaiting_filled merge) ──


def _seed_awaiting_multi_field(
    writer,
    *,
    fields: tuple[ClarifyField, ...],
    awaiting_filled: dict | None = None,
    nl_extract: bool = False,
):
    """Seed an awaiting run with a multi-field schema and optional pre-filled
    answers. Mirrors ``_seed_awaiting`` but accepts a custom field tuple and
    allows pre-populating ``awaiting_filled_json`` to model the chat-mode
    scenario where the user answered one field per turn."""
    cfg = ClarifyStepConfig(
        mode="form",
        fields=fields,
        timeout_hours=24,
        cancel_keywords=(),
        nl_extract=nl_extract,
    )
    plan = MetaPlan(
        name="t",
        triggers=(),
        priority=0,
        steps=(
            MetaStep(
                id="collect", skill="collect", kind="user_input",
                clarify_config=cfg,
            ),
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
             time.time(),
             json.dumps(awaiting_filled or {}), "{}"),
        )
        writer._conn.commit()
    return plan


@pytest.mark.asyncio
async def test_deterministic_success_merges_previously_filled(tmp_path):
    """Bug-Y deterministic branch: a chat-mode user who filled ``city``
    in an earlier turn and ``days`` in the current turn must see the
    cumulative ``{city, days}`` propagated to ``meta_resume``. Without
    the merge, ``city`` would silently disappear from the DAG resume
    payload."""
    writer = _writer(tmp_path)
    _seed_awaiting_multi_field(
        writer,
        fields=(
            ClarifyField(name="city", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ),
        awaiting_filled={"city": "Tokyo"},
    )
    ctx = _ctx(writer, message="days: 5", session_id="S1")
    out = await meta_resolution(ctx)
    assert "meta_resume" in out.metadata, (
        f"expected resume after merge; got metadata={dict(out.metadata)}"
    )
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {"city": "Tokyo", "days": 5}, (
        f"merged state must include both previously-filled and current-turn "
        f"fields; got {parsed!r}"
    )


@pytest.mark.asyncio
async def test_nl_success_rejects_incomplete_required(tmp_path):
    """Soft-clarify contract: when the NL extractor returns only some
    required fields with the default FILL intent, the DAG must NOT
    resume (Bug-X), but it must ALSO NOT slam the form back as a
    hard reprompt. Instead the resolver writes the partial fill to
    ``awaiting_filled_json`` and stashes a ``meta_clarify_soft_progress``
    payload so the LLM can naturally acknowledge what was captured
    while letting the user keep chatting."""
    writer = _writer(tmp_path)
    _seed_awaiting_multi_field(
        writer,
        fields=(
            ClarifyField(name="city", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ),
        nl_extract=True,
    )
    # LLM extracts only ``city`` — ``days`` is still required but missing
    # both from previously_filled and from the current reply.
    ctx = _ctx_with_nl_chat(
        writer,
        message="we want to go to Tokyo",
        llm_response=json.dumps({
            "intent": "FILL",
            "fields": {"city": "Tokyo"},
            "ambiguous_fields": [],
            "unknown_mentions": [],
        }),
    )
    out = await meta_resolution(ctx)
    assert "meta_resume" not in out.metadata, (
        f"NL path must not resume with missing required field; got "
        f"metadata={dict(out.metadata)}"
    )
    # Soft-clarify: no hard reprompt, just incremental progress.
    assert "meta_clarify_errors" not in out.metadata
    progress = out.metadata.get("meta_clarify_soft_progress")
    assert progress is not None, (
        f"expected soft_progress, got metadata={dict(out.metadata)}"
    )
    assert progress["filled"] == {"city": "Tokyo"}
    assert progress["missing_required"] == ["days"]
    assert "city" in progress["newly_filled"]


@pytest.mark.asyncio
async def test_deterministic_missing_required_autofills_and_resumes(tmp_path):
    """A form reply that omits required fields should no longer trap the
    user in a reprompt loop. The resolver infers the missing required
    values, then resumes with a complete payload."""
    writer = _writer(tmp_path)
    _seed_awaiting_multi_field(
        writer,
        fields=(
            ClarifyField(name="city", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ),
    )
    ctx = _ctx(writer, message="days: 5", session_id="S1")
    async def fake_chat(_system: str, _user: str) -> str:
        return '{"city": "Tokyo"}'

    ctx.metadata["meta_llm_chat"] = fake_chat
    out = await meta_resolution(ctx)
    assert "meta_resume" in out.metadata, (
        f"missing required field should be inferred; got metadata={dict(out.metadata)}"
    )
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {"days": 5, "city": "Tokyo"}
    assert out.metadata["meta_clarify_autofilled_fields"] == ["city"]


@pytest.mark.asyncio
async def test_deterministic_uninformative_required_answer_is_autofilled(tmp_path):
    """Delegating answers such as ``都可以`` are treated as permission for the
    runtime to choose a concrete value, not as useful field content."""
    writer = _writer(tmp_path)
    _seed_awaiting_multi_field(
        writer,
        fields=(
            ClarifyField(name="budget", type="string", required=True),
            ClarifyField(name="age", type="int", required=True, min=6, max=12),
        ),
    )
    ctx = _ctx(writer, message="budget: 都可以\nage: 9", session_id="S1")

    async def fake_chat(_system: str, _user: str) -> str:
        return '{"budget": "100 元以内"}'

    ctx.metadata["meta_llm_chat"] = fake_chat
    out = await meta_resolution(ctx)

    assert "meta_resume" in out.metadata
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {"budget": "100 元以内", "age": 9}
    assert out.metadata["meta_clarify_autofilled_fields"] == ["budget"]


@pytest.mark.asyncio
async def test_nl_success_merges_previously_filled(tmp_path):
    """Bug-Y NL branch: the NL extractor returning the LAST missing
    required field must resume with the cumulative state, not just the
    just-extracted slice. Combined with Bug-X this is the chat-mode
    happy path where the user filled ``city`` last turn and ``days``
    this turn."""
    writer = _writer(tmp_path)
    _seed_awaiting_multi_field(
        writer,
        fields=(
            ClarifyField(name="city", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ),
        awaiting_filled={"city": "Tokyo"},
        nl_extract=True,
    )
    ctx = _ctx_with_nl_chat(
        writer,
        message="five days please",
        llm_response=json.dumps({"days": 5}),
    )
    out = await meta_resolution(ctx)
    assert "meta_resume" in out.metadata, (
        f"NL path must resume once the merged state satisfies all required; "
        f"got metadata={dict(out.metadata)}"
    )
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {"city": "Tokyo", "days": 5}, (
        f"merged state must include both previously-filled and NL-extracted "
        f"fields; got {parsed!r}"
    )


# ── F-history step (b): conversation_history injection ──


def _awaiting_stub(*, step_id="collect", inputs=None, filled=None, outputs=None):
    """Lightweight stand-in for ``writer.peek_awaiting`` rows used by
    ``_clarify_extract_context``. We rely only on the four JSON columns
    so a SimpleNamespace is enough — no DB."""
    return SimpleNamespace(
        run_id="r-test",
        step_id=step_id,
        awaiting_since=time.time(),
        awaiting_session_id="S1",
        awaiting_schema_json="{}",
        awaiting_filled_json=json.dumps(filled or {}),
        step_outputs_json=json.dumps(outputs or {}),
        inputs_json=json.dumps(inputs or {"user_message": "trigger"}),
        parse_failure_count=0,
    )


def _ctx_stub(*, conversation_history=None) -> SimpleNamespace:
    """Minimal TurnContext-shaped stub. ``_clarify_extract_context``
    only reads ``ctx.metadata``, so a SimpleNamespace is sufficient."""
    metadata: dict[str, object] = {}
    if conversation_history is not None:
        metadata["conversation_history"] = conversation_history
    return SimpleNamespace(metadata=metadata)


def test_clarify_context_omits_history_when_metadata_missing() -> None:
    """Without an upstream gateway/agent injecting history, the
    resolver must behave exactly as before — the
    ``conversation_history`` key is absent so the NL extractor sees
    today's prompt shape."""
    from opensquilla.engine.steps.meta_resolution import _clarify_extract_context

    awaiting = _awaiting_stub()
    ctx = _ctx_stub()  # no conversation_history key

    out = _clarify_extract_context(awaiting, [], ctx)
    assert "conversation_history" not in out


def test_clarify_context_omits_history_when_ctx_is_none() -> None:
    """Backwards compatibility: ``ctx`` is optional. Callers that
    haven't migrated yet still get a fully-formed context dict."""
    from opensquilla.engine.steps.meta_resolution import _clarify_extract_context

    out = _clarify_extract_context(_awaiting_stub(), [])
    assert "conversation_history" not in out


def test_clarify_context_renders_history_with_role_lines() -> None:
    """Three-turn slice (newest last) rendered as ``[role] text`` lines.
    Each turn is clipped to 200 chars; the OpenAI-style content-block
    list is flattened to plain text."""
    from opensquilla.engine.steps.meta_resolution import _clarify_extract_context

    long_user_text = "user said " * 80   # ~800 chars → must be clipped
    history = [
        {"role": "user", "content": "I want to plan a trip"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Sure, where to?"},
            {"type": "image", "image_url": "..."},
        ]},
        {"role": "user", "content": long_user_text},
    ]
    ctx = _ctx_stub(conversation_history=history)

    out = _clarify_extract_context(_awaiting_stub(), [], ctx)
    block = out.get("conversation_history")
    assert isinstance(block, str) and block

    # Three lines, in order, each prefixed with role.
    lines = block.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("[user] I want to plan a trip")
    assert lines[1].startswith("[assistant] Sure, where to?")
    # Image block ignored, text-only flattened.
    assert "image_url" not in lines[1]
    # Long turn clipped.
    assert lines[2].startswith("[user] ")
    assert "...[truncated]" in lines[2]
    assert len(lines[2]) <= 200 + len("[user] ") + len("...[truncated]")


def test_clarify_context_history_takes_last_three_turns_only() -> None:
    """A long backlog must be sliced to the last three turns so the
    prompt budget stays bounded."""
    from opensquilla.engine.steps.meta_resolution import _clarify_extract_context

    history = [
        {"role": "user", "content": f"turn {i}"} for i in range(10)
    ]
    ctx = _ctx_stub(conversation_history=history)

    out = _clarify_extract_context(_awaiting_stub(), [], ctx)
    block = out["conversation_history"]
    lines = block.splitlines()
    assert len(lines) == 3
    # The retained slice is the LAST three turns (7, 8, 9).
    assert lines[0].endswith("turn 7")
    assert lines[2].endswith("turn 9")


def test_clarify_context_history_skips_non_text_entries() -> None:
    """Malformed or unknown-shape entries must not break the channel —
    the resolver is fail-open by design so a bad history feed cannot
    block a clarify run."""
    from opensquilla.engine.steps.meta_resolution import _clarify_extract_context

    history = [
        "raw string with no role",  # not a Mapping
        {"role": "tool", "content": ""},  # empty content
        {"role": "user", "content": "real turn"},
    ]
    ctx = _ctx_stub(conversation_history=history)

    out = _clarify_extract_context(_awaiting_stub(), [], ctx)
    block = out.get("conversation_history", "")
    assert block == "[user] real turn"


def test_clarify_context_history_ignores_non_list_metadata() -> None:
    """If a misconfigured upstream sets the metadata key to a string
    or dict instead of a list, the resolver must not crash. Ignoring
    it silently mirrors the existing fail-open contract."""
    from opensquilla.engine.steps.meta_resolution import _clarify_extract_context

    for bogus in ("not a list", {"role": "user"}, 42):
        ctx = _ctx_stub(conversation_history=bogus)
        out = _clarify_extract_context(_awaiting_stub(), [], ctx)
        assert "conversation_history" not in out


# ── C2 producer fallback: synthesise history from router metadata ──


def test_clarify_context_history_uses_router_metadata_fallback() -> None:
    """When no explicit ``conversation_history`` is injected, the
    resolver must synthesise a history block from the squilla router's
    existing ``router_history_user_texts`` and
    ``router_prev_assistant_text`` channels (already populated for
    every turn). This is the C2 producer hook — without an extra
    ingress hop, every live-traffic clarify run automatically gets
    the last user turns + the last assistant reply."""
    from opensquilla.engine.steps.meta_resolution import _clarify_extract_context

    ctx = SimpleNamespace(metadata={
        "router_history_user_texts": [
            "I want to plan a trip next month",
            "Probably Tokyo or Osaka",
        ],
        "router_prev_assistant_text": "Sure, what dates are you thinking?",
    })
    out = _clarify_extract_context(_awaiting_stub(), [], ctx)
    block = out.get("conversation_history", "")
    lines = block.splitlines()
    # Expect the two router-recorded user turns plus the assistant
    # reply, in order, each tagged with its role.
    assert any(
        line.startswith("[user] I want to plan a trip next month")
        for line in lines
    ), block
    assert any(
        line.startswith("[user] Probably Tokyo or Osaka")
        for line in lines
    ), block
    assert any(
        line.startswith("[assistant] Sure, what dates")
        for line in lines
    ), block


def test_clarify_context_explicit_history_takes_priority_over_router_fallback() -> None:
    """If both the canonical ``conversation_history`` key and the
    router fallback are present, the canonical key wins. This makes
    the upgrade path safe — a future channel adapter that wants to
    inject a richer history (e.g. from a longer transcript window)
    fully replaces the router-derived fallback rather than
    appending to it."""
    from opensquilla.engine.steps.meta_resolution import _clarify_extract_context

    ctx = SimpleNamespace(metadata={
        "conversation_history": [
            {"role": "user", "content": "explicit injection"},
        ],
        "router_history_user_texts": ["should not appear"],
        "router_prev_assistant_text": "should not appear either",
    })
    out = _clarify_extract_context(_awaiting_stub(), [], ctx)
    block = out["conversation_history"]
    assert "explicit injection" in block
    assert "should not appear" not in block


def test_clarify_context_history_router_fallback_assistant_only() -> None:
    """A turn with no user history (first turn after a reset, but the
    previous assistant reply survived) must still produce a useful
    one-line history block from the assistant text alone."""
    from opensquilla.engine.steps.meta_resolution import _clarify_extract_context

    ctx = SimpleNamespace(metadata={
        "router_prev_assistant_text": "I can help plan a Tokyo trip.",
    })
    out = _clarify_extract_context(_awaiting_stub(), [], ctx)
    block = out.get("conversation_history", "")
    assert block.startswith("[assistant] I can help plan a Tokyo trip.")


# ── Step (d): prefill audit propagates to ctx.metadata ──


@pytest.mark.asyncio
async def test_prefill_audit_surfaces_to_metadata_on_reprompt(tmp_path):
    """Step (d) + soft-clarify: when the prefill scan seeded
    ``awaiting_filled_json`` with a ``__prefill_audit__`` payload,
    the resolver must extract it and stash it on
    ``ctx.metadata["meta_clarify_prefill_audit"]`` regardless of
    which branch handles this turn. Under the new soft-clarify
    contract a missing required field yields
    ``meta_clarify_soft_progress`` (not the legacy ``meta_clarify_reprompt``)
    while the audit stays visible so the surface can keep rendering
    the ``confirmed_fields`` protocol."""
    writer = _writer(tmp_path)
    _seed_awaiting_multi_field(
        writer,
        fields=(
            ClarifyField(name="city", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ),
        awaiting_filled={
            "city": "Tokyo",
            "__prefill_audit__": {
                "source": "auto_prefill",
                "fields": ["city"],
                "ambiguous": [{"name": "days", "reason": "no duration"}],
                "unknown_mentions": [],
            },
        },
        nl_extract=True,
    )
    # The user's reply does not satisfy the missing required ``days``,
    # so this turn stays in soft-clarify rather than resuming.
    ctx = _ctx_with_nl_chat(
        writer,
        message="Tokyo it is",
        llm_response=json.dumps({
            "intent": "FILL",
            "fields": {"city": "Tokyo"},
            "ambiguous_fields": [],
            "unknown_mentions": [],
        }),
    )
    out = await meta_resolution(ctx)

    audit = out.metadata.get("meta_clarify_prefill_audit")
    assert isinstance(audit, dict)
    assert audit["source"] == "auto_prefill"
    assert audit["fields"] == ["city"]
    # Soft-clarify path — no resume, no legacy reprompt, but the
    # progress payload tells the LLM what's still missing.
    assert "meta_resume" not in out.metadata
    progress = out.metadata.get("meta_clarify_soft_progress")
    assert progress is not None
    assert "days" in progress["missing_required"]


@pytest.mark.asyncio
async def test_prefill_audit_stripped_from_resume_payload(tmp_path):
    """Step (d): the reserved ``__prefill_audit__`` key must NOT
    leak into the merged state passed to the DAG resume. Downstream
    steps see only schema-declared fields. Without this guard,
    ``__prefill_audit__`` would be visible to every step that
    reads ``inputs.collected``."""
    writer = _writer(tmp_path)
    _seed_awaiting_multi_field(
        writer,
        fields=(
            ClarifyField(name="city", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ),
        awaiting_filled={
            "city": "Tokyo",
            "__prefill_audit__": {
                "source": "auto_prefill",
                "fields": ["city"],
                "ambiguous": [],
                "unknown_mentions": [],
            },
        },
        nl_extract=True,
    )
    ctx = _ctx_with_nl_chat(
        writer,
        message="five days",
        llm_response=json.dumps({"days": 5}),
    )
    out = await meta_resolution(ctx)

    assert "meta_resume" in out.metadata
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {"city": "Tokyo", "days": 5}
    assert "__prefill_audit__" not in parsed


# ── Soft-clarify (free-form continuation) ──


@pytest.mark.asyncio
async def test_soft_clarify_proceed_now_with_complete_required_resumes(
    tmp_path,
):
    """When the user explicitly signals readiness (``intent: PROCEED_NOW``)
    and every required field is satisfied (either by this turn's
    extract or carried-over state), the DAG resumes immediately
    without forcing another round of clarification."""
    writer = _writer(tmp_path)
    _seed_awaiting_multi_field(
        writer,
        fields=(
            ClarifyField(name="city", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ),
        awaiting_filled={"city": "Tokyo"},
        nl_extract=True,
    )
    ctx = _ctx_with_nl_chat(
        writer,
        message="five days, go ahead",
        llm_response=json.dumps({
            "intent": "PROCEED_NOW",
            "fields": {"days": 5},
            "ambiguous_fields": [],
            "unknown_mentions": [],
        }),
    )
    out = await meta_resolution(ctx)
    assert "meta_resume" in out.metadata
    _, parsed = out.metadata["meta_resume"]
    assert parsed == {"city": "Tokyo", "days": 5}


@pytest.mark.asyncio
async def test_soft_clarify_proceed_now_blocked_when_required_missing(
    tmp_path,
):
    """If the user says PROCEED_NOW but a required field is still
    unfilled, the resolver must NOT resume blindly. It surfaces a
    ``meta_clarify_proceed_blocked`` payload so the assistant can
    naturally tell the user what's still missing."""
    writer = _writer(tmp_path)
    _seed_awaiting_multi_field(
        writer,
        fields=(
            ClarifyField(name="city", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ),
        nl_extract=True,
    )
    ctx = _ctx_with_nl_chat(
        writer,
        message="just start already",
        llm_response=json.dumps({
            "intent": "PROCEED_NOW",
            "fields": {},
            "ambiguous_fields": [],
            "unknown_mentions": [],
        }),
    )
    out = await meta_resolution(ctx)
    assert "meta_resume" not in out.metadata
    blocked = out.metadata.get("meta_clarify_proceed_blocked")
    assert blocked is not None
    assert set(blocked["missing_required"]) == {"city", "days"}


@pytest.mark.asyncio
async def test_soft_clarify_cancel_all_intent_marks_cancelled(tmp_path):
    """The CANCEL_ALL intent emitted by the NL extractor must take
    the same path as a substring cancel keyword — the awaiting run
    is marked cancelled and the resolver surfaces
    ``meta_clarify_cancelled``."""
    writer = _writer(tmp_path)
    _seed_awaiting_multi_field(
        writer,
        fields=(
            ClarifyField(name="city", type="string", required=True),
        ),
        nl_extract=True,
    )
    ctx = _ctx_with_nl_chat(
        writer,
        message="actually never mind, drop the whole thing",
        llm_response=json.dumps({
            "intent": "CANCEL_ALL",
            "fields": {},
            "ambiguous_fields": [],
            "unknown_mentions": [],
        }),
    )
    out = await meta_resolution(ctx)
    assert out.metadata.get("meta_clarify_cancelled") is not None
    assert out.metadata.get("meta_clarify_cancel_reason") == "user_cancel_nl"


@pytest.mark.asyncio
async def test_soft_clarify_persists_partial_fill_across_turns(tmp_path):
    """Soft-clarify must persist every partial fill into
    ``awaiting_filled_json`` so the next turn's prior_filled view is
    cumulative. Run two ``meta_resolution`` turns and assert the
    persisted state grows."""
    writer = _writer(tmp_path)
    _seed_awaiting_multi_field(
        writer,
        fields=(
            ClarifyField(name="city", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ),
        nl_extract=True,
    )

    # Turn 1 — fill city only.
    ctx1 = _ctx_with_nl_chat(
        writer,
        message="we want to go to Tokyo",
        llm_response=json.dumps({
            "intent": "FILL",
            "fields": {"city": "Tokyo"},
            "ambiguous_fields": [],
            "unknown_mentions": [],
        }),
    )
    out1 = await meta_resolution(ctx1)
    assert "meta_resume" not in out1.metadata
    assert "meta_clarify_soft_progress" in out1.metadata
    # The persisted state must now include city at the top level
    # (matching the awaiting-resume contract: flat ``{field: value,
    # __prefill_audit__: ...}``).
    awaiting1 = writer.peek_awaiting(session_id="S1")
    assert awaiting1 is not None
    persisted1 = json.loads(awaiting1.awaiting_filled_json)
    assert persisted1.get("city") == "Tokyo"

    # Turn 2 — provide days. Cumulative state should include both
    # AND the DAG should resume because everything required is now
    # satisfied (FILL intent + complete = auto-resume).
    ctx2 = _ctx_with_nl_chat(
        writer,
        message="five days please",
        llm_response=json.dumps({
            "intent": "FILL",
            "fields": {"days": 5},
            "ambiguous_fields": [],
            "unknown_mentions": [],
        }),
    )
    out2 = await meta_resolution(ctx2)
    assert "meta_resume" in out2.metadata, (
        f"expected auto-resume on complete fields, got "
        f"metadata={dict(out2.metadata)}"
    )
    _, parsed = out2.metadata["meta_resume"]
    assert parsed == {"city": "Tokyo", "days": 5}
