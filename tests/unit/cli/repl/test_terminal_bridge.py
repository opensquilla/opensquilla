from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
TERMINAL_CHAT_ADAPTER = "opensquilla.cli.repl.terminal_chat_adapter"
TERMINAL_CHAT_ADAPTER_PACKAGE = "opensquilla.cli.repl"
TUI_TERMINAL_BRIDGE = "opensquilla.cli.tui.adapters.terminal_bridge"
TUI_TERMINAL_CHAT_ADAPTER = "opensquilla.cli.tui.adapters.terminal_chat_adapter"


def _imports_terminal_chat_adapter(path: Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == TERMINAL_CHAT_ADAPTER for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == TERMINAL_CHAT_ADAPTER:
                return True
            if node.module == TERMINAL_CHAT_ADAPTER_PACKAGE and any(
                alias.name == "terminal_chat_adapter" for alias in node.names
            ):
                return True
    return False


def test_chat_cmd_does_not_import_terminal_adapter_directly() -> None:
    assert not _imports_terminal_chat_adapter(
        PROJECT_ROOT / "src/opensquilla/cli/chat_cmd.py"
    )


def test_repl_terminal_modules_do_not_own_terminal_chat_adapter() -> None:
    repl_dir = PROJECT_ROOT / "src/opensquilla/cli/repl"
    offenders = sorted(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in repl_dir.glob("*.py")
        if _imports_terminal_chat_adapter(path)
    )

    assert offenders == []


def test_runtime_bridge_imports_tui_terminal_bridge() -> None:
    runtime_bridge = PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/runtime_bridge.py"

    assert _imports_from_module(runtime_bridge, TUI_TERMINAL_BRIDGE)
    assert not _imports_terminal_chat_adapter(runtime_bridge)


def test_tui_terminal_bridge_imports_tui_terminal_chat_adapter() -> None:
    terminal_bridge = PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/terminal_bridge.py"

    assert _imports_from_module(terminal_bridge, TUI_TERMINAL_CHAT_ADAPTER)


def _imports_from_module(path: Path, module_name: str) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == module_name:
                return True
    return False
