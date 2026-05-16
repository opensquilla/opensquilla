from __future__ import annotations

import ast
from pathlib import Path

import pytest

from opensquilla.agents.workspace_files import (
    list_workspace_agent_files,
    read_workspace_agent_file,
    validate_workspace_file_name,
    workspace_file_entry,
    workspace_file_root_for_config,
    write_workspace_agent_file,
)
from opensquilla.gateway import rpc_agents


def test_agent_workspace_file_helpers_round_trip_content(tmp_path) -> None:
    result = write_workspace_agent_file(tmp_path, "MEMORY.md", "hello")

    assert result == {"name": "MEMORY.md", "path": "MEMORY.md", "size": 5}
    assert read_workspace_agent_file(tmp_path, "MEMORY.md") == ("MEMORY.md", "hello")
    assert workspace_file_entry(tmp_path, "MEMORY.md") == {
        "name": "MEMORY.md",
        "path": "MEMORY.md",
        "exists": True,
        "missing": False,
        "status": "present",
        "size": 5,
    }
    assert any(row["name"] == "MEMORY.md" for row in list_workspace_agent_files(tmp_path))


def test_agent_workspace_file_helpers_reject_unsafe_names(tmp_path) -> None:
    with pytest.raises(ValueError, match="path separators"):
        validate_workspace_file_name("../MEMORY.md")

    with pytest.raises(ValueError, match="Unsupported workspace agent file"):
        validate_workspace_file_name("notes.txt")

    (tmp_path / "MEMORY.md").symlink_to(tmp_path / "target.md")
    assert workspace_file_entry(tmp_path, "MEMORY.md")["unsafeReason"] == "symlink"
    with pytest.raises(ValueError, match="must not be a symlink"):
        read_workspace_agent_file(tmp_path, "MEMORY.md")


def test_workspace_file_root_for_config_honors_agent_workspace(tmp_path) -> None:
    cfg = type(
        "Config",
        (),
        {
            "workspace_dir": str(tmp_path / "workspace"),
            "agents": [{"id": "ops", "enabled": True, "workspace": str(tmp_path / "ops")}],
        },
    )()

    assert workspace_file_root_for_config(cfg, "main") == tmp_path / "workspace"
    assert workspace_file_root_for_config(cfg, "ops") == tmp_path / "ops"
    assert (
        workspace_file_root_for_config(type("NoWorkspace", (), {"workspace_dir": None})(), "ops")
        is None
    )


def test_rpc_agents_does_not_own_workspace_file_helpers() -> None:
    source = Path(rpc_agents.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    top_level_functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }

    assert "_workspace_file_entry" not in top_level_functions
    assert "_read_workspace_agent_file" not in top_level_functions
    assert "_write_workspace_agent_file" not in top_level_functions
    assert "opensquilla.identity.bootstrap" not in imported_modules
