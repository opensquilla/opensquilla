"""Config-directory writability preflight for the interactive wizard.

An unwritable state/config directory used to surface as a raw
``PermissionError`` traceback only at persist time — after the operator had
already answered every prompt, including pasting the API key. The wizard now
probes writability before the first prompt and exits with code 2 and an
actionable message instead.
"""

from __future__ import annotations

import os
import sys
import types
from io import StringIO
from typing import Any

import pytest
from rich.console import Console

from opensquilla.onboarding import flow

pytestmark = pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="read-only directory permissions are not enforceable for this user",
)


class _NoPromptQuestionary(types.SimpleNamespace):
    """Every prompt is a test failure: nothing may fire before the preflight."""

    def _fail(self, message: str) -> Any:
        raise AssertionError(f"prompt fired despite unwritable config dir: {message}")

    def select(self, message: str, **_kwargs: Any) -> Any:
        return self._fail(message)

    def text(self, message: str, **_kwargs: Any) -> Any:
        return self._fail(message)

    def password(self, message: str, **_kwargs: Any) -> Any:
        return self._fail(message)

    def confirm(self, message: str, **_kwargs: Any) -> Any:
        return self._fail(message)

    def checkbox(self, message: str, **_kwargs: Any) -> Any:
        return self._fail(message)


def _capture_console(monkeypatch) -> StringIO:
    output = StringIO()
    monkeypatch.setattr(
        flow,
        "console",
        Console(file=output, force_terminal=False, highlight=False, width=300),
    )
    return output


def test_onboard_unwritable_config_dir_exits_2_before_any_prompt(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    target = state_dir / "config.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    output = _capture_console(monkeypatch)
    gate_fired: list[str] = []
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: gate_fired.append("start"))
    monkeypatch.setattr(flow, "detect_default_sources", lambda: [])
    monkeypatch.setitem(sys.modules, "questionary", _NoPromptQuestionary())

    state_dir.chmod(0o500)
    try:
        with pytest.raises(SystemExit) as exc_info:
            flow.run_interactive_onboard(flow.OnboardOptions())
    finally:
        state_dir.chmod(0o700)

    assert exc_info.value.code == 2
    # No input was wasted: not even the "Press Enter to start setup" gate ran.
    assert gate_fired == []
    out = output.getvalue()
    assert "Setup directory not writable" in out
    assert str(state_dir) in out
    assert "--config" in out
    assert not target.exists()


def test_onboard_uncreatable_config_dir_exits_2(tmp_path, monkeypatch):
    """A config path whose parent directory cannot even be created must fail
    the same actionable way instead of crashing inside ``mkdir``."""

    locked_root = tmp_path / "locked"
    locked_root.mkdir()
    target = locked_root / "nested" / "config.toml"
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    output = _capture_console(monkeypatch)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: None)
    monkeypatch.setattr(flow, "detect_default_sources", lambda: [])
    monkeypatch.setitem(sys.modules, "questionary", _NoPromptQuestionary())

    locked_root.chmod(0o500)
    try:
        with pytest.raises(SystemExit) as exc_info:
            flow.run_interactive_onboard(flow.OnboardOptions(config_path=target))
    finally:
        locked_root.chmod(0o700)

    assert exc_info.value.code == 2
    assert "Setup directory not writable" in output.getvalue()


def test_writability_preflight_creates_dir_and_leaves_no_probe_file(tmp_path):
    target = tmp_path / "state" / "config.toml"

    flow._ensure_config_dir_writable(target)

    assert (tmp_path / "state").is_dir()
    assert list((tmp_path / "state").iterdir()) == []
