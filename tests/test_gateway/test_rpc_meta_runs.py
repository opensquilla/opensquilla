"""Read-only meta-skill run history RPC handlers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from opensquilla.gateway.auth import Principal
from opensquilla.gateway.protocol import ERROR_UNAUTHORIZED
from opensquilla.gateway.rpc import get_dispatcher
from opensquilla.gateway.rpc.registry import RpcContext
from opensquilla.gateway.rpc_meta_runs import (
    _bounded_limit,
    _handle_meta_runs_draft,
    _handle_meta_runs_failures,
    _handle_meta_runs_list,
    _handle_meta_runs_show,
)
from opensquilla.gateway.scopes import ADMIN_SCOPE, METHOD_SCOPES, READ_SCOPE
from opensquilla.persistence.meta_run_writer import open_meta_run_writer
from opensquilla.persistence.migrator import apply_pending
from opensquilla.skills.meta.types import MetaPlan, MetaResult, MetaStep

MIGRATIONS_DIR = Path(__file__).resolve().parents[1].parent / "migrations"


def _seed_writer(tmp_path: Path):
    db = str(tmp_path / "runs.db")
    apply_pending(db, MIGRATIONS_DIR)
    writer = open_meta_run_writer(db)
    plan = MetaPlan(
        name="alpha-skill",
        triggers=("alpha request",),
        priority=10,
        steps=(MetaStep(id="s1", skill="writer", kind="agent", label="Write"),),
        request_template={
            "outcome": "Brief",
            "fields": [{"name": "audience"}, {"name": "language"}],
        },
        output_contract={"required_sections": ["Summary"]},
        eval_prompts=[{
            "name": "brief",
            "prompt": "Write an alpha brief",
            "rubric": ["Summary"],
        }],
    )
    run_id = writer.begin_run_sync(
        meta_skill_name="alpha-skill",
        meta_plan=plan,
        triggered_by="soft_meta_invoke",
        inputs={"user_message": "Write an alpha brief"},
        session_key="sess-1",
        turn_id="turn-1",
    )
    writer.begin_step_sync(
        run_id=run_id,
        step=plan.steps[0],
        effective_skill="writer",
        rendered_inputs={"task": "Write an alpha brief"},
    )
    writer.finish_step_sync(
        run_id=run_id,
        step_id="s1",
        status="ok",
        output_text="done",
    )
    writer.finish_run_sync(
        run_id=run_id,
        status="ok",
        result=MetaResult(ok=True, final_text="done"),
    )
    return writer, run_id


def test_meta_runs_list_rpc_returns_summary(tmp_path: Path) -> None:
    writer, run_id = _seed_writer(tmp_path)
    try:
        ctx = RpcContext(conn_id="test", meta_run_writer=writer)
        payload = asyncio.run(_handle_meta_runs_list({"limit": 5}, ctx))
    finally:
        writer.close()

    assert payload["runs"][0]["run_id"] == run_id
    assert payload["runs"][0]["summary"]["step_count"] == 1
    assert payload["runs"][0]["summary"]["usage"]["available"] is False
    assert "inputs_json" not in payload["runs"][0]
    assert "plan_snapshot_json" not in payload["runs"][0]
    assert "final_text" not in payload["runs"][0]
    assert "steps" not in payload["runs"][0]
    assert "output_text" not in payload["runs"][0]["summary"]["steps"][0]
    assert "rendered_inputs_json" not in payload["runs"][0]["summary"]["steps"][0]


def test_meta_runs_failures_rpc_returns_summary_only(tmp_path: Path) -> None:
    writer, run_id = _seed_writer(tmp_path)
    writer.finish_run_sync(
        run_id=run_id,
        status="failed",
        result=MetaResult(
            ok=False,
            error="raw secret failure detail",
            failed_step_id="s1",
        ),
    )
    try:
        ctx = RpcContext(conn_id="test", meta_run_writer=writer)
        payload = asyncio.run(_handle_meta_runs_failures({"limit": 500}, ctx))
    finally:
        writer.close()

    run = payload["runs"][0]
    assert run["run_id"] == run_id
    assert run["error_present"] is True
    assert "error" not in run
    assert "inputs_json" not in run
    assert "final_text" not in run


def test_meta_runs_show_rpc_returns_steps(tmp_path: Path) -> None:
    writer, run_id = _seed_writer(tmp_path)
    try:
        ctx = RpcContext(conn_id="test", meta_run_writer=writer)
        payload = asyncio.run(_handle_meta_runs_show({"runId": run_id}, ctx))
    finally:
        writer.close()

    run = payload["run"]
    assert run["run_id"] == run_id
    assert run["steps"][0]["step_id"] == "s1"
    assert run["summary"]["steps"][0]["output_chars"] == 4


def test_meta_runs_draft_rpc_returns_author_seed(tmp_path: Path) -> None:
    writer, run_id = _seed_writer(tmp_path)
    try:
        ctx = RpcContext(conn_id="test", meta_run_writer=writer)
        payload = asyncio.run(_handle_meta_runs_draft({"runId": run_id}, ctx))
    finally:
        writer.close()

    draft = payload["draft"]
    assert draft["source_run"]["run_id"] == run_id
    assert draft["name"] == "alpha-skill-draft"
    assert draft["request_template"]["outcome"] == "Brief"
    assert draft["eval_prompts"][0]["name"] == "brief"


def test_meta_runs_rpc_scope_contract() -> None:
    assert METHOD_SCOPES["meta.runs.list"] == READ_SCOPE
    assert METHOD_SCOPES["meta.runs.failures"] == READ_SCOPE
    assert METHOD_SCOPES["meta.runs.show"] == ADMIN_SCOPE
    assert METHOD_SCOPES["meta.runs.draft"] == ADMIN_SCOPE


@pytest.mark.asyncio
async def test_meta_runs_show_and_draft_deny_read_only_dispatch(tmp_path: Path) -> None:
    writer, run_id = _seed_writer(tmp_path)
    read_only = Principal(
        role="operator",
        scopes=frozenset({READ_SCOPE}),
        is_owner=False,
        authenticated=True,
    )
    try:
        ctx = RpcContext(conn_id="test", principal=read_only, meta_run_writer=writer)
        dispatcher = get_dispatcher()
        for method in ("meta.runs.show", "meta.runs.draft"):
            res = await dispatcher.dispatch("r1", method, {"runId": run_id}, ctx)
            assert res.error is not None
            assert res.error.code == ERROR_UNAUTHORIZED
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_meta_runs_read_only_requires_session_key_for_history(tmp_path: Path) -> None:
    writer, _run_id = _seed_writer(tmp_path)
    read_only = Principal(
        role="operator",
        scopes=frozenset({READ_SCOPE}),
        is_owner=False,
        authenticated=True,
    )
    try:
        ctx = RpcContext(conn_id="test", principal=read_only, meta_run_writer=writer)
        dispatcher = get_dispatcher()
        for method in ("meta.runs.list", "meta.runs.failures"):
            res = await dispatcher.dispatch("r1", method, {"limit": 5}, ctx)
            assert res.error is not None
            assert res.error.code == ERROR_UNAUTHORIZED
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_meta_runs_read_only_denies_arbitrary_session_key(tmp_path: Path) -> None:
    writer, run_id = _seed_writer(tmp_path)
    read_only = Principal(
        role="operator",
        scopes=frozenset({READ_SCOPE}),
        is_owner=False,
        authenticated=True,
    )
    try:
        ctx = RpcContext(conn_id="test", principal=read_only, meta_run_writer=writer)
        res = await get_dispatcher().dispatch(
            "r1",
            "meta.runs.list",
            {"sessionKey": "sess-1", "limit": 5},
            ctx,
        )
        assert res.error is not None
        assert res.error.code == ERROR_UNAUTHORIZED
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_meta_runs_failures_read_only_denies_arbitrary_session_key(
    tmp_path: Path,
) -> None:
    writer, run_id = _seed_writer(tmp_path)
    writer.finish_run_sync(
        run_id=run_id,
        status="failed",
        result=MetaResult(ok=False, error="failed", failed_step_id="s1"),
    )
    read_only = Principal(
        role="operator",
        scopes=frozenset({READ_SCOPE}),
        is_owner=False,
        authenticated=True,
    )
    try:
        ctx = RpcContext(conn_id="test", principal=read_only, meta_run_writer=writer)
        res = await get_dispatcher().dispatch(
            "r1",
            "meta.runs.failures",
            {"sessionKey": "sess-1", "limit": 5},
            ctx,
        )
        assert res.error is not None
        assert res.error.code == ERROR_UNAUTHORIZED
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_meta_runs_owner_read_scope_allows_session_history(tmp_path: Path) -> None:
    writer, run_id = _seed_writer(tmp_path)
    owner_read = Principal(
        role="operator",
        scopes=frozenset({READ_SCOPE}),
        is_owner=True,
        authenticated=False,
    )
    try:
        ctx = RpcContext(conn_id="test", principal=owner_read, meta_run_writer=writer)
        res = await get_dispatcher().dispatch(
            "r1",
            "meta.runs.list",
            {"sessionKey": "sess-1", "limit": 5},
            ctx,
        )
        assert res.error is None, res.error
        assert res.payload["runs"][0]["run_id"] == run_id
    finally:
        writer.close()


def test_meta_runs_rpc_limit_is_bounded() -> None:
    assert _bounded_limit(None) == 50
    assert _bounded_limit(-1) == 50
    assert _bounded_limit("5000") == 100
    assert _bounded_limit("12") == 12


def test_meta_runs_rpc_does_not_import_cli_private_helpers() -> None:
    source = Path("src/opensquilla/gateway/rpc_meta_runs.py").read_text()
    assert "opensquilla.cli.skills_meta_cmd" not in source
    assert "_meta_run_writer" not in source
