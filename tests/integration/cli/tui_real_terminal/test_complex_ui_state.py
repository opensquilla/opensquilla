from __future__ import annotations

from pathlib import Path

import pytest

from tui_real_terminal.assertions import assert_visible_text
from tui_real_terminal.driver import TerminalFrame, TerminalSize
from tui_real_terminal.evidence import ScenarioResult
from tui_real_terminal.scenarios import scenario_by_id

pytestmark = pytest.mark.tui_real_terminal


def test_complex_ui_state(run_real_terminal_scenario) -> None:
    scenario = scenario_by_id("complex_ui_state")
    result = run_real_terminal_scenario(scenario)

    assert result.status == "pass"
    assert (result.run_dir / "frames").is_dir()
    assert (result.run_dir / "transcript.txt").exists()
    intermediate_frame = _read_frame(
        result,
        "during-intermediate",
        scenario.initial_size,
    )

    assert result.backend_id == "opentui"
    assert_visible_text(intermediate_frame, "intermediate-before-tool")
    intermediate_lines = [
        line
        for line in intermediate_frame.text.splitlines()
        if "intermediate-before-tool" in line
    ]
    assert intermediate_lines
    assert intermediate_lines[0].lstrip().startswith("✱ ")
    assert "…" in intermediate_lines[0]
    assert "second-intermediate-line" in intermediate_frame.text


def _read_frame(
    result: ScenarioResult,
    checkpoint: str,
    size: TerminalSize,
) -> TerminalFrame:
    frame_path = _frame_path(result.run_dir, checkpoint)
    return TerminalFrame(
        checkpoint,
        frame_path.read_text(encoding="utf-8"),
        0,
        size,
    )


def _frame_path(run_dir: Path, checkpoint: str) -> Path:
    matches = sorted((run_dir / "frames").glob(f"*-{checkpoint}.txt"))
    if len(matches) == 1:
        return matches[0]
    available = ", ".join(path.name for path in sorted((run_dir / "frames").glob("*.txt")))
    raise AssertionError(
        f"expected exactly one frame for checkpoint {checkpoint!r}; available: {available}"
    )
