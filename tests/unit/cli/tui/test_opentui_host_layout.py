from __future__ import annotations

from pathlib import Path

HOST_SOURCE = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "opensquilla"
    / "cli"
    / "tui"
    / "opentui"
    / "package"
    / "src"
    / "main.mjs"
)


def test_opentui_footer_uses_reference_plugin_layout_contract() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert 'shouldFill: false' in source
    assert 'id: "composer-box"' in source
    assert 'bottomTitle: `${statusIcon()} ${turnStatus.label}`' in source
    assert 'id: "router-plugin"' in source
    assert 'position: "absolute"' in source
    assert 'right: 1' in source
    assert 'bottom: 0' in source
    assert 'title: " router "' in source


def test_opentui_host_locks_recommended_daily_visual_preset() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "OPENTUI_DAILY_THEME" in source
    assert 'preset: "daily"' in source
    assert 'frame: "card"' in source
    assert "#77B7FF" in source
    assert "renderPromptBlock" in source
    assert "renderModelText" in source
    assert "renderToolCall" in source
    assert "renderToolDetail" in source
    assert "renderAnswerText" in source
    assert "renderUsage" in source
    assert "STATUS_PULSE_FRAMES" in source


def test_opentui_host_uses_lines_not_backgrounds_for_visual_separation() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "backgroundColor" not in source
    assert "routerBackground" not in source


def test_opentui_host_removes_regex_timeline_classifier() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "decorateDailyTimelineScrollback" not in source
    assert "classifyDailyTimelineLine" not in source
    assert "colorForDailyScrollback" not in source
    assert "currentTurn" in source


def test_opentui_footer_revives_status_and_composer_and_router_color() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "syncPulseTimer" in source
    assert "setInterval" in source
    assert "composerDisabledBorder" in source
    assert "colorForStyle(routerState.style)" in source
    assert "backgroundColor" not in source
