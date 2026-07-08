"""scrub_text: secret masking + home-dir normalization for shareable artifacts."""

from __future__ import annotations

from pathlib import Path

from opensquilla.observability.redact import scrub_text

FAKE_KEY = "sk-FAKE1234567890abcdef"


def test_masks_secret_shaped_assignments() -> None:
    text = (
        f"api_key={FAKE_KEY}\n"
        f'"slack_token": "xoxb-FAKE-0000"\n'
        f"password = hunter2-fake\n"
        f"Authorization: Bearer {FAKE_KEY}\n"
    )
    scrubbed = scrub_text(text)
    assert FAKE_KEY not in scrubbed
    assert "xoxb-FAKE-0000" not in scrubbed
    assert "hunter2-fake" not in scrubbed
    assert scrubbed.count("[redacted]") >= 4


def test_normalizes_home_directory() -> None:
    home = str(Path.home())
    scrubbed = scrub_text(f"config loaded from {home}/.opensquilla/config.toml")
    assert home not in scrubbed
    assert "~/.opensquilla/config.toml" in scrubbed


def test_leaves_ordinary_text_alone() -> None:
    text = "2026-07-07 [ERROR] opensquilla.engine: turn_runner.failed session_key='agent:x'"
    assert scrub_text(text) == text


def test_masks_quoted_multiword_value_fully() -> None:
    scrubbed = scrub_text('password = "correct horse battery staple"')
    assert "correct horse battery staple" not in scrubbed
    assert "horse" not in scrubbed
    assert "staple" not in scrubbed
    assert "[redacted]" in scrubbed


TRICKY_INPUTS = [
    f"api_key={FAKE_KEY}",
    '"slack_token": "xoxb-FAKE-0000"',
    "password = hunter2-fake",
    f"Authorization: Bearer {FAKE_KEY}",
    'password = "correct horse battery staple"',
    "Authorization: Basic dXNlcjpwYXNzLWZha2U=",
    "retrying with header Bearer abc+def/gh== now",
    "session_key=abc",
    "password:\nRestarting the gateway",
    "api_key=[redacted]",
    'secret_key=abc123 private-key: xyz789 "secret_access_key": "AKIAFAKE999"',
]


def test_scrub_is_idempotent() -> None:
    for text in TRICKY_INPUTS:
        once = scrub_text(text)
        assert scrub_text(once) == once, f"double scrub diverged for {text!r}"


def test_masks_basic_auth_credential() -> None:
    scrubbed = scrub_text("Authorization: Basic dXNlcjpwYXNzLWZha2U=")
    assert "dXNlcjpwYXNzLWZha2U=" not in scrubbed
    assert "[redacted]" in scrubbed


def test_masks_base64_bearer_token_fully() -> None:
    scrubbed = scrub_text("retrying with header Bearer abc+def/gh== now")
    assert "abc+def/gh==" not in scrubbed
    assert "gh==" not in scrubbed
    assert "[redacted]" in scrubbed


def test_masks_additional_secret_key_variants() -> None:
    text = 'secret_key=abc123 private-key: xyz789 "secret_access_key": "AKIAFAKE999"'
    scrubbed = scrub_text(text)
    assert "abc123" not in scrubbed
    assert "xyz789" not in scrubbed
    assert "AKIAFAKE999" not in scrubbed


def test_session_key_stays_readable() -> None:
    scrubbed = scrub_text("resuming turn with session_key=abc")
    assert "session_key=abc" in scrubbed


def test_bare_label_does_not_mask_next_line() -> None:
    text = "password:\nRestarting the gateway"
    assert scrub_text(text) == text
