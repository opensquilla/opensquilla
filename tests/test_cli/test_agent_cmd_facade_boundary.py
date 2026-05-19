from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.cli import agent_cmd, agent_command_output, agent_run_runtime

ROOT = Path(__file__).resolve().parents[2]
AGENT_CMD = ROOT / "src" / "opensquilla" / "cli" / "agent_cmd.py"


def _defined_functions() -> set[str]:
    tree = ast.parse(AGENT_CMD.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_agent_cmd_reexports_run_agent_once_from_runtime_boundary() -> None:
    assert agent_cmd.run_agent_once is agent_run_runtime.run_agent_once
    assert "run_agent_once" not in _defined_functions()


def test_agent_cmd_uses_command_output_boundary_for_rendering() -> None:
    assert agent_cmd.agent_result_payload is agent_command_output.agent_result_payload
    assert agent_cmd.render_agent_result is agent_command_output.render_agent_result
