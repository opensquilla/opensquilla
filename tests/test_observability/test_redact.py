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
