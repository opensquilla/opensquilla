from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRON_CMD = ROOT / "src/opensquilla/cli/cron_cmd.py"
CRON_WORKFLOWS = ROOT / "src/opensquilla/cli/cron_workflows.py"
CRON_PRESENTERS = ROOT / "src/opensquilla/cli/cron_presenters.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imported_names(tree: ast.Module, module: str) -> set[str]:
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
    }


def _imported_modules(tree: ast.Module) -> set[str]:
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_cron_cli_has_workflow_and_presenter_boundaries() -> None:
    assert CRON_WORKFLOWS.exists()
    assert CRON_PRESENTERS.exists()

    cmd_tree = _tree(CRON_CMD)
    workflow_tree = _tree(CRON_WORKFLOWS)
    presenter_tree = _tree(CRON_PRESENTERS)

    assert _imported_names(
        cmd_tree,
        "opensquilla.cli.cron_workflows",
    ) == {
        "add_cron_job_for_cli",
        "list_cron_jobs_for_cli",
        "list_cron_runs_for_cli",
        "remove_cron_job_for_cli",
        "run_cron_job_for_cli",
        "show_cron_job_for_cli",
        "update_cron_job_for_cli",
    }
    assert "opensquilla.cli.gateway_rpc" not in _imported_modules(cmd_tree)
    assert "opensquilla.cli.output" not in _imported_modules(cmd_tree)
    assert "opensquilla.cli.ui" not in _imported_modules(cmd_tree)
    assert "rich.table" not in _imported_modules(cmd_tree)
    assert _imported_names(
        workflow_tree,
        "opensquilla.cli.gateway_rpc",
    ) == {"confirm_or_exit", "run_gateway_sync"}
    assert {
        "emit_cron_jobs",
        "emit_cron_runs",
        "emit_cron_success",
    } <= _imported_names(workflow_tree, "opensquilla.cli.cron_presenters")
    assert _imported_names(presenter_tree, "opensquilla.cli.output") == {"print_json"}


def test_cron_commands_delegate_without_inline_rpc_or_rendering() -> None:
    cmd_tree = _tree(CRON_CMD)
    command_to_workflow = {
        "cron_list": "list_cron_jobs_for_cli",
        "cron_status": "show_cron_job_for_cli",
        "cron_add": "add_cron_job_for_cli",
        "cron_update": "update_cron_job_for_cli",
        "cron_remove": "remove_cron_job_for_cli",
        "cron_run": "run_cron_job_for_cli",
        "cron_runs": "list_cron_runs_for_cli",
    }
    blocked_identifiers = {
        "run_gateway_sync",
        "print_json",
        "confirm_or_exit",
        "client",
        "console",
        "Table",
    }

    for command_name, workflow_name in command_to_workflow.items():
        command = _function(cmd_tree, command_name)
        identifiers = {node.id for node in ast.walk(command) if isinstance(node, ast.Name)}
        assert workflow_name in identifiers
        assert not any(isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(command))
        assert not (identifiers & blocked_identifiers)
