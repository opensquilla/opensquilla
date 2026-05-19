from __future__ import annotations

import ast
import inspect

from opensquilla.cli import agent_run_runtime
from opensquilla.cli.agent_outputs import AgentRunResult


def _imported_modules(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_agent_run_runtime_exposes_run_agent_once() -> None:
    assert agent_run_runtime.run_agent_once.__module__ == (
        "opensquilla.cli.agent_run_runtime"
    )
    assert inspect.iscoroutinefunction(agent_run_runtime.run_agent_once)


def test_agent_run_runtime_uses_agent_outputs_result_model() -> None:
    assert agent_run_runtime.AgentRunResult is AgentRunResult


def test_agent_run_runtime_imports_runtime_helpers_without_agent_cmd_dependency() -> None:
    imports = _imported_modules(agent_run_runtime)

    assert "opensquilla.cli.agent_cmd" not in imports
    assert "opensquilla.cli.agent_outputs" in imports
    assert "opensquilla.cli.agent_runtime_config" in imports
    assert "opensquilla.cli.attachments" in imports
