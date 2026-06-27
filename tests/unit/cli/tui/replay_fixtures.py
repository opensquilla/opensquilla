from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReplayEvent:
    kind: str
    payload: dict[str, object]
    timestamp_ms: int


def _router_decision_payload(index: int, *, tier: str) -> dict[str, object]:
    model = f"openrouter/{tier}-model-{index}"
    return {
        "tier": tier,
        "model": model,
        "baseline_model": "openrouter/frontier-baseline",
        "source": "synthetic-replay",
        "confidence": round(0.92 - index * 0.07, 2),
        "savings_pct": 18 + index * 9,
        "fallback": index == 3,
        "thinking_mode": "observe" if index % 2 == 0 else "full",
        "prompt_policy": "standard",
        "routing_applied": index != 3,
        "rollout_phase": f"phase-{index}",
    }


def build_long_stream_events() -> list[ReplayEvent]:
    events: list[ReplayEvent] = [
        ReplayEvent(
            "user_input",
            {"text": "Explain the OpenSquilla routing decision stream."},
            0,
        ),
        ReplayEvent("router_decision", _router_decision_payload(0, tier="standard"), 1),
    ]

    timestamp_ms = 2
    tool_index = 0
    for index in range(4_000):
        section = index // 800
        delta = f"stream-section-{section:02d}-delta-{index:04d}-"[:40]
        events.append(ReplayEvent("text_delta", {"text": delta.ljust(40, ".")}, timestamp_ms))
        timestamp_ms += 1

        if (index + 1) % 800 == 0 and tool_index < 4:
            tool_id = f"tool-{tool_index}"
            events.append(
                ReplayEvent(
                    "tool_start",
                    {
                        "name": "synthetic_tool",
                        "args": {"section": section},
                        "tool_use_id": tool_id,
                    },
                    timestamp_ms,
                )
            )
            timestamp_ms += 1
            events.append(
                ReplayEvent(
                    "tool_finished",
                    {
                        "tool_use_id": tool_id,
                        "success": True,
                        "elapsed": 0.01 + tool_index * 0.001,
                    },
                    timestamp_ms,
                )
            )
            timestamp_ms += 1
            tool_index += 1

    events.append(
        ReplayEvent(
            "done",
            {
                "usage": {
                    "input_tokens": 1_024,
                    "output_tokens": 42_000,
                    "cache_read_tokens": 512,
                }
            },
            timestamp_ms,
        )
    )
    return events


def build_dense_history_events() -> list[ReplayEvent]:
    events: list[ReplayEvent] = []
    timestamp_ms = 0
    for index, tier in enumerate(("spark", "standard", "frontier", "fallback")):
        events.append(
            ReplayEvent(
                "router_decision",
                _router_decision_payload(index, tier=tier),
                timestamp_ms,
            )
        )
        timestamp_ms += 1

    user_text = "user historical prompt line ".ljust(96, "u")
    assistant_text = "assistant historical answer line ".ljust(160, "a")
    for index in range(250):
        events.append(
            ReplayEvent(
                "history_message",
                {
                    "role": "user",
                    "content": f"{index:03d}: {user_text}",
                },
                timestamp_ms,
            )
        )
        timestamp_ms += 1
        events.append(
            ReplayEvent(
                "history_message",
                {
                    "role": "assistant",
                    "content": f"{index:03d}: {assistant_text}",
                },
                timestamp_ms,
            )
        )
        timestamp_ms += 1

    for index in range(120):
        events.append(
            ReplayEvent(
                "tool_card",
                {
                    "tool_use_id": f"dense-tool-{index}",
                    "name": "synthetic_tool",
                    "summary": f"summary for dense tool card {index}",
                    "expanded_candidate": index < 20,
                    "line_count": 12 + index,
                    "rendered_bytes": 1_024 + index * 8,
                },
                timestamp_ms,
            )
        )
        timestamp_ms += 1

    return events
