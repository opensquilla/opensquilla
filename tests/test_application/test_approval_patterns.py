from __future__ import annotations

from opensquilla.application.approval_queue import classify_command


def test_deny_only_match_returns_deny() -> None:
    assert classify_command("rm -rf /tmp/x", allow_patterns=[], deny_patterns=["rm *"]) == "deny"


def test_allow_only_match_returns_allow() -> None:
    assert (
        classify_command("uv run pytest", allow_patterns=["uv *"], deny_patterns=[]) == "allow"
    )


def test_deny_takes_precedence_when_both_match() -> None:
    assert (
        classify_command(
            "rm -rf /tmp/x",
            allow_patterns=["rm *"],
            deny_patterns=["rm *"],
        )
        == "deny"
    )


def test_no_match_returns_none() -> None:
    assert classify_command("ls -la", allow_patterns=["uv *"], deny_patterns=["rm *"]) is None


def test_empty_command_returns_none() -> None:
    assert classify_command("", allow_patterns=["*"], deny_patterns=["*"]) is None


def test_glob_wildcard_matches_command() -> None:
    assert (
        classify_command("git push --force", allow_patterns=[], deny_patterns=["git push *"])
        == "deny"
    )


def test_substring_fallback_matches_without_wildcard() -> None:
    # A bare token with no glob metacharacter still matches as a substring.
    assert (
        classify_command("sudo systemctl restart x", allow_patterns=[], deny_patterns=["sudo"])
        == "deny"
    )


def test_matching_is_case_sensitive() -> None:
    assert classify_command("RM file", allow_patterns=[], deny_patterns=["rm *"]) is None


def test_blank_pattern_never_matches() -> None:
    assert classify_command("rm file", allow_patterns=["   "], deny_patterns=["  "]) is None
