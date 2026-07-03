"""Regression tests for the sandboxed-subprocess environment builder.

``run_sandboxed`` must give the child process the allowlisted subset of the
parent environment (PATH, HOME, ...) and then overlay any allowlisted
caller-supplied overrides. A caller-supplied ``env`` must never *replace* the
parent environment — the NoopBackend passes ``env=_filtered_request_env(...)``,
which is ``{}`` for tools like git that request ``env={}``, and an empty dict
must not strip PATH/HOME from the spawned process.
"""

from __future__ import annotations

from opensquilla.safety.sandbox import _filtered_env

_WHITELIST = ["PATH", "HOME", "LANG"]


def test_filtered_env_none_returns_allowlisted_parent(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/tester")
    monkeypatch.delenv("LANG", raising=False)

    result = _filtered_env(_WHITELIST)

    assert result == {"PATH": "/usr/bin", "HOME": "/home/tester"}


def test_filtered_env_empty_dict_keeps_parent_env(monkeypatch) -> None:
    # The regression: an empty caller env must not blank out the child env.
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/tester")

    result = _filtered_env(_WHITELIST, {})

    assert result["PATH"] == "/usr/bin"
    assert result["HOME"] == "/home/tester"


def test_filtered_env_overlays_allowlisted_caller_vars(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/tester")

    result = _filtered_env(_WHITELIST, {"PATH": "/opt/bin", "EVIL": "leak"})

    assert result["PATH"] == "/opt/bin"  # allowlisted caller override wins
    assert result["HOME"] == "/home/tester"  # parent value preserved
    assert "EVIL" not in result  # non-allowlisted caller var dropped
