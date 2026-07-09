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


def test_rollback_window_keys_on_decision_ts_not_rating_ts(tmp_path) -> None:
    """A post-promotion rating of a PRE-promotion decision must not count
    against the newly promoted classifier."""
    promo_ts = "2026-07-05T00:00:00Z"
    # Decision made before promotion, rated after.
    write_feedback(
        "main",
        decision_id="old-turn",
        session_key="agent:main:webchat:s1",
        turn_index=0,
        rating="down",
        decision_ts="2026-07-01T00:00:00Z",
        home=tmp_path,
        now=NOW,  # rating arrives 2026-07-09, after promotion
    )
    # Decision made after promotion, rated after.
    write_feedback(
        "main",
        decision_id="new-turn",
        session_key="agent:main:webchat:s1",
        turn_index=1,
        rating="down",
        decision_ts="2026-07-06T00:00:00Z",
        home=tmp_path,
        now=NOW,
    )

    post = scan_feedback_stats("main", since_ts=promo_ts, home=tmp_path)
    assert post.down == 1  # only the new-model decision counts


def test_retention_keys_on_rating_ts(tmp_path) -> None:
    """Rating an old-but-valid decision must survive the retention prune."""
    old_decision = "2026-05-01T00:00:00Z"  # decision older than retention
    _write(tmp_path, "d1", "down", now=NOW)  # trigger prune context
    write_feedback(
        "main",
        decision_id="d2",
        session_key="agent:main:webchat:s1",
        turn_index=1,
        rating="down",
        decision_ts=old_decision,
        home=tmp_path,
        now=NOW,  # the rating itself is fresh
    )
    fb = load_feedback_map("main", home=tmp_path)
    assert "d2" in fb  # not pruned despite the old decision


def test_concurrent_writes_with_prune_lose_nothing(tmp_path) -> None:
    """The write lock serializes append+prune; parallel ratings all survive."""
    import threading
    from datetime import timedelta

    # Seed one expired row so every write triggers a real prune rewrite.
    _write(tmp_path, "expired", "down", now=NOW - timedelta(days=40))

    def submit(i: int) -> None:
        _write(tmp_path, f"c{i}", "up", turn=i, now=NOW)

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    fb = load_feedback_map("main", home=tmp_path)
    assert "expired" not in fb
    assert all(f"c{i}" in fb for i in range(16))  # no rating lost
