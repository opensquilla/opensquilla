from __future__ import annotations

import ast
from pathlib import Path

import pytest

from opensquilla.commands import (
    DEFAULT_REGISTRY,
    Surface,
    command_def_rpc_payload,
    commands_for_surface_rpc_payload,
)

ROOT = Path(__file__).resolve().parents[1]
RPC_COMMANDS = ROOT / "src/opensquilla/gateway/rpc_commands.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_command_def_rpc_payload_omits_callable_rpc_params() -> None:
    command = DEFAULT_REGISTRY.find("/new", surface=Surface.WEB)

    assert command is not None
    payload = command_def_rpc_payload(command)

    assert payload == {
        "name": "/new",
        "usage": "/new [title]",
        "description": "Start a new chat session.",
        "aliases": [],
        "rpc_method": "sessions.reset",
    }
    assert "rpc_params" not in payload


def test_commands_for_surface_rpc_payload_preserves_wire_shape() -> None:
    payload = commands_for_surface_rpc_payload({"surface": "WEB"})

    assert payload["surface"] == "web"
    assert [command["name"] for command in payload["commands"]] == [
        "/compact",
        "/new",
        "/reset",
    ]


def test_commands_for_surface_rpc_payload_validates_request_shape() -> None:
    with pytest.raises(ValueError, match="params must be an object"):
        commands_for_surface_rpc_payload("bad-params")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="params.surface must be a string"):
        commands_for_surface_rpc_payload({"surface": 123})
    with pytest.raises(ValueError, match="unknown surface"):
        commands_for_surface_rpc_payload({"surface": "desktop"})


def test_gateway_delegates_commands_rpc_payload_to_command_boundary() -> None:
    imports = _imports_from(RPC_COMMANDS)
    top_level_functions = _top_level_functions(RPC_COMMANDS)

    assert ("opensquilla.commands", "commands_for_surface_rpc_payload") in imports
    assert ("opensquilla.commands", "DEFAULT_REGISTRY") not in imports
    assert ("opensquilla.commands", "CommandDef") not in imports
    assert ("opensquilla.commands", "Surface") not in imports
    assert "_serialize" not in top_level_functions
