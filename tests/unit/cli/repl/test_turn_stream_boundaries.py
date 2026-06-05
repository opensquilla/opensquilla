from __future__ import annotations

import ast
import importlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
CHAT_CMD = PROJECT_ROOT / "src/opensquilla/cli/chat_cmd.py"
TURN_STREAM = PROJECT_ROOT / "src/opensquilla/cli/chat/turn_stream.py"
TURN_BRIDGE = PROJECT_ROOT / "src/opensquilla/cli/tui/turn_bridge.py"
TURN_STREAM_DEFAULTS = (
    PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/turn_stream_defaults.py"
)
GATEWAY_SLASH_ADAPTER = (
    PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/slash_gateway.py"
)
STANDALONE_SLASH_ADAPTER = (
    PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/slash_standalone.py"
)
OPENTUI_RENDERER = "opensquilla.cli.tui.opentui.renderer"
REMOVED_TERMINAL_BRIDGE = "terminal" + "_bridge"


def _imports_name_from_module(path: Path, module: str, name: str) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == module and any(alias.name == name for alias in node.names):
            return True
    return False


def _imports_from_module(path: Path, module: str) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            return True
        if isinstance(node, ast.Import) and any(alias.name == module for alias in node.names):
            return True
    return False


def _imports_module(path: Path, module: str) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name == module for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == module:
            return True
    return False


def _imports_module_from_package(path: Path, package: str, module_name: str) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == package and any(alias.name == module_name for alias in node.names):
                return True
            continue
        if isinstance(node, ast.Import):
            module = f"{package}.{module_name}"
            if any(alias.name == module for alias in node.names):
                return True
    return False


def _defined_function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _module_aliases(path: Path, module_alias: str) -> dict[str, str]:
    tree = ast.parse(path.read_text())
    aliases: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == module_alias
        ):
            aliases[node.targets[0].id] = value.attr
    return aliases


def test_chat_cmd_does_not_import_legacy_renderer_or_approval_handler() -> None:
    assert not _imports_name_from_module(
        CHAT_CMD,
        "opensquilla.cli.repl.stream",
        "StreamingRenderer",
    )
    assert not _imports_name_from_module(
        CHAT_CMD,
        "opensquilla.cli.repl.approval",
        "maybe_handle_approval",
    )


def test_chat_cmd_does_not_import_raw_slash_adapters_or_context() -> None:
    assert not _imports_module_from_package(
        CHAT_CMD,
        "opensquilla.cli.repl",
        "slash_adapter",
    )
    assert not _imports_module_from_package(
        CHAT_CMD,
        "opensquilla.cli.repl",
        "standalone_slash_adapter",
    )
    assert not _imports_from_module(
        CHAT_CMD,
        "opensquilla.cli.repl.slash_adapter",
    )


def test_chat_cmd_does_not_import_raw_runtime_or_removed_bridges() -> None:
    assert not _imports_module_from_package(
        CHAT_CMD,
        "opensquilla.cli.repl",
        "gateway_runtime",
    )
    assert not _imports_module_from_package(
        CHAT_CMD,
        "opensquilla.cli.repl",
        "standalone_runtime",
    )
    assert not _imports_module_from_package(
        CHAT_CMD,
        "opensquilla.cli.repl",
        REMOVED_TERMINAL_BRIDGE,
    )


def test_chat_cmd_does_not_import_raw_input_assets() -> None:
    assert not _imports_module_from_package(
        CHAT_CMD,
        "opensquilla.cli.repl",
        "input_assets",
    )
    assert not _imports_from_module(
        CHAT_CMD,
        "opensquilla.cli.repl.input_assets",
    )


def test_chat_cmd_does_not_import_backend_helper_bridges() -> None:
    for module_name in ("input_bridge", "slash_bridge", "turn_bridge"):
        assert not _imports_module_from_package(
            CHAT_CMD,
            "opensquilla.cli.repl",
            module_name,
        )
        assert not _imports_from_module(
            CHAT_CMD,
            f"opensquilla.cli.repl.{module_name}",
        )


def test_chat_cmd_private_compat_surface_is_dynamic_legacy_exports() -> None:
    tree = ast.parse(CHAT_CMD.read_text())
    assigned_names = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert _defined_function_names(CHAT_CMD) == {"__dir__", "__getattr__", "run_chat"}
    assert not any(
        name.startswith("_") and not name.startswith("__")
        for name in assigned_names
    )
    assert not _imports_module_from_package(
        CHAT_CMD,
        "opensquilla.cli.repl",
        "chat_compat",
    )
    assert not _imports_from_module(
        CHAT_CMD,
        "opensquilla.cli.repl.chat_compat",
    )


def test_chat_cmd_uses_typed_launch_request_instead_of_private_runner_names() -> None:
    source = CHAT_CMD.read_text()

    assert "_ChatCommandRequest" in source
    assert "_ChatCommandLaunchOverrides" in source
    assert "_run_chat_request" in source
    assert "legacy_overrides" not in source
    assert "_launch_bridge" not in source
    assert "_standalone_repl" not in source
    assert "_gateway_chat" not in source


