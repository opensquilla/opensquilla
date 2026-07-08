from __future__ import annotations

from opensquilla.engine.progress_watchdog import ProgressObservation, ProgressWatchdog


def test_progress_watchdog_observes_progress_and_resets_repeated_errors() -> None:
    watchdog = ProgressWatchdog(repeated_tool_error_threshold=2)

    first = watchdog.observe(ProgressObservation(iteration=1, tool_error_signature="tool:error"))
    progress = watchdog.observe(ProgressObservation(iteration=2, successful_tool_result=True))
    after_reset = watchdog.observe(
        ProgressObservation(iteration=3, tool_error_signature="tool:error")
    )

    assert first.action == "observe"
    assert progress.reason == "progress"
    assert after_reset.action == "observe"


def test_progress_watchdog_warns_in_observe_only_mode() -> None:
    watchdog = ProgressWatchdog(repeated_tool_error_threshold=2, observe_only=True)

    watchdog.observe(ProgressObservation(iteration=1, tool_error_signature="same"))
    decision = watchdog.observe(ProgressObservation(iteration=2, tool_error_signature="same"))

    assert decision.action == "warn"
    assert decision.reason == "repeated_tool_error"
    assert decision.details["count"] == 2
    assert decision.details["iteration"] == 2
    assert decision.details["provider_call_count"] == 0


def test_progress_watchdog_blocks_only_when_enabled() -> None:
    watchdog = ProgressWatchdog(
        repeated_provider_failure_threshold=2,
        observe_only=False,
    )

    watchdog.observe(ProgressObservation(iteration=1, provider_failure_signature="timeout"))
    decision = watchdog.observe(
        ProgressObservation(iteration=2, provider_failure_signature="timeout")
    )

    assert decision.action == "block"
    assert decision.reason == "repeated_provider_failure"


def test_progress_watchdog_warns_on_repeated_failure_anchor_despite_successful_tools() -> None:
    watchdog = ProgressWatchdog(repeated_failure_anchor_threshold=2)

    first = watchdog.observe(
        ProgressObservation(
            iteration=1,
            successful_tool_result=True,
            failure_anchor_signature="same-failure",
            failure_anchor_summary="exec_command: FAILED test_app.py::test_bug",
        )
    )
    second = watchdog.observe(
        ProgressObservation(
            iteration=2,
            provider_call_count=2,
            successful_tool_result=True,
            failure_anchor_signature="same-failure",
            failure_anchor_summary="exec_command: FAILED test_app.py::test_bug",
        )
    )

    assert first.action == "observe"
    assert second.action == "warn"
    assert second.reason == "repeated_failure_anchor_without_workspace_write"
    assert second.details["count"] == 2
    assert second.details["threshold"] == 2
    assert second.details["failure_anchor_summary"] == (
        "exec_command: FAILED test_app.py::test_bug"
    )


def test_progress_watchdog_resets_repeated_failure_anchor_after_workspace_write() -> None:
    watchdog = ProgressWatchdog(repeated_failure_anchor_threshold=2)

    watchdog.observe(
        ProgressObservation(
            iteration=1,
            failure_anchor_signature="same-failure",
            workspace_write_count=0,
        )
    )
    after_write = watchdog.observe(
        ProgressObservation(
            iteration=2,
            successful_tool_result=True,
            workspace_write_count=1,
        )
    )
    after_reset = watchdog.observe(
        ProgressObservation(
            iteration=3,
            failure_anchor_signature="same-failure",
            workspace_write_count=1,
        )
    )

    assert after_write.action == "observe"
    assert after_write.reason == "progress"
    assert after_reset.action == "observe"


