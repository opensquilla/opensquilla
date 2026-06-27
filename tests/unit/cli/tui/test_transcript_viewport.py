from __future__ import annotations

from opensquilla.cli.tui.backend.transcript import (
    MessageItem,
    RouterDecisionItem,
    StatusItem,
    ToolItem,
    ToolPreviewPolicy,
    TranscriptStore,
    UsageItem,
    ViewportRequest,
    build_args_preview,
    build_output_preview,
    project_viewport,
)


def test_transcript_store_assigns_stable_ids_and_snapshots_are_immutable() -> None:
    store = TranscriptStore()

    first = store.append(MessageItem(role="user", text="hello", run_id="run-1", timestamp_ms=1))
    second = store.append(
        ToolItem(
            tool_id="call-1",
            name="search",
            status="running",
            args_preview="{}",
            output_preview="",
            expanded=False,
            timestamp_ms=2,
        )
    )
    snapshot = store.snapshot()
    store.append(StatusItem(message="working", style="dim", timestamp_ms=3))

    assert first.item_id == "message-1"
    assert second.item_id == "tool-call-1"
    assert [item.item_id for item in snapshot] == ["message-1", "tool-call-1"]
    assert len(snapshot) == 2
    assert len(store) == 3


def test_transcript_store_clear_resets_items_and_id_counters() -> None:
    store = TranscriptStore()
    store.append(MessageItem(role="user", text="hello", run_id=None, timestamp_ms=1))

    store.clear()
    item = store.append(MessageItem(role="assistant", text="hi", run_id=None, timestamp_ms=2))

    assert len(store) == 1
    assert item.item_id == "message-1"


def test_tool_args_preview_caps_long_json_without_reordering_keys() -> None:
    policy = ToolPreviewPolicy(max_arg_chars=28)

    preview = build_args_preview({"first": "a" * 20, "second": "b"}, policy)

    assert preview.truncated is True
    assert preview.text.startswith('{"first"')
    assert "..." in preview.text
    assert len(preview.text) <= policy.max_arg_chars + len("...")


def test_tool_output_preview_caps_lines_and_chars() -> None:
    policy = ToolPreviewPolicy(max_output_lines=3, max_output_chars=200)
    output = "\n".join(f"line {index}" for index in range(10))

    preview = build_output_preview(output, policy)

    assert preview.truncated is True
    assert "line 0" in preview.text
    assert "line 2" in preview.text
    assert "line 3" not in preview.text
    assert "... truncated" in preview.text


def test_tool_output_preview_handles_image_placeholders_and_errors() -> None:
    policy = ToolPreviewPolicy()

    image_preview = build_output_preview(
        {"type": "image", "mime": "image/png", "width": 20, "height": 10},
        policy,
    )
    error_preview = build_output_preview("boom", policy, is_error=True)

    assert image_preview.text == "[image image/png 20x10]"
    assert image_preview.truncated is False
    assert error_preview.text == "error: boom"


def test_viewport_projection_is_bounded_for_dense_history() -> None:
    store = TranscriptStore()
    for index in range(250):
        store.append(
            MessageItem(
                role="user",
                text=f"user {index}",
                run_id="run-dense",
                timestamp_ms=index * 2,
            )
        )
        store.append(
            MessageItem(
                role="assistant",
                text=f"assistant {index}",
                run_id="run-dense",
                timestamp_ms=index * 2 + 1,
            )
        )
    for index in range(120):
        store.append(
            ToolItem(
                tool_id=f"tool-{index}",
                name="search",
                status="done",
                args_preview="{}",
                output_preview="ok",
                expanded=index < 20,
                timestamp_ms=1_000 + index,
                detail_line_count=8,
            )
        )

    projection = project_viewport(
        store.snapshot(),
        ViewportRequest(scroll_offset=200, viewport_height=24, overscan=3),
    )

    assert projection.total_items == 620
    assert projection.total_rows > 620
    assert len(projection.items) <= 30
    assert projection.items == project_viewport(
        store.snapshot(),
        ViewportRequest(scroll_offset=200, viewport_height=24, overscan=3),
    ).items


def test_transcript_accepts_router_status_and_usage_items() -> None:
    store = TranscriptStore()

    store.append(
        RouterDecisionItem(
            tier="standard",
            model="openrouter/model",
            baseline_model="openrouter/baseline",
            confidence=0.71,
            rollout_phase="full",
            timestamp_ms=1,
        )
    )
    store.append(StatusItem(message="working", style="dim", timestamp_ms=2))
    store.append(UsageItem(input_tokens=10, output_tokens=20, cost_usd=0.01, timestamp_ms=3))

    assert [item.item_id for item in store.snapshot()] == [
        "router-1",
        "status-1",
        "usage-1",
    ]
