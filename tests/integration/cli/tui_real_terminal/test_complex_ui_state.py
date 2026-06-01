from __future__ import annotations

import pytest

from tui_real_terminal.scenarios import scenario_by_id

pytestmark = pytest.mark.tui_real_terminal


def test_complex_ui_state(run_real_terminal_scenario) -> None:
    result = run_real_terminal_scenario(scenario_by_id("complex_ui_state"))

    assert result.status == "pass"
    assert (result.run_dir / "frames").is_dir()
    assert (result.run_dir / "transcript.txt").exists()
    last_frame = sorted((result.run_dir / "frames").glob("*.txt"))[-1].read_text(
        encoding="utf-8"
    )
    scrollback = (result.run_dir / "scrollback.txt").read_text(encoding="utf-8")
    rendered = f"{last_frame}\n{scrollback}"
    if result.backend_id == "textual":
        router_lines = [line for line in rendered.splitlines() if "Router:" in line]
        assert "Router:" in rendered
        assert "fake-terminal" in rendered
        assert "save 42%" in rendered
        assert router_lines
    if result.backend_id == "opentui":
        intermediate_lines = [
            line for line in rendered.splitlines() if "intermediate-before-tool" in line
        ]
        assert intermediate_lines
        assert intermediate_lines[0].lstrip().startswith("✱ ")
        assert "…" in intermediate_lines[0]
        assert "second-intermediate-line" in rendered