def test_progress_watchdog_warns_after_source_context_without_writes() -> None:
    watchdog = ProgressWatchdog(
        source_context_without_write_threshold=2,
        observe_only=True,
    )

    first = watchdog.observe(
        ProgressObservation(
            iteration=1,
            successful_tool_result=True,
            successful_source_context_tool_result=True,
            workspace_write_count=0,
        )
    )
    second = watchdog.observe(
        ProgressObservation(
            iteration=2,
            provider_call_count=2,
            successful_tool_result=True,
            successful_source_context_tool_result=True,
            workspace_write_count=0,
        )
    )

    assert first.action == "observe"
    assert second.action == "warn"
    assert second.reason == "source_context_without_workspace_write"
    assert second.details["count"] == 2
    assert second.details["threshold"] == 2
    assert second.details["provider_call_count"] == 2


def test_noop_receipt_does_not_reset_source_context_without_write_loop() -> None:
    watchdog = ProgressWatchdog(
        source_context_without_write_threshold=2,
        observe_only=False,
    )

    first = watchdog.observe(
        ProgressObservation(
            iteration=1,
            successful_source_context_tool_result=True,
            source_context_signature="read:src/a.py",
            workspace_write_count=1,
            changed_receipt_count=0,
            noop_receipt_count=1,
        )
    )
    second = watchdog.observe(
        ProgressObservation(
            iteration=2,
            successful_source_context_tool_result=True,
            source_context_signature="read:src/a.py",
            workspace_write_count=1,
            changed_receipt_count=0,
            noop_receipt_count=1,
        )
    )

    assert first.action == "observe"
    assert second.reason == "source_context_without_workspace_write"


def test_changed_receipt_counts_as_workspace_progress() -> None:
    watchdog = ProgressWatchdog(
        source_context_without_write_threshold=1,
        observe_only=False,
    )

    decision = watchdog.observe(
        ProgressObservation(
            iteration=1,
            successful_source_context_tool_result=True,
            source_context_signature="read:src/a.py",
            workspace_write_count=0,
            changed_receipt_count=1,
        )
    )

    assert decision.reason == "progress"


def test_unchanged_changed_receipt_count_does_not_mask_repeated_tool_errors() -> None:
    watchdog = ProgressWatchdog(
        repeated_tool_error_threshold=3,
        observe_only=False,
    )

    initial_progress = watchdog.observe(
        ProgressObservation(iteration=1, changed_receipt_count=1)
    )
    first_error = watchdog.observe(
        ProgressObservation(
            iteration=2,
            changed_receipt_count=1,
            tool_error_signature="edit_file:failed",
        )
    )
    second_error = watchdog.observe(
        ProgressObservation(
            iteration=3,
            changed_receipt_count=1,
            tool_error_signature="edit_file:failed",
        )
    )
    blocked = watchdog.observe(
        ProgressObservation(
            iteration=4,
            changed_receipt_count=1,
            tool_error_signature="edit_file:failed",
        )
    )

    assert initial_progress.reason == "progress"
    assert first_error.reason == "no_signal"
    assert second_error.reason == "no_signal"
    assert blocked.action == "block"
    assert blocked.reason == "repeated_tool_error"
    assert blocked.details["count"] == 3


def test_progress_watchdog_warns_after_varied_source_context_without_writes() -> None:
    watchdog = ProgressWatchdog(
        source_context_exploration_without_write_threshold=3,
        observe_only=True,
    )

    first = watchdog.observe(
        ProgressObservation(
            iteration=1,
            provider_call_count=1,
            successful_tool_result=True,
            successful_source_context_tool_result=True,
            source_context_signature="read:src/a.py",
            workspace_write_count=0,
        )
    )
    second = watchdog.observe(
        ProgressObservation(
            iteration=2,
            provider_call_count=2,
            successful_tool_result=True,
            successful_source_context_tool_result=True,
            source_context_signature="read:src/b.py",
            workspace_write_count=0,
        )
    )
    third = watchdog.observe(
        ProgressObservation(
            iteration=3,
            provider_call_count=3,
            successful_tool_result=True,
            successful_source_context_tool_result=True,
            source_context_signature="grep:src/c.py",
            workspace_write_count=0,
        )
    )

    assert first.action == "observe"
    assert second.action == "observe"
    assert third.action == "warn"
    assert third.reason == "source_context_exploration_without_workspace_write"
    assert third.details["count"] == 3
    assert third.details["threshold"] == 3
    assert third.details["provider_call_count"] == 3
    assert third.details["source_context_signature"] == "grep:src/c.py"


