"""Unit tests for ``StreamConsumerStage`` driven directly (no full
TurnRunner stack).

Drives the stage through ``StreamConsumerStage.run`` with recording
fakes for all five ports + the warning transformer, plus per-handler
unit tests for the eight internal handler classes.

Raising-fake cases exercise the exception-propagation contracts without the
runtime wrapper.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine.turn_runner.stream_consumer_stage import (
    _SUPPRESS,
    StreamConsumerStage,
    StreamConsumerStageInput,
    _ArtifactHandler,
    _CompactionHandler,
    _DoneHandler,
    _ErrorHandler,
    _StreamState,
    _TextDeltaHandler,
    _ToolUseStartHandler,
    _WarningHandler,
)
from opensquilla.engine.types import (
    ArtifactEvent,
    CompactionEvent,
    DoneEvent,
    ErrorEvent,
    TextDeltaEvent,
    ToolUseStartEvent,
    WarningEvent,
)

# ---------------------------------------------------------------------------
# Recording fakes
# ---------------------------------------------------------------------------


@dataclass
class _RecordingAgentRun:
    events: list[Any] = field(default_factory=list)
    raises: type[BaseException] | None = None
    received: list[dict[str, Any]] = field(default_factory=list)

    def run_turn(
        self,
        agent: Any,
        *,
        turn_input: str,
        extra_messages: list[Any] | None,
        semantic_message: str | None,
    ) -> AsyncIterator[Any]:
        self.received.append(
            {
                "agent": agent,
                "turn_input": turn_input,
                "extra_messages": extra_messages,
                "semantic_message": semantic_message,
            }
        )
        events = list(self.events)
        raises = self.raises

        async def _iter():
            for ev in events:
                yield ev
            if raises is not None:
                raise raises("recording agent boom")

        return _iter()


@dataclass
class _RecordingCompactionPersist:
    calls: list[dict[str, Any]] = field(default_factory=list)
    raises: type[BaseException] | None = None

    async def persist_and_notify(
        self,
        *,
        session_key: str,
        summary: str,
        kept_entries: list[Any],
    ) -> None:
        self.calls.append(
            {
                "session_key": session_key,
                "summary": summary,
                "kept_entries": kept_entries,
            }
        )
        if self.raises is not None:
            raise self.raises("recording persist boom")


@dataclass
class _RecordingMemorySnapshotRefresh:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def refresh_snapshot(
        self,
        *,
        agent_id: str,
        session_key: str,
        private_memory_allowed: bool,
    ) -> None:
        self.calls.append(
            {
                "agent_id": agent_id,
                "session_key": session_key,
                "private_memory_allowed": private_memory_allowed,
            }
        )


@dataclass
class _RecordingSystemPromptRefresh:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def refresh_system_prompt(
        self,
        *,
        agent: Any,
        agent_id: str,
        tool_defs: list[Any],
        session_key: str,
        bootstrap_context_mode: str | None,
    ) -> None:
        self.calls.append(
            {
                "agent": agent,
                "agent_id": agent_id,
                "tool_defs": tool_defs,
                "session_key": session_key,
                "bootstrap_context_mode": bootstrap_context_mode,
            }
        )


@dataclass
class _RecordingMemorySyncNotify:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def notify_message_bytes(
        self,
        sync_manager: Any | None,
        runtime_message: str,
    ) -> None:
        self.calls.append(
            {
                "sync_manager_present": sync_manager is not None,
                "runtime_message": runtime_message,
            }
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_turn(metadata: dict[str, Any] | None = None, tool_defs: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        metadata=metadata if metadata is not None else {},
        tool_defs=tool_defs if tool_defs is not None else [],
    )


def _make_state() -> _StreamState:
    return _StreamState(
        current_text_parts=[],
        final_text_parts=[],
        turn_segments=[],
        turn_artifacts=[],
        artifact_delivery_failures=[],
    )


def _make_input(
    *,
    state: _StreamState | None = None,
    turn: Any | None = None,
    session_manager_present: bool = True,
    private_memory_allowed: bool = True,
    sync_manager: Any | None = None,
    input_provenance: dict[str, Any] | None = None,
) -> StreamConsumerStageInput:
    return StreamConsumerStageInput(
        agent=SimpleNamespace(),
        agent_id="agent:main",
        sync_manager=sync_manager,
        private_memory_allowed=private_memory_allowed,
        turn=turn if turn is not None else _make_turn(),
        tool_defs=[],
        turn_input="hi",
        extra_messages=None,
        semantic_input="hi",
        effective_runtime_message="hello there",
        input_provenance=input_provenance,
        session_key="agent:main:s1",
        run_kind="default",
        heartbeat_ack_max_chars=300,
        bootstrap_context_mode=None,
        router_cfg=None,
        session_manager_present=session_manager_present,
        state=state if state is not None else _make_state(),
    )


def _make_stage(
    *,
    agent_run: _RecordingAgentRun | None = None,
    compaction_persist: _RecordingCompactionPersist | None = None,
    memory_snapshot_refresh: _RecordingMemorySnapshotRefresh | None = None,
    system_prompt_refresh: _RecordingSystemPromptRefresh | None = None,
    memory_sync_notify: _RecordingMemorySyncNotify | None = None,
    warning_transformer=None,
) -> tuple[StreamConsumerStage, dict[str, Any]]:
    agent_run = agent_run or _RecordingAgentRun()
    compaction_persist = compaction_persist or _RecordingCompactionPersist()
    memory_snapshot_refresh = (
        memory_snapshot_refresh or _RecordingMemorySnapshotRefresh()
    )
    system_prompt_refresh = (
        system_prompt_refresh or _RecordingSystemPromptRefresh()
    )
    memory_sync_notify = memory_sync_notify or _RecordingMemorySyncNotify()
    if warning_transformer is None:
        warning_transformer = lambda event: event  # noqa: E731

    stage = StreamConsumerStage(
        agent_run=agent_run,
        compaction_persist=compaction_persist,
        memory_snapshot_refresh=memory_snapshot_refresh,
        system_prompt_refresh=system_prompt_refresh,
        memory_sync_notify=memory_sync_notify,
        warning_transformer=warning_transformer,
    )
    recordings = {
        "agent_run": agent_run,
        "compaction_persist": compaction_persist,
        "memory_snapshot_refresh": memory_snapshot_refresh,
        "system_prompt_refresh": system_prompt_refresh,
        "memory_sync_notify": memory_sync_notify,
    }
    return stage, recordings


async def _drain(stage: StreamConsumerStage, inp: StreamConsumerStageInput) -> list[Any]:
    yielded: list[Any] = []
    async for event in stage.run(inp):
        yielded.append(event)
    return yielded


# ---------------------------------------------------------------------------
# Per-handler tests
# ---------------------------------------------------------------------------


def test_text_delta_handler_appends_to_both_buffers() -> None:
    state = _make_state()
    handler = _TextDeltaHandler()
    out = handler.handle(TextDeltaEvent(text="hi"), state)
    assert out.text == "hi"
    assert state.final_text_parts == ["hi"]
    assert state.current_text_parts == ["hi"]


def test_tool_use_start_handler_flushes_text_and_appends_segment() -> None:
    state = _make_state()
    state.current_text_parts = ["pre"]
    state.final_text_parts = ["pre"]
    handler = _ToolUseStartHandler()
    handler.handle(
        ToolUseStartEvent(
            tool_use_id="t1",
            tool_name="echo",
            synthetic_from_text=False,
        ),
        state,
    )
    assert state.turn_segments == [
        {"type": "text", "text": "pre"},
        {"type": "tool_use", "tool_use_id": "t1", "name": "echo", "input": ""},
    ]
    assert state.current_text_parts == []
    assert state.final_text_parts == ["pre"]  # unchanged when not synthetic


def test_artifact_handler_appends_payload() -> None:
    state = _make_state()
    handler = _ArtifactHandler()
    event = ArtifactEvent(
        id="art-a1",
        sha256="deadbeef",
        name="x.png",
        mime="image/png",
        size=10,
        session_id="s1",
        session_key="agent:main:s1",
        source="tool",
        created_at="2026-05-15T00:00:00Z",
        download_url="https://x/y",
    )
    handler.handle(event, state)
    assert len(state.turn_artifacts) == 1


def test_error_handler_rewrites_timeout_envelope() -> None:
    state = _make_state()
    handler = _ErrorHandler()
    result = handler.handle(ErrorEvent(message="x", code="timeout"), state)
    assert result is _SUPPRESS
    assert state.pending_error_event is not None
    assert state.pending_error_event.code == "llm_timeout"


def test_error_handler_drops_unpaired_tool_use_on_incomplete_stream() -> None:
    state = _make_state()
    state.turn_segments[:] = [
        {"type": "tool_use", "tool_use_id": "t1", "name": "x", "input": ""},
    ]
    handler = _ErrorHandler()
    result = handler.handle(
        ErrorEvent(message="boom", code="incomplete_tool_stream"),
        state,
    )
    assert result is _SUPPRESS
    assert state.turn_segments == []  # unpaired tool_use dropped


def test_warning_handler_forwards_through_transformer() -> None:
    captured: list[WarningEvent] = []

    def transformer(event: WarningEvent) -> WarningEvent:
        captured.append(event)
        return WarningEvent(code="rewritten", message="from-transformer")

    handler = _WarningHandler(transformer)
    out = handler.handle(WarningEvent(code="orig", message="m"))
    assert captured == [WarningEvent(code="orig", message="m")]
    assert out.code == "rewritten"


def test_done_handler_normalizes_and_emits_done() -> None:
    state = _make_state()
    handler = _DoneHandler()
    inp = _make_input(state=state, turn=_make_turn(metadata={"routed_tier": "L1"}))
    done = DoneEvent(text="result", input_tokens=10, output_tokens=5)
    transformed, extra = handler.handle(done, inp, state)
    assert isinstance(transformed, DoneEvent)
    assert transformed.routed_tier == "L1"
    assert state.done_event is transformed
    assert extra == []


@pytest.mark.asyncio
async def test_compaction_handler_runs_persist_snapshot_prompt_in_order() -> None:
    persist = _RecordingCompactionPersist()
    snapshot = _RecordingMemorySnapshotRefresh()
    prompt = _RecordingSystemPromptRefresh()
    handler = _CompactionHandler(
        persist=persist,
        memory_snapshot=snapshot,
        system_prompt=prompt,
    )
    inp = _make_input()
    await handler.handle(
        CompactionEvent(summary="s", kept_entries=[1, 2]),
        inp,
    )
    assert len(persist.calls) == 1
    assert persist.calls[0]["summary"] == "s"
    assert persist.calls[0]["kept_entries"] == [1, 2]
    assert len(snapshot.calls) == 1
    assert len(prompt.calls) == 1


@pytest.mark.asyncio
async def test_compaction_handler_skips_persist_when_session_manager_absent() -> None:
    persist = _RecordingCompactionPersist()
    snapshot = _RecordingMemorySnapshotRefresh()
    prompt = _RecordingSystemPromptRefresh()
    handler = _CompactionHandler(
        persist=persist,
        memory_snapshot=snapshot,
        system_prompt=prompt,
    )
    inp = _make_input(session_manager_present=False)
    await handler.handle(CompactionEvent(summary="s", kept_entries=[]), inp)
    assert persist.calls == []
    # Snapshot + prompt still fire; the persist guard is the only conditional.
    assert len(snapshot.calls) == 1
    assert len(prompt.calls) == 1


@pytest.mark.asyncio
async def test_compaction_handler_log_and_continue_on_persist_failure() -> None:
    persist = _RecordingCompactionPersist(raises=RuntimeError)
    snapshot = _RecordingMemorySnapshotRefresh()
    prompt = _RecordingSystemPromptRefresh()
    handler = _CompactionHandler(
        persist=persist,
        memory_snapshot=snapshot,
        system_prompt=prompt,
    )
    inp = _make_input()
    # Must NOT raise -- log-and-continue per legacy.
    await handler.handle(CompactionEvent(summary="s", kept_entries=[]), inp)
    assert len(persist.calls) == 1
    # Snapshot + prompt still fire after persist failure.
    assert len(snapshot.calls) == 1
    assert len(prompt.calls) == 1


# ---------------------------------------------------------------------------
# Outer-stage tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outer_stage_yields_text_then_done_and_notifies_post_stream() -> None:
    agent_run = _RecordingAgentRun(
        events=[
            TextDeltaEvent(text="hi"),
            TextDeltaEvent(text=" world"),
            DoneEvent(text="hi world"),
        ]
    )
    stage, recs = _make_stage(agent_run=agent_run)
    inp = _make_input(sync_manager=object())
    yielded = await _drain(stage, inp)
    kinds = [type(e).__name__ for e in yielded]
    assert kinds == ["TextDeltaEvent", "TextDeltaEvent", "DoneEvent"]
    assert inp.state.final_text_parts == ["hi", " world"]
    assert len(recs["memory_sync_notify"].calls) == 1
    assert recs["memory_sync_notify"].calls[0]["runtime_message"] == "hello there"
    assert recs["memory_sync_notify"].calls[0]["sync_manager_present"] is True


@pytest.mark.asyncio
async def test_outer_stage_injects_partial_failure_disclosure_before_done() -> None:
    agent_run = _RecordingAgentRun(
        events=[
            TextDeltaEvent(text="Parent synthesis."),
            DoneEvent(text="Parent synthesis."),
        ]
    )
    stage, _ = _make_stage(agent_run=agent_run)
    inp = _make_input(
        input_provenance={
            "kind": "internal_system",
            "runtime_partial_failure_disclosure_required": True,
            "subagent_group_outcome": {
                "total": 2,
                "succeeded": 1,
                "failed": 1,
                "timeout": 0,
                "cancelled": 0,
                "abandoned": 0,
                "non_success": 1,
                "failed_children": [
                    {
                        "child_session_key": "agent:worker:subagent:failed",
                        "task_id": "task-failed",
                        "agent_id": "worker-b",
                        "status": "failed",
                        "terminal_reason": "tool_error",
                        "error_class": "RuntimeError",
                        "error_message": "boom",
                    }
                ],
            },
        }
    )

    yielded = await _drain(stage, inp)

    kinds = [type(e).__name__ for e in yielded]
    assert kinds == ["TextDeltaEvent", "TextDeltaEvent", "DoneEvent"]
    disclosure = yielded[1]
    assert isinstance(disclosure, TextDeltaEvent)
    assert "Subagents: 1/2 succeeded" in disclosure.text
    assert "agent:worker:subagent:failed" in disclosure.text
    assert "RuntimeError: boom" in disclosure.text
    done = yielded[2]
    assert isinstance(done, DoneEvent)
    assert done.text == "".join(inp.state.final_text_parts)
    assert "Subagents: 1/2 succeeded" in done.text


@pytest.mark.asyncio
async def test_outer_stage_disclosure_summarizes_current_turn_exhaustion() -> None:
    agent_run = _RecordingAgentRun(events=[DoneEvent(text="Parent synthesis.")])
    stage, _ = _make_stage(agent_run=agent_run)
    inp = _make_input(
        input_provenance={
            "kind": "internal_system",
            "runtime_partial_failure_disclosure_required": True,
            "subagent_group_outcome": {
                "total": 2,
                "succeeded": 1,
                "failed": 1,
                "non_success": 1,
                "failed_children": [
                    {
                        "child_session_key": "agent:main:subagent:failed",
                        "status": "failed",
                        "terminal_reason": "error",
                        "error_class": "current_turn_context_exhausted",
                        "error_message": (
                            "Context overflow is in the current turn's recent tool calls "
                            "or reasoning tail; history compaction cannot reduce it."
                        ),
                    }
                ],
            },
        }
    )

    yielded = await _drain(stage, inp)

    disclosure = yielded[0]
    assert isinstance(disclosure, TextDeltaEvent)
    assert "Subagents: 1/2 succeeded" in disclosure.text
    assert "current_turn_context_exhausted" in disclosure.text
    assert "history compaction cannot reduce it" not in disclosure.text


@pytest.mark.asyncio
async def test_outer_stage_injects_disclosure_for_all_failed_group() -> None:
    agent_run = _RecordingAgentRun(events=[DoneEvent(text="No usable result.")])
    stage, _ = _make_stage(agent_run=agent_run)
    inp = _make_input(
        input_provenance={
            "kind": "internal_system",
            "runtime_partial_failure_disclosure_required": True,
            "subagent_group_outcome": {
                "total": 2,
                "succeeded": 0,
                "failed": 2,
                "timeout": 0,
                "cancelled": 0,
                "abandoned": 0,
                "non_success": 2,
                "failed_children": [
                    {
                        "child_session_key": "agent:worker:subagent:a",
                        "status": "failed",
                        "terminal_reason": "error",
                    },
                    {
                        "child_session_key": "agent:worker:subagent:b",
                        "status": "failed",
                        "terminal_reason": "error",
                    },
                ],
            },
        }
    )

    yielded = await _drain(stage, inp)

    kinds = [type(e).__name__ for e in yielded]
    assert kinds == ["TextDeltaEvent", "DoneEvent"]
    disclosure = yielded[0]
    assert isinstance(disclosure, TextDeltaEvent)
    assert "Subagents: 0/2 succeeded" in disclosure.text
    done = yielded[1]
    assert isinstance(done, DoneEvent)
    assert done.text == "".join(inp.state.final_text_parts)
    assert "Subagents: 0/2 succeeded" in done.text


@pytest.mark.asyncio
async def test_outer_stage_fails_when_disclosure_required_without_outcome() -> None:
    agent_run = _RecordingAgentRun(events=[DoneEvent(text="Parent synthesis.")])
    stage, _ = _make_stage(agent_run=agent_run)
    inp = _make_input(
        input_provenance={
            "kind": "internal_system",
            "runtime_partial_failure_disclosure_required": True,
        }
    )

    with pytest.raises(RuntimeError, match="outcome metadata is missing"):
        await _drain(stage, inp)


@pytest.mark.asyncio
async def test_outer_stage_suppresses_compaction_event_and_refreshes_runtime_state() -> None:
    agent_run = _RecordingAgentRun(
        events=[
            TextDeltaEvent(text="hi"),
            CompactionEvent(summary="sum", kept_entries=[1, 2, 3]),
            TextDeltaEvent(text=" after"),
            DoneEvent(text="hi after"),
        ]
    )
    stage, recs = _make_stage(agent_run=agent_run)
    inp = _make_input()
    yielded = await _drain(stage, inp)
    kinds = [type(e).__name__ for e in yielded]
    # CompactionEvent must NOT be yielded.
    assert "CompactionEvent" not in kinds
    assert kinds == ["TextDeltaEvent", "TextDeltaEvent", "DoneEvent"]
    # In-turn compaction refreshes fired in order.
    assert len(recs["compaction_persist"].calls) == 1
    assert recs["compaction_persist"].calls[0]["kept_entries"] == [1, 2, 3]
    assert len(recs["memory_snapshot_refresh"].calls) == 1
    assert len(recs["system_prompt_refresh"].calls) == 1


@pytest.mark.asyncio
async def test_outer_stage_suppresses_error_event_and_records_pending() -> None:
    agent_run = _RecordingAgentRun(
        events=[
            TextDeltaEvent(text="partial"),
            ErrorEvent(message="boom", code="agent_error"),
        ]
    )
    stage, _ = _make_stage(agent_run=agent_run)
    inp = _make_input()
    yielded = await _drain(stage, inp)
    # ErrorEvent is NOT yielded; the stream continues without yielding it.
    kinds = [type(e).__name__ for e in yielded]
    assert kinds == ["TextDeltaEvent"]
    assert inp.state.pending_error_event is not None
    assert inp.state.pending_error_event.code == "agent_error"
    assert inp.state.error_message == "boom"


@pytest.mark.asyncio
async def test_outer_stage_propagates_agent_run_exception() -> None:
    agent_run = _RecordingAgentRun(
        events=[TextDeltaEvent(text="partial")],
        raises=RuntimeError,
    )
    stage, _ = _make_stage(agent_run=agent_run)
    inp = _make_input()
    with pytest.raises(RuntimeError):
        await _drain(stage, inp)
    assert inp.state.final_text_parts == ["partial"]


@pytest.mark.asyncio
async def test_outer_stage_empty_stream_still_notifies() -> None:
    agent_run = _RecordingAgentRun(events=[])
    stage, recs = _make_stage(agent_run=agent_run)
    inp = _make_input(sync_manager=object())
    yielded = await _drain(stage, inp)
    assert yielded == []
    assert len(recs["memory_sync_notify"].calls) == 1


def test_stage_name() -> None:
    assert StreamConsumerStage.name == "stream_consumer_stage"
