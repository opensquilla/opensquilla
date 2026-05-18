"""Repository checks for stage test boundaries.

The direct ``*_stage_unit.py`` suites should exercise stage input/output and
port behavior. Full ``TurnRunner._run_turn`` snapshot probes are allowed only in
the transition snapshot suites, where the filename makes the coupling explicit.
"""

from __future__ import annotations

from pathlib import Path

_TURN_RUNNER_TEST_DIR = Path(__file__).parent


def test_stage_unit_tests_do_not_frame_walk_or_import_runtime_adapters() -> None:
    offenders: list[str] = []
    for path in sorted(_TURN_RUNNER_TEST_DIR.glob("test_*_stage_unit.py")):
        text = path.read_text(encoding="utf-8")
        if "sys._getframe" in text:
            offenders.append(f"{path.name}: sys._getframe")
        if "from opensquilla.engine.turn_runner.harness import" in text:
            offenders.append(f"{path.name}: harness import")
        if "_TurnRunner" in text and "Adapter" in text:
            offenders.append(f"{path.name}: private runtime adapter")

    assert offenders == []


def test_frame_walking_probes_stay_in_snapshot_suites() -> None:
    offenders = [
        path.name
        for path in sorted(_TURN_RUNNER_TEST_DIR.glob("test_*.py"))
        if path != Path(__file__)
        if "sys._getframe" in path.read_text(encoding="utf-8")
        and "_snapshot" not in path.stem
    ]

    assert offenders == []
