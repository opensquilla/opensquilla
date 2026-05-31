"""Session deletion cascades to meta_skill_runs via purge_for_session."""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.persistence.meta_run_writer import open_meta_run_writer
from opensquilla.persistence.migrator import apply_pending
from opensquilla.session.models import SessionNode
from opensquilla.session.storage import SessionStorage
from opensquilla.skills.meta.types import MetaPlan, MetaStep

MIGRATIONS_DIR = Path(__file__).resolve().parents[1].parent / "migrations"


@pytest.mark.asyncio
async def test_delete_session_purges_meta_runs(tmp_path: Path) -> None:
    db = str(tmp_path / "session.db")
    apply_pending(db, MIGRATIONS_DIR)

    # Pre-populate a meta run for sess-doomed.
    writer = open_meta_run_writer(db)
    plan = MetaPlan(
        name="x",
        triggers=("t",),
        priority=10,
        steps=(MetaStep(id="s1", skill="a", kind="agent"),),
    )
    run_id = writer.begin_run_sync(
        meta_skill_name="x",
        meta_plan=plan,
        triggered_by="soft_meta_invoke",
        inputs={},
        session_key="sess-doomed",
        turn_id=None,
    )
    writer.finish_run_sync(run_id=run_id, status="ok", result=None)
    assert writer.list_runs(session_key="sess-doomed"), "precondition: row exists"

    # Build a SessionStorage with the writer injected.
    storage = SessionStorage(db_path=db, meta_run_writer=writer)
    await storage.connect()

    # Seed the session row so DELETE has a target.
    await storage.upsert_session(SessionNode(session_key="sess-doomed"))

    # Act
    await storage.delete_session("sess-doomed")

    # Assert: meta_skill_runs row is gone.
    assert writer.list_runs(session_key="sess-doomed") == []
    writer.close()
    await storage.close()
