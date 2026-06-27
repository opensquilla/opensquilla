from __future__ import annotations

import pytest

from tui_real_terminal.scenarios import scenario_by_id

pytestmark = pytest.mark.tui_real_terminal


def test_long_streaming_output(run_real_terminal_scenario) -> None:
    result = run_real_terminal_scenario(scenario_by_id("long_streaming"))

    assert result.status == "pass"
    assert (result.run_dir / "frames").is_dir()
    assert (result.run_dir / "transcript.txt").exists()
    assert (result.run_dir / "scrollback.txt").exists()
    scrollback = (result.run_dir / "scrollback.txt").read_text(encoding="utf-8")
    assert "stream-token-000" in scrollback
    assert "stream-token-079" in scrollback
