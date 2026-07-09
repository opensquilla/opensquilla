from __future__ import annotations

from opensquilla.safety.secret_redaction import redact_secret_text, redact_secret_value


def test_redact_secret_text_masks_env_assignments_and_provider_keys() -> None:
    text = (
        "env.OPENROUTER_API_KEY=sk-or-v1-abcdefghijklmnopqrstuvwxyz "
        "DASHSCOPE_API_KEY:sk-123456789012345678901234 "
        "Authorization: Bearer secret-token"
    )

    redacted = redact_secret_text(text)

    assert "sk-or-v1-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "sk-123456789012345678901234" not in redacted
    assert "secret-token" not in redacted
    assert "env.OPENROUTER_API_KEY=[REDACTED]" in redacted
    assert "DASHSCOPE_API_KEY:[REDACTED]" in redacted
    assert "Authorization: Bearer [REDACTED]" in redacted


def test_redact_secret_text_masks_bare_tokenrhythm_keys() -> None:
    # Provider errors echo credentials verbatim with no key=value structure
    # ("Incorrect API key sk_tr_... provided"); the underscore prefix is
    # invisible to the hyphen-anchored sk- patterns.
    text = "Incorrect API key sk_tr_FAKEabc123def456ghi789 provided"

    redacted = redact_secret_text(text)

    assert "sk_tr_FAKEabc123def456ghi789" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_secret_text_masks_tokenrhythm_keys_abutting_punctuation() -> None:
    # A key glued to '-' or '_' must over-mask, never fail the trailing
    # boundary and leak whole (the sk- pattern's tail class behaves the same).
    for tail in ("-rotated", "_old"):
        redacted = redact_secret_text(f"old key sk_tr_FAKEabc123def456ghi789{tail} replaced")
        assert "FAKEabc123def456ghi789" not in redacted, tail


def test_redact_secret_text_masks_quoted_assignment_values() -> None:
    text = (
        'password: "hunter2hunter2" '
        "token = 'abcdefabcdef' "
        'api_key="quoted with spaces inside" '
        "client_secret: 'unterminated"
    )

    redacted = redact_secret_text(text)

    assert "hunter2hunter2" not in redacted
    assert "abcdefabcdef" not in redacted
    assert "quoted with spaces inside" not in redacted
    assert "unterminated" not in redacted
    assert "password:[REDACTED]" in redacted
    assert "token=[REDACTED]" in redacted
    assert "api_key=[REDACTED]" in redacted
    assert "client_secret:[REDACTED]" in redacted


def test_redact_secret_text_keeps_quoted_values_for_non_secret_keys() -> None:
    text = 'name: "alice" retry_count = \'3\''

    assert redact_secret_text(text) == text


def test_redact_secret_text_does_not_mask_token_counters() -> None:
    assert redact_secret_text("total_tokens=123 cached_tokens:100") == (
        "total_tokens=123 cached_tokens:100"
    )


def test_redact_secret_value_masks_secret_keys_and_nested_strings() -> None:
    payload = {
        "api_key": "plain-secret",
        "messages": [
            {
                "content": "debug env.OPENROUTER_API_KEY=sk-or-v1-abcdefghijklmnopqrstuvwxyz"
            }
        ],
    }

    redacted = redact_secret_value(payload)

    assert redacted["api_key"] == "[REDACTED]"
    assert "sk-or-v1-abcdefghijklmnopqrstuvwxyz" not in str(redacted)
