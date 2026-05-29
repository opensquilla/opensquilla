from __future__ import annotations

import json

import pytest

from tui_real_terminal.scenarios import scenario_by_id

pytestmark = pytest.mark.tui_real_terminal


def test_terminal_resize_paste_ctrl_c_and_eof(run_real_terminal_scenario) -> None:
    result = run_real_terminal_scenario(scenario_by_id("terminal_changes"))

    assert result.status == "pass"
    assert (result.run_dir / "frames").is_dir()
    assert (result.run_dir / "transcript.txt").exists()


def test_textual_cjk_paste_is_visible_and_submitted(
    run_real_terminal_scenario,
    tui_backend: str,
) -> None:
    if tui_backend != "textual":
        pytest.skip("Textual-only paste handling regression")

    result = run_real_terminal_scenario(scenario_by_id("terminal_changes"))

    assert result.status == "pass"
    after_narrow = result.run_dir / "frames" / "002-after-narrow.txt"
    router_lines = [
        line for line in after_narrow.read_text().splitlines() if "Router:" in line
    ]
    assert router_lines
    assert all(line.count("│") >= 4 for line in router_lines)

    after_paste = result.run_dir / "frames" / "003-after-paste.txt"
    assert "CJK混合ASCII" in after_paste.read_text()

    after_response = result.run_dir / "frames" / "005-after-response.txt"
    assert "CJK混合ASCII" in after_response.read_text()
    app_log = result.run_dir / "textual-app.log"
    dispatched = [
        json.loads(line)["payload"].get("input", "")
        for line in app_log.read_text().splitlines()
        if json.loads(line)["event"] == "dispatch"
    ]
    assert any("CJK混合ASCII" in submitted for submitted in dispatched)
