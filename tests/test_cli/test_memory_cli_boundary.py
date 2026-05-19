from __future__ import annotations

import ast
from pathlib import Path

import pytest

MAIN_PATH = Path("src/opensquilla/cli/main.py")
WORKFLOWS_PATH = Path("src/opensquilla/cli/memory_workflows.py")
PRESENTERS_PATH = Path("src/opensquilla/cli/memory_presenters.py")

MEMORY_COMMANDS = {
    "memory_status_cmd": "show_memory_status_for_cli",
    "memory_list_cmd": "list_memory_sources_for_cli",
    "memory_search_cmd": "search_memory_sources_for_cli",
    "memory_show_cmd": "show_memory_source_for_cli",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    pytest.fail(f"missing function {name}")


def _imported_names(tree: ast.Module, module: str) -> set[str]:
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
    }


def _called_names(tree: ast.AST) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def _identifiers(tree: ast.AST) -> set[str]:
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _string_literals(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_memory_commands_delegate_to_workflow_boundary() -> None:
    main_tree = _tree(MAIN_PATH)

    assert _imported_names(main_tree, "opensquilla.cli.memory_workflows") == set(
        MEMORY_COMMANDS.values()
    )

    for command_name, workflow_name in MEMORY_COMMANDS.items():
        command = _function(main_tree, command_name)
        assert workflow_name in _called_names(command)
        assert not (
            _identifiers(command)
            & {"run_gateway_sync", "print_json", "console", "Table", "client"}
        )


def test_memory_workflow_owns_rpc_methods_and_payload_keys() -> None:
    workflow_tree = _tree(WORKFLOWS_PATH)

    assert _imported_names(workflow_tree, "opensquilla.cli.gateway_rpc") == {
        "run_gateway_sync"
    }
    assert {
        "emit_memory_status",
        "emit_memory_sources",
        "emit_memory_search_results",
        "emit_memory_source_content",
    } <= _imported_names(workflow_tree, "opensquilla.cli.memory_presenters")

    literals = _string_literals(workflow_tree)
    assert {
        "doctor.memory.status",
        "memory.list",
        "memory.search",
        "memory.show",
        "agentId",
        "query",
        "limit",
        "path",
        "fromLine",
        "lines",
    } <= literals


def test_memory_presenter_owns_json_table_and_truncated_rendering() -> None:
    presenter_tree = _tree(PRESENTERS_PATH)

    assert _imported_names(presenter_tree, "opensquilla.cli.output") == {"print_json"}
    assert _imported_names(presenter_tree, "rich.table") == {"Table"}

    literals = _string_literals(presenter_tree)
    assert {
        "Memory status \u2014 agent=",
        "Memory sources - agent=",
        "Memory search - agent=",
        "Backend",
        "Status",
        "Entries",
        "Size bytes",
        "Error",
        "Path",
        "Lines",
        "Modified",
        "Score",
        "Snippet",
        "[dim]... truncated[/dim]",
    } <= literals
