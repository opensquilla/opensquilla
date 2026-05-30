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


def test_opentui_host_uses_fullscreen_scrollbox_layout() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert 'screenMode: "alternate-screen"' in source
    assert "ScrollBoxRenderable" in source
    assert 'stickyStart: "bottom"' in source
    assert "viewportCulling" in source
    assert 'id: "composer-box"' in source
    assert 'id: "router-plugin"' in source
    assert 'screenMode: "split-footer"' not in source
    assert "writeToScrollback" not in source


def test_opentui_host_locks_recommended_daily_visual_preset() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "OPENTUI_DAILY_THEME" in source
    assert 'preset: "daily"' in source
    assert 'frame: "card"' in source
    assert "#77B7FF" in source
    assert "conversationBox.add" in source
    assert "TextRenderable(renderer" in source
    assert "`tmp-${scrollbackSeq++}`" in source
    assert "`sb-${scrollbackSeq++}`" in source
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
    assert "conversationBox" in source


def test_opentui_footer_revives_status_and_composer_and_router_color() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "syncPulseTimer" in source
    assert "setInterval" in source
    assert "composerDisabledBorder" in source
    assert "colorForStyle(routerState.style)" in source
    assert "backgroundColor" not in source
