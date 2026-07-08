"""scrub_text: secret masking + home-dir normalization for shareable artifacts."""

from __future__ import annotations

from pathlib import Path

from opensquilla.observability.redact import scrub_text

FAKE_KEY = "sk-FAKE1234567890abcdef"

# Synthetic bare tokens (no key=value structure around them), as they appear
# verbatim inside provider/channel error messages.
FAKE_OPENAI = "sk-FAKEabc123def456ghi789"
FAKE_OPENAI_PROJ = "sk-proj-FAKEabc123def456ghi789"
FAKE_OPENAI_ANT = "sk-ant-api03-FAKEabc123def456ghi789"
FAKE_SLACK_BOT = "xoxb-FAKE1234567890-abcdefghij"
FAKE_SLACK_WEBHOOK = "https://hooks.slack.com/services/T0FAKE123/B0FAKE456/FAKEabcdefFAKE"
# Assembled at runtime so the tracked source never contains a GitHub-token-
# shaped literal (the public-release hygiene scan flags those shapes).
FAKE_GITHUB_PAT = "ghp_" + "FAKEabc123def456ghi789jkl"
FAKE_GITHUB_FINE_PAT = "github_pat_" + "FAKE1234567890abcdef_FAKEmoretail"
FAKE_AWS_KEY_ID = "AKIAFAKE0123456789AB"
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJGQUtFIjoidHJ1ZSJ9.FAKEsig1234567890"
FAKE_GOOGLE_KEY = "AIzaFAKE0123456789abcdefghijklmnopqrstu"

BARE_TOKENS = [
    FAKE_OPENAI,
    FAKE_OPENAI_PROJ,
    FAKE_OPENAI_ANT,
    FAKE_SLACK_BOT,
    FAKE_GITHUB_PAT,
    FAKE_GITHUB_FINE_PAT,
    FAKE_AWS_KEY_ID,
    FAKE_JWT,
    FAKE_GOOGLE_KEY,
]


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
    *(f"provider said: {token} was rejected" for token in BARE_TOKENS),
    f"error posting to {FAKE_SLACK_WEBHOOK} (404)",
    f'{{"error": {{"message": "Incorrect API key {FAKE_OPENAI} provided"}}}}',
    "no tokens here: skill risk-free eyJustSaying task-1234 AKIAplan",
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


def test_masks_bare_tokens_in_prose() -> None:
    for token in BARE_TOKENS:
        text = f"provider error: token {token} was rejected upstream"
        scrubbed = scrub_text(text)
        assert token not in scrubbed, f"bare token survived: {token!r}"
        assert "[redacted]" in scrubbed
        assert scrubbed.startswith("provider error: token ")
        assert scrubbed.endswith(" was rejected upstream")


def test_masks_bare_tokens_inside_json_blob() -> None:
    for token in BARE_TOKENS:
        text = f'{{"error": {{"message": "Incorrect API key {token} provided", "code": 401}}}}'
        scrubbed = scrub_text(text)
        assert token not in scrubbed, f"bare token survived in JSON: {token!r}"
        assert '"code": 401' in scrubbed
        assert "Incorrect API key" in scrubbed


def test_masks_openai_style_error_message() -> None:
    text = f"Incorrect API key {FAKE_OPENAI} provided. You can find your key at ..."
    scrubbed = scrub_text(text)
    assert FAKE_OPENAI not in scrubbed
    assert "Incorrect API key [redacted] provided" in scrubbed


def test_masks_slack_webhook_path() -> None:
    text = f"channel delivery failed: POST {FAKE_SLACK_WEBHOOK} returned 404"
    scrubbed = scrub_text(text)
    assert "T0FAKE123" not in scrubbed
    assert "FAKEabcdefFAKE" not in scrubbed
    assert "hooks.slack.com/services/" in scrubbed
    assert "returned 404" in scrubbed


def test_bare_token_prose_non_matches() -> None:
    # Ordinary words and short identifiers that resemble token prefixes must
    # never be masked: word-boundary anchors + length floors.
    for text in [
        "the skill loader retried the task",
        "this deployment is risk-free and reversible",
        "eyJustSaying this is fine",
        "sk-1 sk-short sk- and ghp_ alone",
        "xoxb- with no tail; AKIA alone; AKIAlowercase123456",
        "AIza too short to be a key",
        "eyJab.eyJcd.ef segments below the floor",
        "task-1234 completed in 20ms",
        "see https://hooks.slack.com/services for docs",
    ]:
        assert scrub_text(text) == text, f"ordinary prose was mangled: {text!r}"


def test_bare_token_masking_is_idempotent() -> None:
    for token in BARE_TOKENS:
        text = f"log line with {token} embedded"
        once = scrub_text(text)
        assert scrub_text(once) == once, f"double scrub diverged for {token!r}"
