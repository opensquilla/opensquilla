"""CLI help presentation tests."""

from __future__ import annotations

import re
from pathlib import Path

import click
from typer import rich_utils
from typer.testing import CliRunner

from opensquilla.cli.main import app
from opensquilla.ui import ACCENT, questionary_style

runner = CliRunner()


def test_rich_help_uses_opensquilla_accent() -> None:
    assert rich_utils.STYLE_OPTIONS_PANEL_BORDER == ACCENT
    assert rich_utils.STYLE_COMMANDS_PANEL_BORDER == ACCENT
    assert rich_utils.STYLE_OPTION == f"bold {ACCENT}"
    assert rich_utils.STYLE_COMMANDS_TABLE_FIRST_COLUMN == f"bold {ACCENT}"


def test_questionary_checkbox_selection_avoids_reverse_row_highlight() -> None:
    style = questionary_style()
    assert style is not None
    rules = dict(style.style_rules)

    for token in ("pointer", "highlighted", "selected"):
        assert "noreverse" in rules[token]
        assert "bg:" not in rules[token]


def test_onboard_help_keeps_router_option_readable() -> None:
    result = runner.invoke(app, ["onboard", "--help"], terminal_width=100)

    assert result.exit_code == 0, result.output
    output = click.unstyle(result.output)
    assert "--router" in output
    assert "--router MODE" in output
    assert "Router profile: recommended," in output
    assert "openrouter-mix, or" in output
    assert "disabled." in output
    assert "TEXT  recommended | openrouter-mix" not in output


def test_onboard_help_uses_compact_option_columns() -> None:
    result = runner.invoke(app, ["onboard", "--help"], terminal_width=100)

    assert result.exit_code == 0, result.output
    output = click.unstyle(result.output)
    assert "--provider TEXT" in output
    assert "--router MODE" in output
    assert not re.search(r"--provider\s{12,}TEXT", output)


def test_onboard_help_explains_first_run_inputs() -> None:
    result = runner.invoke(app, ["onboard", "--help"], terminal_width=110)

    assert result.exit_code == 0, result.output
    output = click.unstyle(result.output)
    assert "OpenSquilla setup cockpit" in output
    assert "SquillaRouter" in output
    assert "Provider id to configure" in output
    assert "Model id for the provider" in output
    assert "Read the provider key from this environment" in output
    assert "variable." in output
    assert "Only run the wizard when required setup is" in output
    assert "incomplete." in output
    assert "Leave channel setup for later" in output
    assert "Leave optional Web search setup for later" in output
    assert "Leave optional image generation setup for later" in output


def test_configure_help_explains_section_specific_inputs() -> None:
    result = runner.invoke(app, ["configure", "--help"], terminal_width=110)

    assert result.exit_code == 0, result.output
    output = click.unstyle(result.output)
    normalized = " ".join(output.replace("│", " ").split())
    assert "Reconfigure provider, router, channels, search, image generation, or memory" in output
    assert "Usage:" in output
    assert "[SECTION]" in output
    assert "SECTION_ARG" not in output
    assert "Section to configure" in output
    assert "Text provider id for provider setup" in normalized
    assert "Search provider id" in normalized
    assert "Image provider id" in normalized
    assert "Model id for provider or remote memory embedding" in normalized
    assert "Channel type such as slack, discord, feishu" in normalized
    assert "Image model id" in normalized
    assert "Memory embedding provider" in output


def test_help_theme_supports_click_make_metavar_without_context(monkeypatch) -> None:
    def legacy_make_metavar(self: click.Option) -> str:
        if self.is_bool_flag:
            return "BOOLEAN"
        return self.metavar or self.type.name.upper()

    monkeypatch.setattr(click.Option, "make_metavar", legacy_make_metavar)

    result = runner.invoke(app, ["onboard", "--help"], terminal_width=100)

    assert result.exit_code == 0, result.output
    output = click.unstyle(result.output)
    assert "--provider TEXT" in output
    assert "--router MODE" in output


def test_cli_brand_surfaces_do_not_use_cyan() -> None:
    cli_files = [*Path("src/opensquilla/cli").rglob("*.py"), Path("src/opensquilla/ui.py")]
    forbidden = (
        "bold cyan",
        "[cyan]",
        "[/cyan]",
        "typer.colors.CYAN",
        'style="cyan"',
    )

    offenders: list[str] = []
    for path in cli_files:
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{path}:{needle}")

    assert offenders == []
