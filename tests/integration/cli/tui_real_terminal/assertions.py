from __future__ import annotations

import re

from tui_real_terminal.driver import TerminalFrame

_ANSI_RE = re.compile(
    r"\x1b(?:"
    r"\[[0-?]*[ -/]*[@-~]"
    r"|\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|P[^\x1b]*\x1b\\"
    r"|[@-Z\\-_]"
    r")"
)


def assert_visible_text(frame: TerminalFrame, expected: str) -> None:
    if expected not in frame.text:
        raise AssertionError(
            f"{frame.checkpoint}: expected visible text {expected!r}; screen was:\n"
            f"{frame.text}"
        )


def assert_prompt_ready(frame: TerminalFrame) -> None:
    if "you" not in frame.text:
        raise AssertionError(f"{frame.checkpoint}: prompt is not visibly ready:\n{frame.text}")


def assert_no_traceback(frame: TerminalFrame) -> None:
    forbidden = (
        "Traceback (most recent call last)",
        "RuntimeError:",
        "Unhandled exception",
    )
    for marker in forbidden:
        if marker in frame.text:
            raise AssertionError(f"{frame.checkpoint}: unexpected error marker {marker!r}")


def assert_no_raw_ansi_leakage(frame: TerminalFrame) -> None:
    match = _ANSI_RE.search(frame.text)
    if match:
        raise AssertionError(
            f"{frame.checkpoint}: raw terminal escape leaked at offset {match.start()}"
        )
