"""End-to-end coverage for the ``onboard --if-needed`` gate.

The user-reported regression was: after cancelling the search section
mid-flow, ``onboard --if-needed`` falsely reported "complete" because the
gate only consulted ``llm_configured``. With section-verifier semantics
the gate must escalate to every section so a stuck search step keeps the
operator in the flow.

Console output is captured by monkeypatching ``opensquilla.cli.onboard_cmd.console``
rather than ``capsys``. Rich consoles bind to a stdout reference at import
time, which makes ``capsys`` brittle under full-suite execution.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from opensquilla.cli.main import app
from opensquilla.gateway.config import GatewayConfig, LlmProviderConfig
from opensquilla.onboarding.status import get_onboarding_status


class _RecordingConsole:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, message: str = "", *_a, **_kw) -> None:
        self.messages.append(str(message))

    def joined(self) -> str:
        return "\n".join(self.messages)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def recorder(monkeypatch) -> _RecordingConsole:
    instance = _RecordingConsole()
    monkeypatch.setattr("opensquilla.cli.onboard_cmd.console", instance)
    return instance


def _llm_ok_cfg() -> GatewayConfig:
    cfg = GatewayConfig()
    cfg.llm = LlmProviderConfig(
        provider="openrouter",
        model="m",
        api_key="sk-x",
        base_url="https://openrouter.ai/api/v1",
    )
    return cfg


def test_if_needed_skips_when_all_sections_ok_or_optional(
    monkeypatch, tmp_path, recorder, runner
):
    cfg = _llm_ok_cfg()
    # Fresh config persisted to disk so has_config=True.
    config_path = tmp_path / "config.toml"
    config_path.write_text("")
    cfg.config_path = str(config_path)

    monkeypatch.setattr("opensquilla.cli.onboard_cmd.load_config", lambda _path=None: cfg)

    result = runner.invoke(app, ["onboard", "--if-needed"])
    assert result.exit_code == 0, result.output
    assert "already complete" in recorder.joined()


def test_if_needed_does_not_skip_when_search_was_cancelled(
    monkeypatch, tmp_path, recorder, runner
):
    """Reproduces the user's original report:

    Provider was configured, then the search step crashed at the api-key
    prompt. ``onboard --if-needed`` used to print "already complete" and
    exit. With section verifiers it must keep the operator in the flow.
    """
    cfg = _llm_ok_cfg()
    cfg.search_provider = "brave"
    cfg.search_api_key = ""
    cfg.search_api_key_env = ""

    config_path = tmp_path / "config.toml"
    config_path.write_text("")
    cfg.config_path = str(config_path)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setattr("opensquilla.cli.onboard_cmd.load_config", lambda _path=None: cfg)

    status = get_onboarding_status(cfg)
    assert status.needs_onboarding is True
    assert status.sections["search"].value == "missing"

    # Force non-TTY exit path so the interactive flow does not actually run.
    monkeypatch.setattr("opensquilla.onboarding.flow._is_tty", lambda: False)

    runner.invoke(app, ["onboard", "--if-needed"])
    assert "already complete" not in recorder.joined()
    assert "unfinished sections" in recorder.joined()
    assert "search" in recorder.joined()


def test_onboard_status_subcommand_emits_json(monkeypatch, tmp_path, runner):
    cfg = _llm_ok_cfg()
    config_path = tmp_path / "config.toml"
    config_path.write_text("")
    cfg.config_path = str(config_path)
    monkeypatch.setattr("opensquilla.cli.onboard_cmd.load_config", lambda _path=None: cfg)

    result = runner.invoke(app, ["onboard", "status", "--json"])
    assert result.exit_code == 0, result.output
    import json

    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["needsOnboarding"] is False
    assert payload["sections"]["llm"] == "ok"
    assert "router" in payload["sections"]
