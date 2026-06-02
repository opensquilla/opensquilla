from __future__ import annotations

import ast
import importlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC_ROOT = PROJECT_ROOT / "src/opensquilla/cli"
TUI_ROOT = SRC_ROOT / "tui"
REMOVED_TEXT_BACKEND = "text" + "ual"
REMOVED_TERMINAL = "terminal"
PROMPT_TOOLKIT = "prompt" + "_toolkit"


REMOVED_FRONTEND_PATHS = (
    TUI_ROOT / "terminal",
    TUI_ROOT / REMOVED_TEXT_BACKEND,
    TUI_ROOT / "app.py",
    TUI_ROOT / "prompt.py",
    TUI_ROOT / "paste.py",
    TUI_ROOT / "stream.py",
    TUI_ROOT / "signal_handlers.py",
    TUI_ROOT / f"{REMOVED_TERMINAL}_bridge.py",
    TUI_ROOT / f"{REMOVED_TERMINAL}_chat_adapter.py",
    TUI_ROOT / f"{REMOVED_TERMINAL}_renderer.py",
    TUI_ROOT / f"{REMOVED_TERMINAL}_surface.py",
    TUI_ROOT / f"adapters/{REMOVED_TERMINAL}_bridge.py",
    TUI_ROOT / f"adapters/{REMOVED_TERMINAL}_chat_adapter.py",
    TUI_ROOT / f"adapters/{REMOVED_TEXT_BACKEND}_bridge.py",
    TUI_ROOT / f"renderers/{REMOVED_TEXT_BACKEND}_backend.py",
    SRC_ROOT / f"repl/{REMOVED_TERMINAL}_bridge.py",
    SRC_ROOT / f"repl/{REMOVED_TERMINAL}_chat_adapter.py",
    SRC_ROOT / f"repl/{REMOVED_TERMINAL}_renderer.py",
    SRC_ROOT / f"repl/{REMOVED_TERMINAL}_surface.py",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
            continue
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _live_tui_python_paths() -> list[Path]:
    return [
        path
        for path in TUI_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def test_removed_frontend_files_are_absent() -> None:
    assert [path for path in REMOVED_FRONTEND_PATHS if path.exists()] == []


def test_live_tui_modules_do_not_import_removed_frontends() -> None:
    forbidden_prefixes = (
        f"opensquilla.cli.tui.{REMOVED_TERMINAL}",
        f"opensquilla.cli.tui.{REMOVED_TEXT_BACKEND}",
        f"opensquilla.cli.tui.adapters.{REMOVED_TERMINAL}_bridge",
        f"opensquilla.cli.tui.adapters.{REMOVED_TERMINAL}_chat_adapter",
        f"opensquilla.cli.tui.adapters.{REMOVED_TEXT_BACKEND}_bridge",
        f"opensquilla.cli.repl.{REMOVED_TERMINAL}_bridge",
        f"opensquilla.cli.repl.{REMOVED_TERMINAL}_chat_adapter",
        f"opensquilla.cli.repl.{REMOVED_TERMINAL}_renderer",
        f"opensquilla.cli.repl.{REMOVED_TERMINAL}_surface",
        PROMPT_TOOLKIT,
        REMOVED_TEXT_BACKEND,
    )

    offenders: dict[str, list[str]] = {}
    for path in _live_tui_python_paths():
        imports = sorted(
            module
            for module in _imported_modules(path)
            if module == REMOVED_TEXT_BACKEND
            or any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in forbidden_prefixes
            )
        )
        if imports:
            offenders[str(path.relative_to(PROJECT_ROOT))] = imports

    assert offenders == {}


def test_shared_tui_contracts_remain_importable() -> None:
    modules = (
        "opensquilla.cli.tui.backend.contracts",
        "opensquilla.cli.tui.backend.runtime",
        "opensquilla.cli.tui.backend.streaming",
        "opensquilla.cli.tui.backend.transcript",
        "opensquilla.cli.tui.backend.render_summary",
        "opensquilla.cli.tui.plugins",
        "opensquilla.cli.tui.plugins.router_hud",
        "opensquilla.cli.tui.adapters.runtime_helpers",
        "opensquilla.cli.tui.adapters.runtime_bridge",
        "opensquilla.cli.tui.opentui.runtime",
        "opensquilla.cli.tui.opentui.renderer",
    )

    for module in modules:
        assert importlib.import_module(module)


def test_tui_package_exports_only_neutral_and_opentui_surfaces() -> None:
    import opensquilla.cli.tui as tui

    exported = set(tui.__all__)

    assert "backend" in exported
    assert "opentui" in exported
    assert "turn_bridge" in exported
    assert "terminal" not in exported
    assert REMOVED_TEXT_BACKEND not in exported
    assert not any(name.startswith("terminal_") for name in exported)