def test_chat_cmd_star_import_keeps_legacy_public_names_visible() -> None:
    chat_cmd = importlib.import_module("opensquilla.cli.chat_cmd")

    assert "run_chat" in chat_cmd.__all__
    assert "GATEWAY_SLASH_HANDLER_WORDS" in chat_cmd.__all__
    assert "TurnResult" in chat_cmd.__all__
    assert "_file_prompt_and_attachments" not in chat_cmd.__all__
    assert "GATEWAY_SLASH_HANDLER_WORDS" in dir(chat_cmd)
    assert "_file_prompt_and_attachments" in dir(chat_cmd)

    namespace: dict[str, object] = {}
    exec("from opensquilla.cli.chat_cmd import *", namespace)
    assert "run_chat" in namespace
    assert "GATEWAY_SLASH_HANDLER_WORDS" in namespace
    assert "_file_prompt_and_attachments" not in namespace


def test_chat_cmd_only_defines_typer_entrypoint_and_export_hooks() -> None:
    assert _defined_function_names(CHAT_CMD) == {"__dir__", "__getattr__", "run_chat"}


def test_chat_cmd_does_not_import_launch_presentation_details() -> None:
    assert not _imports_module(CHAT_CMD, "asyncio")
    assert not _imports_module(CHAT_CMD, "os")
    assert not _imports_module(CHAT_CMD, "sys")
    assert not _imports_name_from_module(CHAT_CMD, "rich.panel", "Panel")
    assert not _imports_name_from_module(CHAT_CMD, "opensquilla.cli.ui", "ACCENT")


def test_chat_cmd_does_not_import_cli_presentation_defaults() -> None:
    assert not _imports_from_module(CHAT_CMD, "opensquilla.cli.ui")


def test_chat_cmd_does_not_import_raw_turn_stream_facade() -> None:
    assert not _imports_module_from_package(
        CHAT_CMD,
        "opensquilla.cli.repl",
        "turn_stream",
    )
    assert not _imports_from_module(
        CHAT_CMD,
        "opensquilla.cli.repl.turn_stream",
    )
    assert not _imports_from_module(
        CHAT_CMD,
        "opensquilla.cli.repl.stream",
    )


def test_turn_stream_does_not_import_raw_input_assets() -> None:
    assert not _imports_module_from_package(
        TURN_STREAM,
        "opensquilla.cli.repl",
        "input_assets",
    )
    assert not _imports_from_module(
        TURN_STREAM,
        "opensquilla.cli.repl.input_assets",
    )


def test_turn_stream_does_not_import_frontend_default_dependencies() -> None:
    assert not _imports_module_from_package(
        TURN_STREAM,
        "opensquilla.cli.repl",
        "input_bridge",
    )
    assert not _imports_from_module(
        TURN_STREAM,
        "opensquilla.cli.repl.approval",
    )
    assert not _imports_name_from_module(
        TURN_STREAM,
        "opensquilla.cli.repl.stream",
        "StreamingRenderer",
    )
    assert not _imports_from_module(
        TURN_STREAM,
        f"opensquilla.cli.repl.{REMOVED_TERMINAL_BRIDGE}",
    )
    assert not _imports_from_module(
        TURN_STREAM,
        "opensquilla.cli.ui",
    )
    assert not _imports_from_module(
        TURN_STREAM,
        "opensquilla.cli.repl.slash_adapter",
    )
    assert not _imports_from_module(
        TURN_STREAM,
        "opensquilla.cli.tui.contracts",
    )
    assert not _imports_from_module(
        TURN_STREAM,
        "opensquilla.engine.commands",
    )


def test_turn_bridge_does_not_import_concrete_streaming_renderer() -> None:
    assert not _imports_name_from_module(
        TURN_BRIDGE,
        "opensquilla.cli.repl.stream",
        "StreamingRenderer",
    )


def test_turn_stream_defaults_uses_opentui_renderer_default() -> None:
    assert _imports_name_from_module(
        TURN_STREAM_DEFAULTS,
        OPENTUI_RENDERER,
        "OpenTuiStreamRenderer",
    )
    assert not _imports_name_from_module(
        TURN_STREAM_DEFAULTS,
        "opensquilla.cli.repl.approval",
        "maybe_handle_approval",
    )


def test_turn_bridge_delegates_tui_approval_defaults() -> None:
    assert _imports_from_module(
        TURN_BRIDGE,
        "opensquilla.cli.tui.adapters.turn_stream_defaults",
    )
    assert not _imports_name_from_module(
        TURN_BRIDGE,
        OPENTUI_RENDERER,
        "OpenTuiStreamRenderer",
    )


def test_slash_adapters_do_not_import_raw_input_assets() -> None:
    for path in (GATEWAY_SLASH_ADAPTER, STANDALONE_SLASH_ADAPTER):
        assert not _imports_module_from_package(
            path,
            "opensquilla.cli.repl",
            "input_assets",
        )
        assert not _imports_from_module(
            path,
            "opensquilla.cli.repl.input_assets",
        )
