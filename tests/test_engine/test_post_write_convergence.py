from __future__ import annotations

from opensquilla.engine.post_write_convergence import (
    PostWriteConvergenceObservation,
    PostWriteConvergenceTracker,
)


def _observation(
    *,
    iteration: int,
    provider_call_count: int,
    workspace_write_count: int = 1,
    changed_receipt_count: int = 1,
    diff_fingerprint: str = "abc",
    diff_paths: list[str] | None = None,
    focused_verification_success_observed: bool = True,
    continued_activity_after_verification: bool = True,
) -> PostWriteConvergenceObservation:
    return PostWriteConvergenceObservation(
        iteration=iteration,
        provider_call_count=provider_call_count,
        workspace_write_count=workspace_write_count,
        changed_receipt_count=changed_receipt_count,
        diff_fingerprint=diff_fingerprint,
        diff_paths=["src.py"] if diff_paths is None else diff_paths,
        focused_verification_success_observed=focused_verification_success_observed,
        continued_activity_after_verification=continued_activity_after_verification,
    )


def test_post_write_convergence_warns_then_finalizes_stable_verified_diff() -> None:
    tracker = PostWriteConvergenceTracker(
        warn_threshold=3,
        finalize_after_warning=3,
    )

    first = tracker.observe(
        _observation(
            iteration=1,
            provider_call_count=1,
        )
    )
    second = tracker.observe(
        _observation(
            iteration=2,
            provider_call_count=2,
        )
    )
    warned = tracker.observe(
        _observation(
            iteration=3,
            provider_call_count=3,
        )
    )
    tracker.observe(
        _observation(
            iteration=4,
            provider_call_count=4,
        )
    )
    tracker.observe(
        _observation(
            iteration=5,
            provider_call_count=5,
        )
    )
    finalized = tracker.observe(
        _observation(
            iteration=6,
            provider_call_count=6,
        )
    )

    assert first.action == "observe"
    assert second.action == "observe"
    assert warned.action == "warn"
    assert warned.reason == "stable_verified_workspace_diff_continued_activity"
    assert warned.details["stable_count"] == 3
    assert warned.details["diff_fingerprint"] == "abc"
    assert finalized.action == "finalize"
    assert finalized.reason == "stable_verified_workspace_diff_finalization"
    assert finalized.details["stable_count"] == 6
    assert finalized.details["warned_at_count"] == 3


def test_post_write_convergence_resets_when_diff_changes() -> None:
    tracker = PostWriteConvergenceTracker(warn_threshold=3)

    tracker.observe(
        _observation(
            iteration=1,
            provider_call_count=1,
            diff_fingerprint="before",
        )
    )
    reset = tracker.observe(
        _observation(
            iteration=2,
            provider_call_count=2,
            workspace_write_count=2,
            diff_fingerprint="after",
            diff_paths=["src.py", "lib.py"],
        )
    )
    next_observation = tracker.observe(
        _observation(
            iteration=3,
            provider_call_count=3,
            workspace_write_count=2,
            diff_fingerprint="after",
            diff_paths=["src.py", "lib.py"],
        )
    )

    assert reset.action == "reset"
    assert reset.reason == "diff_fingerprint_changed"
    assert reset.details["previous_diff_fingerprint"] == "before"
    assert reset.details["diff_fingerprint"] == "after"
    assert next_observation.action == "observe"
    assert next_observation.details["stable_count"] == 2


def test_post_write_convergence_does_not_finalize_without_clean_verification() -> None:
    tracker = PostWriteConvergenceTracker(
        warn_threshold=2,
        finalize_after_warning=2,
    )

    decisions = [
        tracker.observe(
            _observation(
                iteration=index,
                provider_call_count=index,
                focused_verification_success_observed=False,
            )
        )
        for index in range(1, 6)
    ]

    assert {decision.action for decision in decisions} == {"observe"}


def test_post_write_convergence_ignores_noop_receipt_write_count_only() -> None:
    tracker = PostWriteConvergenceTracker(
        warn_threshold=1,
        finalize_after_warning=1,
    )

    decision = tracker.observe(
        _observation(
            iteration=1,
            provider_call_count=1,
            workspace_write_count=1,
            changed_receipt_count=0,
        )
    )

    assert decision.action == "observe"
    assert decision.reason == "not_eligible"
    assert decision.details["stable_count"] == 0


def test_post_write_convergence_can_trigger_with_changed_receipt() -> None:
    tracker = PostWriteConvergenceTracker(
        warn_threshold=1,
        finalize_after_warning=1,
    )

    decision = tracker.observe(
        _observation(
            iteration=1,
            provider_call_count=1,
            workspace_write_count=0,
            changed_receipt_count=1,
        )
    )

    assert decision.action == "warn"
    assert decision.reason == "stable_verified_workspace_diff_continued_activity"
    assert decision.details["stable_count"] == 1
