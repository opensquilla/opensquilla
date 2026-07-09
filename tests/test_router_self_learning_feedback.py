"""Feedback sidecar: write/merge/revoke/stats/retention semantics."""

from __future__ import annotations

from datetime import UTC, datetime

from opensquilla.squilla_router.self_learning.feedback import (
    FeedbackStats,
    feedback_path,
    load_feedback_map,
    scan_feedback_stats,
    write_feedback,
)

NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)


def _write(
    tmp_path, decision_id, rating, *,
    turn=0, kind="single", now=NOW, session="agent:main:webchat:s1",
):
    return write_feedback(
        "main",
        decision_id=decision_id,
        session_key=session,
        turn_index=turn,
        rating=rating,
        executed_kind=kind,
        home=tmp_path,
        now=now,
    )


def test_write_and_load_roundtrip(tmp_path) -> None:
    _write(tmp_path, "d1", "down")
    _write(tmp_path, "d2", "up", turn=1)

    fb = load_feedback_map("main", home=tmp_path)
    assert fb["d1"].rating == "down"
    assert fb["d2"].rating == "up"
    assert all(e.executed_kind == "single" for e in fb.values())


def test_last_write_wins_per_decision(tmp_path) -> None:
    _write(tmp_path, "d1", "down")
    _write(tmp_path, "d1", "up")

    fb = load_feedback_map("main", home=tmp_path)
    assert fb["d1"].rating == "up"


def test_neutral_revokes(tmp_path) -> None:
    _write(tmp_path, "d1", "down")
    _write(tmp_path, "d1", "neutral")

    assert load_feedback_map("main", home=tmp_path) == {}
    # The audit trail keeps both rows.
    lines = feedback_path("main", tmp_path).read_text().splitlines()
    assert len(lines) == 2


def test_ensemble_kind_preserved_and_stats_split(tmp_path) -> None:
    _write(tmp_path, "d1", "down", turn=0, kind="single")
    _write(tmp_path, "d2", "down", turn=1, kind="ensemble")
    _write(tmp_path, "d3", "up", turn=2, kind="ensemble")

    fb = load_feedback_map("main", home=tmp_path)
    assert fb["d2"].executed_kind == "ensemble"

    stats = scan_feedback_stats("main", home=tmp_path)
    assert stats == FeedbackStats(total=3, up=1, down=2, total_single=1, down_single=1)
    # Rate slices numerator AND denominator to single-model ratings.
    assert stats.downvote_rate == 1.0


def test_stats_since_ts_window(tmp_path) -> None:
    early = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
    _write(tmp_path, "d1", "down", now=early)
    _write(tmp_path, "d2", "down", turn=1, now=NOW)

    post = scan_feedback_stats("main", since_ts="2026-07-05T00:00:00Z", home=tmp_path)
    assert post.down == 1  # only the recent one

    # A pre-window rating revised inside the window counts (revision is the
    # operative judgment).
    _write(tmp_path, "d1", "up", now=NOW)
    post2 = scan_feedback_stats("main", since_ts="2026-07-05T00:00:00Z", home=tmp_path)
    assert post2.up == 1 and post2.down == 1


def test_retention_prunes_old_rows(tmp_path) -> None:
    old = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
    _write(tmp_path, "dOld", "down", now=old)
    # The next write (retention_days=30 vs a 69-day-old row) prunes it.
    _write(tmp_path, "dNew", "up", turn=1, now=NOW)

    fb = load_feedback_map("main", home=tmp_path)
    assert "dOld" not in fb
    assert fb["dNew"].rating == "up"


def test_corrupt_lines_are_skipped(tmp_path) -> None:
    _write(tmp_path, "d1", "down")
    path = feedback_path("main", tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{broken json\n")
        fh.write("[]\n")  # valid JSON, wrong shape

    fb = load_feedback_map("main", home=tmp_path)
    assert fb["d1"].rating == "down"


def test_invalid_rating_rejected(tmp_path) -> None:
    import pytest

    with pytest.raises(ValueError):
        _write(tmp_path, "d1", "amazing")


def test_unknown_executed_kind_coerces_to_single(tmp_path) -> None:
    _write(tmp_path, "d1", "down", kind="mystery")
    fb = load_feedback_map("main", home=tmp_path)
    assert fb["d1"].executed_kind == "single"
