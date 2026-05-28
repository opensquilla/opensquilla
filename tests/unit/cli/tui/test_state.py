from __future__ import annotations

from opensquilla.cli.tui.state import TuiRuntimeState


def test_runtime_state_tracks_pending_queue_fifo() -> None:
    state = TuiRuntimeState()

    state.enqueue("first")
    state.enqueue("second")

    assert state.pending_size == 2
    assert state.pending_items == ("first", "second")
    assert state.promote_next() == "first"
    assert state.promote_next() == "second"
    assert state.promote_next() is None


def test_runtime_state_exposes_active_turn_transitions() -> None:
    state = TuiRuntimeState()

    assert state.has_active_turn is False
    state.mark_turn_started("hello")
    assert state.has_active_turn is True
    assert state.active_input == "hello"

    state.mark_turn_finished()

    assert state.has_active_turn is False
    assert state.active_input is None


def test_runtime_state_clears_pending_queue() -> None:
    state = TuiRuntimeState()
    state.enqueue("first")
    state.enqueue("second")

    dropped = state.clear_pending()

    assert dropped == ("first", "second")
    assert state.pending_size == 0
