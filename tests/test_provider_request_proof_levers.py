"""Opt-in compaction safety levers: tiny-argument guard + recent-assistant protection.

Covers the OPENSQUILLA_PROVIDER_COMPACTION_TINY_GUARD_CHARS and
OPENSQUILLA_PROVIDER_COMPACTION_PROTECT_RECENT_ASSISTANT env levers
(both off by default). Motivation: aggressive aggregate-mode compaction can
replace tiny tool arguments with much larger placeholder markers, and
emergency/hard tiers can destroy the model's just-emitted patch text in the
same request cycle.
"""

from __future__ import annotations

import json

import pytest

from opensquilla.provider.request_proof import (
    _compact_argument_string,
    _compact_recent_tail_payload_once,
    _emergency_compact_current_turn_payload_once,
    _final_hard_cap_payload_once,
    _hard_compact_string,
    prove_or_compact_provider_payload,
)

TINY_GUARD_ENV = "OPENSQUILLA_PROVIDER_COMPACTION_TINY_GUARD_CHARS"
PROTECT_RECENT_ENV = "OPENSQUILLA_PROVIDER_COMPACTION_PROTECT_RECENT_ASSISTANT"


def _aggregate_args_payload() -> dict[str, object]:
    """Payload whose assistant tail triggers tier-2 aggregate argument mode."""
    big = "x" * 2000
    tool_calls = [
        {
            "id": f"call-{index}",
            "type": "function",
            "function": {
                "name": "exec_command",
                "arguments": json.dumps({"command": big, "workdir": "/w", "session": "s1"}),
            },
        }
        for index in range(3)
    ]
    return {
        "messages": [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "", "tool_calls": tool_calls},
        ]
    }


def test_tiny_guard_defaults_off_replaces_tiny_arguments() -> None:
    compacted = _compact_argument_string("s1", preview=False)
    assert compacted.startswith("[provider_request_tool_input_compacted:")
    assert len(compacted) > len("s1")


def test_tiny_guard_keeps_strings_shorter_than_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TINY_GUARD_ENV, "120")
    assert _compact_argument_string("s1", preview=False) == "s1"
    assert _compact_argument_string("y" * 120, preview=False) == "y" * 120
    long_value = "z" * 121
    assert _compact_argument_string(long_value, preview=False) != long_value


def test_tiny_guard_applies_to_hard_compact(monkeypatch: pytest.MonkeyPatch) -> None:
    value = "h" * 110
    assert _hard_compact_string(value, label="t").startswith("[opensquilla_compacted:")
    monkeypatch.setenv(TINY_GUARD_ENV, "120")
    assert _hard_compact_string(value, label="t") == value


def test_tiny_guard_invalid_env_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TINY_GUARD_ENV, "not-a-number")
    compacted = _compact_argument_string("s1", preview=False)
    assert compacted.startswith("[provider_request_tool_input_compacted:")


def test_aggregate_mode_preserves_tiny_arguments_with_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TINY_GUARD_ENV, "120")
    compacted, metadata = _compact_recent_tail_payload_once(_aggregate_args_payload())
    assert metadata["aggregate_tool_arguments_compacted"] is True
    for message in compacted["messages"]:
        for tool_call in message.get("tool_calls") or []:
            arguments = json.loads(tool_call["function"]["arguments"])
            # Tiny fields survive verbatim; only the oversized command is compacted.
            assert arguments["workdir"] == "/w"
            assert arguments["session"] == "s1"
            assert arguments["command"].startswith(
                "[provider_request_tool_input_compacted:"
            )


def test_protect_recent_assistant_off_by_default() -> None:
    payload = _aggregate_args_payload()
    compacted, _ = _compact_recent_tail_payload_once(payload)
    last = compacted["messages"][-1]
    arguments = json.loads(last["tool_calls"][0]["function"]["arguments"])
    assert arguments["command"].startswith("[provider_request_tool_input_compacted:")


def test_protect_recent_assistant_exempts_last_turn_tier2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROTECT_RECENT_ENV, "1")
    payload = _aggregate_args_payload()
    # Add an older assistant turn that must still be compacted.
    payload["messages"].insert(1, deep_assistant_turn())
    compacted, _ = _compact_recent_tail_payload_once(payload)
    older = compacted["messages"][1]
    older_args = older["tool_calls"][0]["function"]["arguments"]
    assert "[provider_request_" in older_args
    last = compacted["messages"][-1]
    last_args = last["tool_calls"][0]["function"]["arguments"]
    assert last_args == payload["messages"][-1]["tool_calls"][0]["function"]["arguments"]
    assert "[provider_request_" not in last_args


def deep_assistant_turn() -> dict[str, object]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "old-call",
                "type": "function",
                "function": {
                    "name": "apply_patch",
                    "arguments": json.dumps({"patch": "p" * 3000}),
                },
            }
        ],
    }


def test_protect_recent_assistant_exempts_last_turn_tier3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROTECT_RECENT_ENV, "1")
    fresh_patch = "diff --git a/f b/f\n" + "+" + "p" * 2000
    payload = {
        "messages": [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "old " + "o" * 2000},
            {"role": "user", "content": "go on"},
            {"role": "assistant", "content": fresh_patch},
        ]
    }
    compacted = _emergency_compact_current_turn_payload_once(payload)
    assert "emergency_compacted" in compacted["messages"][1]["content"]
    assert compacted["messages"][3]["content"] == fresh_patch


def test_protect_recent_assistant_hard_cap_degrades_to_emergency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROTECT_RECENT_ENV, "1")
    fresh_patch = "d" * 5000
    payload = {
        "messages": [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "old " + "o" * 2000},
            {"role": "assistant", "content": fresh_patch},
        ]
    }
    compacted = _final_hard_cap_payload_once(payload)
    assert compacted["messages"][1]["content"].startswith("[opensquilla_compacted:")
    # Protected turn keeps head/tail context instead of the sha-only marker.
    protected = compacted["messages"][2]["content"]
    assert not protected.startswith("[opensquilla_compacted:")
    assert protected.startswith("d" * 180)
    assert "emergency_compacted" in protected


def test_proof_reports_tier_and_lever_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TINY_GUARD_ENV, "120")
    monkeypatch.setenv(PROTECT_RECENT_ENV, "on")
    payload = {
        "messages": [
            {"role": "user", "content": "task"},
            {"role": "tool", "tool_call_id": "c1", "content": "r" * 4000},
        ]
    }
    compacted, proof = prove_or_compact_provider_payload(
        payload,
        projection_adapter="openai",
        proof_budget=3000,
    )
    assert proof is not None
    assert proof["compaction_tier"] == proof["retry_count"]
    assert proof["compaction_tier"] >= 1
    assert proof["compaction_tiny_guard_chars"] == 120
    assert proof["compaction_protect_recent_assistant"] is True


def test_proof_tier_zero_when_fits() -> None:
    _, proof = prove_or_compact_provider_payload(
        {"messages": [{"role": "user", "content": "small"}]},
        projection_adapter="openai",
        proof_budget=10_000,
    )
    assert proof is not None
    assert proof["compaction_tier"] == 0
    assert proof["compaction_tiny_guard_chars"] == 0
    assert proof["compaction_protect_recent_assistant"] is False
