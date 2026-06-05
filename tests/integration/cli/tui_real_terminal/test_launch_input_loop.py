from __future__ import annotations

import pytest

from tui_real_terminal.scenarios import scenario_by_id

pytestmark = pytest.mark.tui_real_terminal


def test_terminal_launch_and_input_loop(run_real_terminal_scenario) -> None:
    result = run_real_terminal_scenario(scenario_by_id("launch_input_loop"))

    assert result.status == "pass"
    assert (result.run_dir / "scenario.json").exists()
    assert (result.run_dir / "transcript.txt").exists()
    assert (result.run_dir / "frames").is_dir()


def test_terminal_cjk_input_loop(run_real_terminal_scenario) -> None:
    result = run_real_terminal_scenario(scenario_by_id("cjk_input_loop"))

    assert result.status == "pass"
    assert (result.run_dir / "transcript.txt").exists()
