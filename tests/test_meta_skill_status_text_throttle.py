"""500ms per-step status_text 节流 + (run, step, state) 去重。"""

from opensquilla.skills.meta.progress_throttle import ProgressThrottle


def test_throttle_allows_first_status_text():
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: 1000.0)
    assert t.allow_status_text("r1", "search") is True


def test_throttle_blocks_within_window():
    now = [1000.0]
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: now[0])
    assert t.allow_status_text("r1", "search") is True
    now[0] = 1000.4  # 400ms later
    assert t.allow_status_text("r1", "search") is False


def test_throttle_allows_after_window():
    now = [1000.0]
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: now[0])
    t.allow_status_text("r1", "search")
    now[0] = 1000.6
    assert t.allow_status_text("r1", "search") is True


def test_throttle_per_step_independent():
    now = [1000.0]
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: now[0])
    assert t.allow_status_text("r1", "search") is True
    assert t.allow_status_text("r1", "draft") is True  # different step


def test_state_dedupe_first_seen():
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: 0.0)
    assert t.allow_state("r1", "search", "running") is True


def test_state_dedupe_repeats_blocked():
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: 0.0)
    t.allow_state("r1", "search", "running")
    assert t.allow_state("r1", "search", "running") is False


def test_state_dedupe_transition_allowed():
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: 0.0)
    t.allow_state("r1", "search", "running")
    assert t.allow_state("r1", "search", "succeeded") is True
