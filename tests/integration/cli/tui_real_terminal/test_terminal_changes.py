from __future__ import annotations

import pytest

from tui_real_terminal.scenarios import scenario_by_id

pytestmark = pytest.mark.tui_real_terminal


def test_terminal_resize_paste_ctrl_c_and_eof(run_real_terminal_scenario) -> None:
    result = run_real_terminal_scenario(scenario_by_id("terminal_changes"))

    assert result.status == "pass"
    assert (result.run_dir / "frames").is_dir()
    assert (result.run_dir / "transcript.txt").exists()
    scrollback = (result.run_dir / "scrollback.txt").read_text(encoding="utf-8")
    assert "terminal-change-response" in scrollback
    assert "CJK混合ASCII" in scrollback
