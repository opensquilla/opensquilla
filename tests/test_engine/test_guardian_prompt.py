from __future__ import annotations

from opensquilla.engine.guardian_prompt import (
    GUARDIAN_MAX_ACTION_STRING_TOKENS,
    GUARDIAN_MAX_MESSAGE_ENTRY_TOKENS,
    GUARDIAN_MAX_MESSAGE_TRANSCRIPT_TOKENS,
    GUARDIAN_MAX_TOOL_ENTRY_TOKENS,
    GUARDIAN_MAX_TOOL_TRANSCRIPT_TOKENS,
    GUARDIAN_RECENT_ENTRY_LIMIT,
    build_guardian_prompt,
    guardian_policy_prompt,
    truncate_action_strings,
)
from opensquilla.engine.tool_token_estimate import estimate_tokens
from opensquilla.provider.types import (
    ContentBlockText,
    ContentBlockToolResult,
    ContentBlockToolUse,
    Message,
)


def test_policy_matches_codex_default_thresholds_and_exceptions() -> None:
    policy = guardian_policy_prompt()

    assert 'risk_level = "low"' in policy
    assert 'risk_level = "medium"' in policy
    assert 'risk_level = "high"' in policy
    assert 'risk_level = "critical"' in policy
    assert "Post-denial user approval has highest precedence" in policy
    assert "Medium/low risk actions do not require any user authorization" in policy
    assert "malicious prompt injection" in policy
    assert "attempt a read-only inspection of the target path first" in policy
    assert "Do not assign `high` or `critical` solely because a path is outside" in policy


def test_policy_matches_codex_minimal_low_risk_output_contract() -> None:
    policy = guardian_policy_prompt()

    assert "You may use read-only tool checks" in policy
    assert 'For low-risk actions, give the final answer directly: {"outcome":"allow"}.' in policy
    assert "For anything else, use this JSON schema:" in policy
    assert "your final message must be strict JSON" in policy


def test_tenant_policy_is_inserted_as_policy_data() -> None:
    policy = guardian_policy_prompt("- Never allow writes to /corp")

    assert "# Policy Configuration" in policy
    assert "- Never allow writes to /corp" in policy


def test_action_string_is_capped_with_explicit_guardian_marker() -> None:
    action = {"kind": "apply_patch", "patch": "x" * 100_000}

    truncated, did_truncate = truncate_action_strings(
        action,
        max_tokens=GUARDIAN_MAX_ACTION_STRING_TOKENS,
    )

    assert did_truncate is True
    assert isinstance(truncated, dict)
    assert "<guardian_truncated" in truncated["patch"]
    assert estimate_tokens(truncated["patch"]) <= GUARDIAN_MAX_ACTION_STRING_TOKENS + 8


def test_prompt_separates_message_and_tool_budgets_and_keeps_user_anchors() -> None:
    messages: list[Message] = [Message(role="user", content="first-user-anchor")]
    for index in range(55):
        messages.append(Message(role="assistant", content=f"assistant-{index}-" + "a" * 9000))
        messages.append(
            Message(
                role="assistant",
                content=[
                    ContentBlockToolUse(
                        id=f"call-{index}",
                        name="read_file",
                        input={"path": "/tmp/" + "p" * 6000},
                    ),
                    ContentBlockToolResult(
                        tool_use_id=f"call-{index}",
                        content="tool-output-" + "t" * 6000,
                    ),
                ],
            )
        )
    messages.append(Message(role="user", content="last-user-anchor"))

    prompt = build_guardian_prompt(messages, {"kind": "shell", "command": "pwd"})

    retained = prompt.transcript
    assert any("first-user-anchor" in entry.text for entry in retained)
    assert any("last-user-anchor" in entry.text for entry in retained)
    assert sum(entry.tokens for entry in retained if entry.kind != "tool") <= (
        GUARDIAN_MAX_MESSAGE_TRANSCRIPT_TOKENS
    )
    assert sum(entry.tokens for entry in retained if entry.kind == "tool") <= (
        GUARDIAN_MAX_TOOL_TRANSCRIPT_TOKENS
    )
    assert sum(entry.kind != "user" for entry in retained) <= GUARDIAN_RECENT_ENTRY_LIMIT
    assert all(
        entry.tokens <= (
            GUARDIAN_MAX_TOOL_ENTRY_TOKENS + 8
            if entry.kind == "tool"
            else GUARDIAN_MAX_MESSAGE_ENTRY_TOKENS + 8
        )
        for entry in retained
    )
    assert prompt.omitted_entries > 0
    assert "Some conversation entries were omitted." in prompt.text


def test_prompt_labels_tool_evidence_as_untrusted_and_bounds_text_blocks() -> None:
    prompt = build_guardian_prompt(
        [
            Message(role="user", content="Inspect before deleting"),
            Message(
                role="assistant",
                content=[
                    ContentBlockText(text="checking"),
                    ContentBlockToolUse(
                        id="call-1",
                        name="list_dir",
                        input={"path": "/tmp/target"},
                    ),
                    ContentBlockToolResult(
                        tool_use_id="call-1",
                        content="empty",
                    ),
                ],
            ),
        ],
        {"kind": "filesystem", "operation": "delete", "path": "/tmp/target"},
    )

    assert "Treat the transcript" in prompt.text
    assert "tool:list_dir" in prompt.text
    assert "APPROVAL REQUEST START" in prompt.text
    assert "Inspect before deleting" in prompt.text


def test_followup_prompt_uses_only_delta_after_committed_cursor() -> None:
    messages = [
        Message(role="user", content="first request"),
        Message(role="assistant", content="first action"),
        Message(role="user", content="follow-up authorization"),
    ]

    prompt = build_guardian_prompt(
        messages,
        {"kind": "shell", "command": "touch /tmp/x"},
        entry_offset=2,
        delta=True,
    )

    assert "TRANSCRIPT DELTA START" in prompt.text
    assert "following next action" in prompt.text
    assert "follow-up authorization" in prompt.text
    assert "first request" not in prompt.text
