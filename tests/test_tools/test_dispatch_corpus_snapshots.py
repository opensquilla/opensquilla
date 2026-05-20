"""Golden-master snapshot tests for every corpus case.

Each test runs the legacy dispatch handler against one CorpusCase and:
1. Asserts the expected_is_error / expected_error_class / expected_status_*
   behavioural contracts.
2. Snapshots the full result envelope via syrupy (stored under
   tests/test_tools/__snapshots__/). Snapshots are updated with
   `pytest --snapshot-update`.
3. Verifies artifact delta, structured log events, and contextvar reset.

These tests form the safety net that dispatch refactors must not regress.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import structlog.testing
from syrupy.assertion import SnapshotAssertion
from test_tools.dispatch_corpus import ALL_CASES, CorpusCase

from opensquilla.tool_boundary import ToolResult
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.types import current_tool_context

# ---------------------------------------------------------------------------
# Snapshot serialisation helpers
# ---------------------------------------------------------------------------

def _stable_envelope(result: ToolResult) -> dict[str, Any]:
    """Build a deterministic dict from ToolResult for snapshotting.

    Dynamic fields (tool_use_id) are normalised; content is parsed as JSON
    when possible so diffs are human-readable.

    The ``preview`` field produced by explicit strict result compaction is
    stripped.  The preview is a raw content slice whose exact byte count is
    sensitive to per-test ToolResultBudgetPolicy settings.  What matters is
    that ``result_truncated``, ``result_original_chars``, and
    ``execution_status.truncated`` are correct; those fields are retained.
    """
    content: Any
    try:
        content = json.loads(result.content) if isinstance(result.content, str) else result.content
    except (TypeError, ValueError):
        content = result.content

    # Strip the raw preview slice from compacted results — see docstring.
    if isinstance(content, dict) and content.get("result_truncated") is True:
        content = {k: v for k, v in content.items() if k != "preview"}

    status: dict[str, Any] | None = None
    if result.execution_status is not None:
        # Keep all fields — all are deterministic for these cases
        status = dict(result.execution_status)

    return {
        "is_error": result.is_error,
        "content": content,
        "execution_status": status,
        # Artifacts: count only — individual dicts have session-specific timestamps
        "artifact_count": len(result.artifacts),
    }


# ---------------------------------------------------------------------------
# Parametrised golden-master test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "case",
    ALL_CASES,
    ids=[c.name for c in ALL_CASES],
)
@pytest.mark.asyncio
async def test_dispatch_corpus_snapshot(
    case: CorpusCase,
    snapshot: SnapshotAssertion,
) -> None:
    """Each corpus case produces a deterministic envelope captured by syrupy.

    Behaviour assertions come first; snapshot comparison is the final seal.
    """
    ctx = case.ctx_factory()
    registry = case.registry_factory()

    handler = build_tool_handler(
        registry,
        ctx,
        known_skill_names=set(case.known_skill_names) if case.known_skill_names else None,
    )

    # Reset contextvar before dispatch — mimics normal agent loop entry
    token = current_tool_context.set(None)
    if case.setup is not None:
        case.setup()
    try:
        artifact_before = len(ctx.published_artifacts) if ctx is not None else 0

        with structlog.testing.capture_logs() as captured:
            result = await handler(case.tool_call)

        artifact_after = len(ctx.published_artifacts) if ctx is not None else 0
    finally:
        current_tool_context.reset(token)
        if case.teardown is not None:
            case.teardown()

    # ------------------------------------------------------------------
    # 1. Behavioural assertions
    # ------------------------------------------------------------------
    assert result.is_error is case.expected_is_error, (
        f"[{case.name}] expected is_error={case.expected_is_error}, "
        f"got {result.is_error}; content={result.content!r}"
    )

    if case.expected_error_class is not None:
        try:
            payload = json.loads(result.content)
        except (TypeError, ValueError):
            payload = {}
        assert payload.get("error_class") == case.expected_error_class, (
            f"[{case.name}] expected error_class={case.expected_error_class!r}, "
            f"got {payload.get('error_class')!r}"
        )

    if case.expected_status_status is not None:
        assert result.execution_status is not None, (
            f"[{case.name}] expected non-None execution_status"
        )
        assert result.execution_status["status"] == case.expected_status_status, (
            f"[{case.name}] expected status={case.expected_status_status!r}, "
            f"got {result.execution_status['status']!r}"
        )

    if case.expected_status_reason is not None:
        assert result.execution_status is not None, (
            f"[{case.name}] expected non-None execution_status"
        )
        assert result.execution_status["reason"] == case.expected_status_reason, (
            f"[{case.name}] expected reason={case.expected_status_reason!r}, "
            f"got {result.execution_status['reason']!r}"
        )

    # ------------------------------------------------------------------
    # 2. Artifact delta
    # ------------------------------------------------------------------
    actual_delta = artifact_after - artifact_before
    assert actual_delta == case.expected_artifact_delta, (
        f"[{case.name}] expected artifact delta={case.expected_artifact_delta}, "
        f"got {actual_delta}"
    )

    # ------------------------------------------------------------------
    # 3. Structured log events
    # ------------------------------------------------------------------
    actual_events = {
        (rec.get("event", ""), rec.get("log_level", ""))
        for rec in captured
    }
    for expected_event, expected_level in case.expected_log_events:
        assert (expected_event, expected_level) in actual_events, (
            f"[{case.name}] expected log event ({expected_event!r}, {expected_level!r}) "
            f"not found in {actual_events!r}"
        )

    # ------------------------------------------------------------------
    # 4. Contextvar leak detection
    # ------------------------------------------------------------------
    if case.contextvar_must_be_none_after:
        ctx_after = current_tool_context.get()
        assert ctx_after is None, (
            f"[{case.name}] contextvar leak: current_tool_context.get()={ctx_after!r} "
            "after dispatch — finally-reset contract violated"
        )

    # ------------------------------------------------------------------
    # 5. Syrupy snapshot — golden master seal
    # ------------------------------------------------------------------
    assert _stable_envelope(result) == snapshot
