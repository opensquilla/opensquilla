from __future__ import annotations

import json

import pytest

from tui_real_terminal.scenarios import scenario_by_id

pytestmark = pytest.mark.tui_real_terminal

PASTED_INPUT = "first line\nsecond line CJK混合ASCII"


def test_terminal_resize_paste_ctrl_c_and_eof(run_real_terminal_scenario) -> None:
    result = run_real_terminal_scenario(scenario_by_id("terminal_changes"))

    assert result.status == "pass"
    assert (result.run_dir / "frames").is_dir()
    assert (result.run_dir / "transcript.txt").exists()
    scrollback = (result.run_dir / "scrollback.txt").read_text(encoding="utf-8")
    assert "terminal-change-response lines=2" in scrollback
    assert "echo-line-0:first line" in scrollback
    assert "echo-line-1:second line CJK混合ASCII" in scrollback
    # The dispatch log records the exact submitted text: the multi-line paste
    # must reach the app with its newline intact, not collapsed to one line.
    app_events = [
        json.loads(line)
        for line in (result.run_dir / "opentui-app.log")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    submitted = [
        event["payload"].get("input", "")
        for event in app_events
        if event["event"] == "dispatch"
    ]
    assert PASTED_INPUT in submitted
