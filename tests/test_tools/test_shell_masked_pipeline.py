from __future__ import annotations

import os

import pytest

from opensquilla.execution_status import execution_status_for_tool_result
from opensquilla.tools.builtin import shell


@pytest.mark.parametrize(
    ("command", "output"),
    [
        (
            "pytest -q 2>&1 | head -50",
            "FAILED tests/test_api.py::test_bad - AssertionError\n",
        ),
        (
            "pytest -q 2>&1 | tail -50",
            "=========================== 2 failed, 10 passed in 1.2s ===========================\n",
        ),
        (
            "python -m unittest 2>&1 | head",
            "FAILED (failures=1, errors=1)\n",
        ),
        (
            "npm test 2>&1 | head -100",
            (
                "Test Suites: 1 failed, 4 passed, 5 total\n"
                "Tests:       2 failed, 20 passed, 22 total\n"
            ),
        ),
        (
            "npm test 2>&1 | head -100",
            "FAIL src/auth.test.ts\n  login\n    Expected true to be false\n",
        ),
    ],
)
def test_masked_pipeline_detects_common_test_failure_summaries(
    command: str,
    output: str,
) -> None:
    assert shell._looks_like_masked_pipeline_failure(command, 0, output)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="pipeline semantics are POSIX-specific")
async def test_exec_command_warns_when_pipeline_masks_failure() -> None:
    result = await shell.exec_command(
        "sh -c 'echo BUILD FAILURE; exit 1' 2>&1 | head -20"
    )

    assert result.startswith("exit_code=0\n[shell_warning:masked_pipeline_failure]")
    assert "Treat this result as failed" in result
    status = execution_status_for_tool_result("exec_command", result)
    assert status is not None
    assert status["status"] == "error"
    assert status["exit_code"] == 0
    assert status["reason"] == "masked_pipeline_failure"
    assert status["preservation_class"] == "diagnostic"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="pipeline semantics are POSIX-specific")
async def test_exec_command_does_not_warn_for_intentional_shell_fallback(tmp_path) -> None:
    haystack = tmp_path / "haystack.txt"
    haystack.write_text("present\n", encoding="utf-8")

    result = await shell.exec_command(
        f"grep definitely-missing {haystack} || echo 'File not found'"
    )

    assert result == "exit_code=0\nFile not found\n"
    status = execution_status_for_tool_result("exec_command", result)
    assert status is not None
    assert status["status"] == "success"
    assert status["reason"] is None
