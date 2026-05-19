from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.cli import chat_gateway_repl, chat_standalone_repl

ROOT = Path(__file__).resolve().parents[2]
CHAT_CMD = ROOT / "src" / "opensquilla" / "cli" / "chat_cmd.py"


def _function(name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(CHAT_CMD.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def test_chat_cmd_gateway_repl_is_thin_compatibility_wrapper() -> None:
    assert hasattr(chat_gateway_repl, "run_gateway_chat")
    node = _function("_gateway_chat")

    assert "run_gateway_chat" in _called_names(node)
    assert not any(isinstance(child, ast.While) for child in ast.walk(node))
    assert not any(isinstance(child, ast.Try) for child in ast.walk(node))


def test_chat_cmd_standalone_repl_is_thin_compatibility_wrapper() -> None:
    assert hasattr(chat_standalone_repl, "run_standalone_repl")
    node = _function("_standalone_repl")

    assert "run_standalone_repl" in _called_names(node)
    assert not any(isinstance(child, ast.While) for child in ast.walk(node))
    assert not any(isinstance(child, ast.Try) for child in ast.walk(node))