def test_progress_watchdog_resets_varied_source_context_after_workspace_write() -> None:
    watchdog = ProgressWatchdog(
        source_context_exploration_without_write_threshold=2,
    )

    watchdog.observe(
        ProgressObservation(
            iteration=1,
            successful_tool_result=True,
            successful_source_context_tool_result=True,
            source_context_signature="read:src/a.py",
            workspace_write_count=0,
        )
    )
    after_write = watchdog.observe(
        ProgressObservation(
            iteration=2,
            successful_tool_result=True,
            workspace_write_count=1,
        )
    )
    after_reset = watchdog.observe(
        ProgressObservation(
            iteration=3,
            successful_tool_result=True,
            successful_source_context_tool_result=True,
            source_context_signature="read:src/b.py",
            workspace_write_count=1,
        )
    )

    assert after_write.action == "observe"
    assert after_write.reason == "progress"
    assert after_reset.action == "observe"


def test_progress_watchdog_warns_after_tool_activity_without_writes() -> None:
    watchdog = ProgressWatchdog(
        tool_activity_without_write_threshold=2,
        observe_only=True,
    )

    first = watchdog.observe(
        ProgressObservation(
            iteration=1,
            provider_call_count=1,
            successful_tool_result=True,
            successful_execution_tool_result=True,
            scratch_write_count=1,
            workspace_write_count=0,
            workspace_change_likely_required=True,
        )
    )
    second = watchdog.observe(
        ProgressObservation(
            iteration=2,
            provider_call_count=2,
            successful_tool_result=True,
            scratch_write_count=1,
            workspace_write_count=0,
            workspace_change_likely_required=True,
        )
    )

    assert first.action == "observe"
    assert second.action == "warn"
    assert second.reason == "tool_activity_without_workspace_write"
    assert second.details["count"] == 2
    assert second.details["threshold"] == 2
    assert second.details["scratch_write_count"] == 1
    assert second.details["workspace_change_likely_required"] is True


def test_progress_watchdog_resets_tool_activity_after_workspace_write() -> None:
    watchdog = ProgressWatchdog(tool_activity_without_write_threshold=2)

    watchdog.observe(
        ProgressObservation(
            iteration=1,
            successful_tool_result=True,
            successful_execution_tool_result=True,
            workspace_write_count=0,
        )
    )
    after_write = watchdog.observe(
        ProgressObservation(
            iteration=2,
            successful_tool_result=True,
            workspace_write_count=1,
        )
    )
    after_reset = watchdog.observe(
        ProgressObservation(
            iteration=3,
            successful_tool_result=True,
            successful_execution_tool_result=True,
            workspace_write_count=1,
        )
    )

    assert after_write.action == "observe"
    assert after_write.reason == "progress"
    assert after_reset.action == "observe"


def test_progress_watchdog_warns_after_verified_diff_continues_tool_activity() -> None:
    watchdog = ProgressWatchdog(verified_post_write_activity_threshold=2)

    first = watchdog.observe(
        ProgressObservation(
            iteration=1,
            provider_call_count=1,
            successful_tool_result=True,
            successful_execution_tool_result=True,
            workspace_write_count=1,
            post_write_focused_verification_observed=True,
        )
    )
    second = watchdog.observe(
        ProgressObservation(
            iteration=2,
            provider_call_count=2,
            successful_tool_result=True,
            successful_source_context_tool_result=True,
            workspace_write_count=1,
            post_write_focused_verification_observed=True,
        )
    )

    assert first.action == "observe"
    assert second.action == "warn"
    assert second.reason == "verified_workspace_diff_continued_tool_activity"
    assert second.details["count"] == 2
    assert second.details["threshold"] == 2
