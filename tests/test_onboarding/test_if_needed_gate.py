"""End-to-end coverage for the ``onboard --if-needed`` gate.

The gate represents first-run readiness. Optional capability sections still
surface action-required metadata, but they must not keep provider-complete
installs inside the interactive wizard forever.

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
    assert "core setup is ready" in recorder.joined()
    assert "optional capabilities need action" in recorder.joined()
    assert "Optional next moves" in recorder.joined()
    assert "Headless channel" in recorder.joined()


def test_if_needed_surfaces_optional_actions_without_running_wizard(
    monkeypatch, tmp_path, recorder, runner
):
    cfg = _llm_ok_cfg()
    cfg.llm = LlmProviderConfig(
        provider="deepseek",
        model="m",
        api_key="sk-x",
        base_url="https://api.deepseek.com/v1",
    )
    cfg.search_provider = "brave"
    cfg.search_api_key = ""
    cfg.search_api_key_env = ""
    cfg.image_generation.enabled = True
    cfg.image_generation.primary = "openai/gpt-image-1"
    cfg.memory.embedding.provider = "auto"

    config_path = tmp_path / "config.toml"
    config_path.write_text("")
    cfg.config_path = str(config_path)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("opensquilla.cli.onboard_cmd.load_config", lambda _path=None: cfg)

    status = get_onboarding_status(cfg)
    assert status.needs_onboarding is False
    action_sections = ("search", "image_generation")
    for section in action_sections:
        assert status.section_details[section]["actionRequired"] is True

    # Guard the assertion: this path should exit before the wizard is reached.
    monkeypatch.setattr("opensquilla.onboarding.flow._is_tty", lambda: False)

    result = runner.invoke(app, ["onboard", "--if-needed"])
    assert result.exit_code == 0, result.output
    assert "core setup is ready" in recorder.joined()
    assert "optional capabilities need action" in recorder.joined()
    for section in action_sections:
        assert status.section_details[section]["label"] in recorder.joined()
    assert "already complete" not in recorder.joined()
    assert "unfinished sections" not in recorder.joined()


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
