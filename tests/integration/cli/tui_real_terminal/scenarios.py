from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from tui_real_terminal import assertions
from tui_real_terminal.driver import (
    RealTerminalSession,
    TerminalFrame,
    TerminalSize,
)
from tui_real_terminal.evidence import (
    EvidenceBundle,
    ScenarioFailure,
    ScenarioResult,
)

ScenarioFamily = Literal[
    "launch_and_input_loop",
    "long_streaming_output",
    "complex_ui_state",
    "terminal_changes",
]

ScenarioAction = Literal["wait_text", "send_text", "paste", "key", "resize", "capture"]


@dataclass(frozen=True)
class ScenarioStep:
    step_id: str
    action: ScenarioAction
    value: str = ""
    checkpoint: str = ""
    timeout_s: float = 5.0


@dataclass(frozen=True)
class TuiScenario:
    scenario_id: str
    family: ScenarioFamily
    initial_size: TerminalSize
    steps: tuple[ScenarioStep, ...]
    expected_text: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "family": self.family,
            "initial_size": {
                "cols": self.initial_size.cols,
                "rows": self.initial_size.rows,
            },
            "steps": [step.__dict__ for step in self.steps],
            "expected_text": list(self.expected_text),
        }


def all_scenarios() -> tuple[TuiScenario, ...]:
    return (
        TuiScenario(
            scenario_id="launch_input_loop",
            family="launch_and_input_loop",
            initial_size=TerminalSize(cols=100, rows=30),
            steps=(
                ScenarioStep("wait-ready", "wait_text", "OPEN_SQUILLA_TUI_READY", "ready"),
                ScenarioStep("send-message", "send_text", "hello harness", "after-input"),
                ScenarioStep(
                    "wait-response",
                    "wait_text",
                    "fake-response:hello harness",
                    "after-response",
                ),
            ),
            expected_text=("fake-response:hello harness", "you"),
        ),
        TuiScenario(
            scenario_id="long_streaming",
            family="long_streaming_output",
            initial_size=TerminalSize(cols=100, rows=30),
            steps=(
                ScenarioStep("wait-ready", "wait_text", "OPEN_SQUILLA_TUI_READY", "ready"),
                ScenarioStep("send-message", "send_text", "stream please", "after-input"),
                ScenarioStep(
                    "wait-stream",
                    "wait_text",
                    "stream-token-079",
                    "after-stream",
                    timeout_s=10.0,
                ),
            ),
            expected_text=("stream-token-000", "stream-token-079", "fake-terminal", "you"),
        ),
        TuiScenario(
            scenario_id="complex_ui_state",
            family="complex_ui_state",
            initial_size=TerminalSize(cols=110, rows=34),
            steps=(
                ScenarioStep("wait-ready", "wait_text", "OPEN_SQUILLA_TUI_READY", "ready"),
                ScenarioStep(
                    "send-message",
                    "send_text",
                    "complex state please",
                    "after-input",
                ),
                ScenarioStep(
                    "wait-tool",
                    "wait_text",
                    "complex-state-complete",
                    "after-complex",
                    timeout_s=10.0,
                ),
            ),
            expected_text=(
                "route standard",
                "fake_tool",
                "approval requested",
                "complex-state-complete",
                "you",
            ),
        ),
        TuiScenario(
            scenario_id="terminal_changes",
            family="terminal_changes",
            initial_size=TerminalSize(cols=100, rows=30),
            steps=(
                ScenarioStep("wait-ready", "wait_text", "OPEN_SQUILLA_TUI_READY", "ready"),
                ScenarioStep("resize-narrow", "resize", "72x24", "after-narrow"),
                ScenarioStep(
                    "paste-multiline",
                    "paste",
                    "first line\nsecond line CJK混合ASCII",
                    "after-paste",
                ),
                ScenarioStep("submit-paste", "key", "Enter", "after-submit"),
                ScenarioStep(
                    "wait-terminal-change",
                    "wait_text",
                    "terminal-change-response",
                    "after-response",
                    timeout_s=10.0,
                ),
                ScenarioStep("resize-wide", "resize", "120x34", "after-wide"),
                ScenarioStep("ctrl-c", "key", "C-c", "after-ctrl-c"),
            ),
            expected_text=("terminal-change-response", "CJK混合ASCII", "you"),
        ),
    )


def scenario_by_id(scenario_id: str) -> TuiScenario:
    scenarios = {scenario.scenario_id: scenario for scenario in all_scenarios()}
    try:
        return scenarios[scenario_id]
    except KeyError as exc:
        raise ValueError(f"unknown real-terminal TUI scenario: {scenario_id}") from exc


def run_scenario(
    *,
    scenario: TuiScenario,
    session: RealTerminalSession,
    evidence: EvidenceBundle,
    backend_id: str,
) -> ScenarioResult:
    started_at = time.monotonic()
    evidence.write_scenario(scenario.to_json_dict())
    last_frame = TerminalFrame("not-started", "", 0, scenario.initial_size)
    current_step = "start"
    session.start()
    try:
        last_frame = session.capture_text("started")
        evidence.record_frame(last_frame)
        for step in scenario.steps:
            current_step = step.step_id
            last_frame = _run_step(session, step)
            evidence.record_frame(last_frame)
            assertions.assert_no_traceback(last_frame)
            assertions.assert_no_raw_ansi_leakage(last_frame)
            if not session.is_alive() and step.action != "key":
                raise AssertionError(f"{step.step_id}: terminal process exited unexpectedly")
        for expected in scenario.expected_text:
            assertions.assert_visible_text(last_frame, expected)
        assertions.assert_prompt_ready(last_frame)
        result = ScenarioResult(
            scenario_id=scenario.scenario_id,
            backend_id=backend_id,
            status="pass",
            run_dir=evidence.run_dir,
        )
        evidence.write_result(result)
        return result
    except Exception as exc:
        failure = ScenarioFailure(
            step_id=current_step,
            message=str(exc),
            elapsed_s=round(time.monotonic() - started_at, 3),
            last_screen=last_frame.text,
            artifact_dir=str(evidence.run_dir),
        )
        result = ScenarioResult(
            scenario_id=scenario.scenario_id,
            backend_id=backend_id,
            status="fail",
            run_dir=evidence.run_dir,
            failure=failure,
        )
        evidence.write_result(result)
        raise
    finally:
        session.terminate()


def _run_step(session: RealTerminalSession, step: ScenarioStep) -> TerminalFrame:
    checkpoint = step.checkpoint or step.step_id
    if step.action == "wait_text":
        return session.wait_for_text(
            step.value,
            timeout_s=step.timeout_s,
            checkpoint=checkpoint,
        )
    if step.action == "send_text":
        session.send_text(step.value)
        return session.capture_text(checkpoint)
    if step.action == "paste":
        session.paste(step.value)
        return session.capture_text(checkpoint)
    if step.action == "key":
        session.send_key(step.value)
        return session.capture_text(checkpoint)
    if step.action == "resize":
        cols, rows = step.value.split("x", 1)
        session.resize(TerminalSize(cols=int(cols), rows=int(rows)))
        return session.capture_text(checkpoint)
    if step.action == "capture":
        return session.capture_text(checkpoint)
    raise ValueError(f"unknown scenario step action: {step.action}")
