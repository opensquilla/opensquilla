from __future__ import annotations

import ast
import importlib
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from opensquilla.cli.tui.contracts import (
    TuiInputKind,
    TuiOutputHandle,
    TuiRenderer,
    TuiRuntimeConfig,
    TuiRuntimeHooks,
    TuiSurface,
)
from opensquilla.cli.tui.events import TuiEvent, TuiEventKind

PROJECT_ROOT = Path(__file__).resolve().parents[4]
TUI_BACKEND_MODULES = {
    "__init__.py",
    "contracts.py",
    "events.py",
    "output_binding.py",
    "runtime.py",
    "slash_policy.py",
    "state.py",
}
TUI_BACKEND_PACKAGE_MODULES = {
    "__init__.py",
    "contracts.py",
    "events.py",
    "output_binding.py",
    "runtime.py",
    "state.py",
}
TUI_TERMINAL_ADAPTER_MODULES = {
    "approval_adapter.py",
    "app.py",
    "chat_compat.py",
    "chat_cmd_exports.py",
    "commands.py",
    "input_bridge.py",
    "launch_bridge.py",
    "paste.py",
    "prompt.py",
    "runtime_bridge.py",
    "signal_handlers.py",
    "slash_adapter.py",
    "slash_bridge.py",
    "stream.py",
    "standalone_runtime.py",
    "terminal_bridge.py",
    "terminal_chat_adapter.py",
    "terminal_renderer.py",
    "terminal_surface.py",
    "turn_bridge.py",
    "turn_stream_defaults.py",
    "standalone_slash_adapter.py",
}
CHAT_CORE_MODULES = {
    "__init__.py",
    "commands.py",
    "entrypoint.py",
    "frontend.py",
    "gateway_runtime.py",
    "input_assets.py",
    "launch.py",
    "output.py",
    "session_context.py",
    "session_state.py",
    "turn.py",
    "turn_stream.py",
}


def _imports_tui_forbidden_runtime_dependency(path: Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "prompt_toolkit"
                or alias.name.startswith("prompt_toolkit.")
                or alias.name == "opensquilla.cli.repl"
                or alias.name.startswith("opensquilla.cli.repl.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if (
                module == "prompt_toolkit"
                or module.startswith("prompt_toolkit.")
                or module == "opensquilla.cli.repl"
                or module.startswith("opensquilla.cli.repl.")
            ):
                return True
    return False


def _imports_chat_core_forbidden_dependency(path: Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "prompt_toolkit"
                or alias.name.startswith("prompt_toolkit.")
                or alias.name == "opensquilla.cli.repl"
                or alias.name.startswith("opensquilla.cli.repl.")
                or alias.name == "opensquilla.cli.tui"
                or alias.name.startswith("opensquilla.cli.tui.")
                or alias.name == "opensquilla.engine.commands"
                or alias.name.startswith("opensquilla.engine.commands.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if (
                module == "prompt_toolkit"
                or module.startswith("prompt_toolkit.")
                or module == "opensquilla.cli.repl"
                or module.startswith("opensquilla.cli.repl.")
                or module == "opensquilla.cli.tui"
                or module.startswith("opensquilla.cli.tui.")
                or module == "opensquilla.engine.commands"
                or module.startswith("opensquilla.engine.commands.")
            ):
                return True
    return False


def test_chat_core_contains_shared_session_and_turn_modules() -> None:
    chat_dir = PROJECT_ROOT / "src/opensquilla/cli/chat"
    modules = sorted(path.name for path in chat_dir.glob("*.py"))

    assert modules == sorted(CHAT_CORE_MODULES)


def test_chat_core_modules_do_not_import_repl_tui_or_prompt_toolkit() -> None:
    chat_dir = PROJECT_ROOT / "src/opensquilla/cli/chat"
    offenders = sorted(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (chat_dir / name for name in CHAT_CORE_MODULES)
        if path.exists() and _imports_chat_core_forbidden_dependency(path)
    )

    assert offenders == []


def test_tui_package_contains_backend_and_terminal_adapter_modules() -> None:
    tui_dir = PROJECT_ROOT / "src/opensquilla/cli/tui"
    modules = sorted(path.name for path in tui_dir.glob("*.py"))

    assert modules == sorted(TUI_BACKEND_MODULES | TUI_TERMINAL_ADAPTER_MODULES)


def test_tui_backend_core_modules_do_not_import_repl_or_prompt_toolkit() -> None:
    tui_dir = PROJECT_ROOT / "src/opensquilla/cli/tui"
    offenders = sorted(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (tui_dir / name for name in TUI_BACKEND_MODULES)
        if _imports_tui_forbidden_runtime_dependency(path)
    )

    assert offenders == []


def test_tui_backend_package_contains_only_backend_modules() -> None:
    backend_dir = PROJECT_ROOT / "src/opensquilla/cli/tui/backend"
    modules = sorted(path.name for path in backend_dir.glob("*.py"))

    assert modules == sorted(TUI_BACKEND_PACKAGE_MODULES)


def test_tui_backend_package_does_not_import_terminal_or_chat_adapters() -> None:
    backend_dir = PROJECT_ROOT / "src/opensquilla/cli/tui/backend"
    forbidden_modules = {
        "opensquilla.cli.ui",
        "opensquilla.engine.commands",
        "opensquilla.cli.tui.app",
        "opensquilla.cli.tui.prompt",
        "opensquilla.cli.tui.approval_adapter",
        "opensquilla.cli.tui.runtime_bridge",
        "opensquilla.cli.tui.slash_adapter",
        "opensquilla.cli.tui.slash_bridge",
        "opensquilla.cli.tui.standalone_runtime",
        "opensquilla.cli.tui.standalone_slash_adapter",
        "opensquilla.cli.tui.terminal_bridge",
        "opensquilla.cli.tui.terminal_chat_adapter",
        "opensquilla.cli.tui.terminal_renderer",
        "opensquilla.cli.tui.terminal_surface",
        "opensquilla.cli.tui.turn_bridge",
        "opensquilla.cli.tui.turn_stream_defaults",
    }
    offenders = sorted(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in backend_dir.glob("*.py")
        if _imports_tui_forbidden_runtime_dependency(path)
        or _imports_from_package_prefix(path, "opensquilla.cli.chat")
        or any(_imports_from_module(path, module) for module in forbidden_modules)
    )

    assert offenders == []


def test_terminal_package_owns_prompt_toolkit_and_rich_terminal_presentation() -> None:
    terminal_dir = PROJECT_ROOT / "src/opensquilla/cli/tui/terminal"

    assert (terminal_dir / "app.py").exists()
    assert (terminal_dir / "prompt.py").exists()
    assert (terminal_dir / "renderer.py").exists()
    assert (terminal_dir / "approval.py").exists()


def test_adapter_package_owns_chat_runtime_composition() -> None:
    adapter_dir = PROJECT_ROOT / "src/opensquilla/cli/tui/adapters"

    assert (adapter_dir / "runtime_bridge.py").exists()
    assert (adapter_dir / "launch_bridge.py").exists()
    assert (adapter_dir / "turn_stream_defaults.py").exists()


def test_repl_adapter_modules_are_legacy_aliases_to_tui_adapters() -> None:
    for repl_name, tui_name in (
        ("approval", "approval_adapter"),
        ("app", "app"),
        ("chat_compat", "chat_compat"),
        ("chat_cmd_legacy_exports", "chat_cmd_exports"),
        ("commands", "commands"),
        ("input_bridge", "input_bridge"),
        ("launch_bridge", "launch_bridge"),
        ("paste", "paste"),
        ("prompt", "prompt"),
        ("runtime_bridge", "runtime_bridge"),
        ("signal_handlers", "signal_handlers"),
        ("slash_adapter", "slash_adapter"),
        ("slash_bridge", "slash_bridge"),
        ("slash_policy", "slash_policy"),
        ("standalone_slash_adapter", "standalone_slash_adapter"),
        ("standalone_runtime", "standalone_runtime"),
        ("stream", "stream"),
        ("terminal_chat_adapter", "terminal_chat_adapter"),
        ("terminal_bridge", "terminal_bridge"),
        ("terminal_renderer", "terminal_renderer"),
        ("terminal_surface", "terminal_surface"),
        ("turn_bridge", "turn_bridge"),
    ):
        repl_module = importlib.import_module(f"opensquilla.cli.repl.{repl_name}")
        tui_module = importlib.import_module(f"opensquilla.cli.tui.{tui_name}")

        assert repl_module is tui_module


def test_repl_input_assets_is_legacy_alias_to_chat_core() -> None:
    repl_module = importlib.import_module("opensquilla.cli.repl.input_assets")
    chat_module = importlib.import_module("opensquilla.cli.chat.input_assets")

    assert repl_module is chat_module


def test_repl_session_modules_are_legacy_aliases_to_chat_core() -> None:
    for module_name in ("session_context", "session_state"):
        repl_module = importlib.import_module(f"opensquilla.cli.repl.{module_name}")
        chat_module = importlib.import_module(f"opensquilla.cli.chat.{module_name}")

        assert repl_module is chat_module


def test_repl_stream_reexports_shared_turn_data_models() -> None:
    repl_stream = importlib.import_module("opensquilla.cli.repl.stream")
    chat_turn = importlib.import_module("opensquilla.cli.chat.turn")

    for name in ("TurnResult", "UsageCounter", "UsageSummary"):
        assert getattr(repl_stream, name) is getattr(chat_turn, name)


def test_repl_turn_stream_is_legacy_alias_to_chat_core() -> None:
    repl_module = importlib.import_module("opensquilla.cli.repl.turn_stream")
    chat_module = importlib.import_module("opensquilla.cli.chat.turn_stream")

    assert repl_module is chat_module


def test_repl_gateway_runtime_is_legacy_alias_to_chat_core() -> None:
    repl_module = importlib.import_module("opensquilla.cli.repl.gateway_runtime")
    chat_module = importlib.import_module("opensquilla.cli.chat.gateway_runtime")

    assert repl_module is chat_module


def test_terminal_chat_adapter_uses_tui_slash_policy() -> None:
    adapter_path = (
        PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/terminal_chat_adapter.py"
    )

    assert _imports_from_module(
        adapter_path,
        "opensquilla.cli.tui.adapters.slash_policy",
    )
    assert not _imports_from_module(
        adapter_path,
        "opensquilla.cli.repl.slash_policy",
    )


def test_terminal_adapters_use_tui_prompt_and_signal_handlers() -> None:
    terminal_imports = {
        "src/opensquilla/cli/tui/terminal/approval.py": {
            "required": {"opensquilla.cli.tui.terminal.prompt"},
            "forbidden": {"opensquilla.cli.repl.prompt"},
        },
        "src/opensquilla/cli/tui/adapters/terminal_chat_adapter.py": {
            "required": {
                "opensquilla.cli.tui.terminal.prompt",
                "opensquilla.cli.tui.terminal.signals",
            },
            "forbidden": {
                "opensquilla.cli.repl.prompt",
                "opensquilla.cli.repl.signal_handlers",
            },
        },
        "src/opensquilla/cli/tui/terminal/surface.py": {
            "required": {"opensquilla.cli.tui.terminal.prompt"},
            "forbidden": {"opensquilla.cli.repl.prompt"},
        },
    }

    for relative_path, modules in terminal_imports.items():
        path = PROJECT_ROOT / relative_path
        for module_name in modules["required"]:
            assert _imports_from_module(path, module_name), (
                f"{relative_path} must import terminal helpers from {module_name}"
            )
        for module_name in modules["forbidden"]:
            assert not _imports_from_module(path, module_name), (
                f"{relative_path} must not import terminal helpers from {module_name}"
            )


def test_tui_stream_uses_tui_prompt_toolbar_context() -> None:
    stream_path = PROJECT_ROOT / "src/opensquilla/cli/tui/terminal/stream.py"

    assert stream_path.exists()
    assert _imports_from_module(stream_path, "opensquilla.cli.tui.terminal.prompt")
    assert not _imports_from_module(stream_path, "opensquilla.cli.repl.prompt")


def test_import_source_parser_reads_utf8_source(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "sample.py"
    source_path.write_text(
        "from opensquilla.cli.tui.terminal import prompt\n",
        encoding="utf-8",
    )
    original_read_text = Path.read_text
    encodings: list[str | None] = []

    def read_text(self: Path, *args, **kwargs) -> str:
        encodings.append(kwargs.get("encoding"))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    assert _imports_from_module(source_path, "opensquilla.cli.tui.terminal")
    assert encodings == ["utf-8"]


def test_tui_prompt_uses_tui_chat_application_driver() -> None:
    prompt_path = PROJECT_ROOT / "src/opensquilla/cli/tui/terminal/prompt.py"

    assert _imports_from_module(prompt_path, "opensquilla.cli.tui.terminal.app")
    assert not _imports_from_module(prompt_path, "opensquilla.cli.repl.app")


def test_tui_terminal_renderer_uses_tui_stream_renderer() -> None:
    renderer_path = PROJECT_ROOT / "src/opensquilla/cli/tui/terminal/renderer.py"

    assert _imports_from_module(renderer_path, "opensquilla.cli.tui.terminal.stream")
    assert not _imports_from_module(renderer_path, "opensquilla.cli.repl.stream")


def test_tui_turn_bridge_uses_chat_turn_stream_core() -> None:
    bridge_path = PROJECT_ROOT / "src/opensquilla/cli/tui/turn_bridge.py"

    assert _imports_name_from_package(
        bridge_path,
        "opensquilla.cli.chat",
        "turn_stream",
    )
    assert not _imports_name_from_package(
        bridge_path,
        "opensquilla.cli.repl",
        "turn_stream",
    )


def test_tui_turn_stream_defaults_owns_terminal_turn_dependencies() -> None:
    defaults_path = (
        PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/turn_stream_defaults.py"
    )

    assert _imports_name_from_module(
        defaults_path,
        "opensquilla.cli.tui.terminal.renderer",
        "TerminalRenderer",
    )
    assert _imports_name_from_module(
        defaults_path,
        "opensquilla.cli.tui.terminal.approval",
        "maybe_handle_approval",
    )
    assert _imports_from_module(
        defaults_path, "opensquilla.cli.tui.adapters.input_bridge"
    )
    assert _imports_from_module(
        defaults_path, "opensquilla.cli.tui.adapters.terminal_bridge"
    )
    assert _imports_from_module(defaults_path, "opensquilla.cli.ui")


def test_tui_turn_bridge_delegates_terminal_turn_defaults() -> None:
    bridge_path = PROJECT_ROOT / "src/opensquilla/cli/tui/turn_bridge.py"

    assert _imports_from_module(
        bridge_path,
        "opensquilla.cli.tui.adapters.turn_stream_defaults",
    )
    assert not _imports_name_from_module(
        bridge_path,
        "opensquilla.cli.tui.terminal.renderer",
        "TerminalRenderer",
    )
    assert not _imports_name_from_module(
        bridge_path,
        "opensquilla.cli.tui.terminal.approval",
        "maybe_handle_approval",
    )
    assert not _imports_from_module(
        bridge_path,
        "opensquilla.cli.tui.adapters.input_bridge",
    )
    assert not _imports_from_module(
        bridge_path,
        "opensquilla.cli.tui.adapters.terminal_bridge",
    )
    assert not _imports_from_module(bridge_path, "opensquilla.cli.ui")


def test_tui_turn_bridge_import_does_not_load_terminal_turn_defaults(
    monkeypatch,
) -> None:  # noqa: ANN001
    for module_name in (
        "opensquilla.cli.tui.turn_bridge",
        "opensquilla.cli.tui.adapters.turn_stream_defaults",
        "opensquilla.cli.tui.terminal.renderer",
        "opensquilla.cli.tui.terminal.approval",
        "opensquilla.cli.tui.adapters.input_bridge",
        "opensquilla.cli.tui.adapters.terminal_bridge",
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    importlib.import_module("opensquilla.cli.tui.turn_bridge")

    assert "opensquilla.cli.tui.adapters.turn_stream_defaults" not in sys.modules
    assert "opensquilla.cli.tui.terminal.renderer" not in sys.modules
    assert "opensquilla.cli.tui.terminal.approval" not in sys.modules
    assert "opensquilla.cli.tui.adapters.input_bridge" not in sys.modules
    assert "opensquilla.cli.tui.adapters.terminal_bridge" not in sys.modules


def test_chat_gateway_runtime_has_no_terminal_presentation_dependencies() -> None:
    runtime_path = PROJECT_ROOT / "src/opensquilla/cli/chat/gateway_runtime.py"

    assert not _imports_from_module(runtime_path, "opensquilla.cli.ui")
    assert not _imports_from_module(runtime_path, "rich.panel")
    assert not _imports_from_module(runtime_path, "opensquilla.engine.commands")


def test_chat_cmd_imports_only_chat_entrypoint_not_tui_resolver() -> None:
    chat_cmd_path = PROJECT_ROOT / "src/opensquilla/cli/chat_cmd.py"

    assert _imports_from_module(chat_cmd_path, "opensquilla.cli.chat.entrypoint")
    assert _imports_name_from_module(
        chat_cmd_path,
        "opensquilla.cli.chat.launch",
        "ChatCommandRequest",
    )
    assert not _imports_from_module(
        chat_cmd_path,
        "opensquilla.cli.tui.chat_cmd_exports",
    )
    assert not _imports_from_module(
        chat_cmd_path,
        "opensquilla.cli.repl.chat_cmd_legacy_exports",
    )


def test_chat_command_request_is_owned_by_chat_core() -> None:
    chat_launch = importlib.import_module("opensquilla.cli.chat.launch")
    exports = importlib.import_module("opensquilla.cli.tui.chat_cmd_exports")

    request = chat_launch.ChatCommandRequest(
        model="openrouter/test",
        session_id="agent:main:existing",
        standalone=True,
        workspace="repo",
        workspace_strict=True,
        timeout=12.5,
    )

    assert exports.ChatCommandRequest is chat_launch.ChatCommandRequest
    assert request.model == "openrouter/test"
    assert request.session_id == "agent:main:existing"
    assert request.standalone is True
    assert request.workspace == "repo"
    assert request.workspace_strict is True
    assert request.timeout == 12.5


def test_chat_launch_contract_does_not_know_legacy_chat_cmd_private_names() -> None:
    chat_launch_path = PROJECT_ROOT / "src/opensquilla/cli/chat/launch.py"
    source = chat_launch_path.read_text()

    assert "_launch_bridge" not in source
    assert "_standalone_repl" not in source
    assert "_gateway_chat" not in source
    assert "legacy_overrides" not in source
    assert not _imports_from_module(
        chat_launch_path,
        "opensquilla.cli.tui.chat_cmd_exports",
    )


def test_tui_chat_cmd_exports_builds_typed_launch_overrides() -> None:
    chat_launch = importlib.import_module("opensquilla.cli.chat.launch")
    exports = importlib.import_module("opensquilla.cli.tui.chat_cmd_exports")

    async def standalone_runner(**_kwargs: Any) -> None:
        return None

    async def gateway_runner(**_kwargs: Any) -> None:
        return None

    def launch_chat(**_kwargs: Any) -> None:
        return None

    overrides = exports.resolve_legacy_chat_cmd_launch_overrides(
        {
            "_launch_bridge": SimpleNamespace(launch_chat=launch_chat),
            "_standalone_repl": standalone_runner,
            "_gateway_chat": gateway_runner,
        }
    )

    assert isinstance(overrides, chat_launch.ChatCommandLaunchOverrides)
    assert overrides.launch_chat is launch_chat
    assert overrides.standalone_runner is standalone_runner
    assert overrides.gateway_runner is gateway_runner


def test_tui_chat_cmd_exports_resolves_runtime_dependencies_from_tui() -> None:
    exports = importlib.import_module("opensquilla.cli.tui.chat_cmd_exports")

    assert exports.MODULE_COMPAT_EXPORTS["chat_compat"] == (
        "opensquilla.cli.tui.adapters.chat_compat"
    )
    assert exports.MODULE_EXPORTS["_chat_compat"] == (
        "opensquilla.cli.tui.adapters.chat_compat"
    )
    assert exports.MODULE_COMPAT_EXPORTS["runtime_bridge"] == (
        "opensquilla.cli.tui.adapters.runtime_bridge"
    )
    assert exports.MODULE_EXPORTS["_runtime_bridge"] == (
        "opensquilla.cli.tui.adapters.runtime_bridge"
    )


def test_tui_launch_bridge_uses_chat_core_launch_request() -> None:
    launch_bridge_path = PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/launch_bridge.py"

    assert _imports_name_from_module(
        launch_bridge_path,
        "opensquilla.cli.chat.launch",
        "ChatCommandRequest",
    )
    assert _imports_from_module(
        launch_bridge_path,
        "opensquilla.cli.tui.adapters.chat_cmd_exports",
    )


def test_runtime_bridge_uses_tui_slash_bridge() -> None:
    runtime_bridge = PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/runtime_bridge.py"

    assert _imports_name_from_package(
        runtime_bridge,
        "opensquilla.cli.tui.adapters",
        "slash_bridge",
    )
    assert not _imports_name_from_package(
        runtime_bridge,
        "opensquilla.cli.repl",
        "slash_bridge",
    )
    assert _imports_name_from_package(
        runtime_bridge,
        "opensquilla.cli.tui",
        "turn_bridge",
    )
    assert not _imports_name_from_package(
        runtime_bridge,
        "opensquilla.cli.repl",
        "turn_bridge",
    )
    assert _imports_name_from_package(
        runtime_bridge,
        "opensquilla.cli.chat",
        "gateway_runtime",
    )
    assert not _imports_name_from_package(
        runtime_bridge,
        "opensquilla.cli.repl",
        "gateway_runtime",
    )
    assert _imports_name_from_package(
        runtime_bridge,
        "opensquilla.cli.tui",
        "standalone_runtime",
    )
    assert not _imports_name_from_package(
        runtime_bridge,
        "opensquilla.cli.repl",
        "standalone_runtime",
    )


def test_tui_commands_use_chat_exit_policy() -> None:
    commands = PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/commands.py"

    assert _imports_from_module(commands, "opensquilla.cli.chat.commands")


def test_tui_slash_bridge_uses_tui_slash_adapters() -> None:
    slash_bridge = PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/slash_bridge.py"

    assert _imports_name_from_package(
        slash_bridge,
        "opensquilla.cli.tui.adapters",
        "slash_gateway",
    )
    assert _imports_name_from_package(
        slash_bridge,
        "opensquilla.cli.tui.adapters",
        "slash_standalone",
    )
    assert _imports_from_module(
        slash_bridge,
        "opensquilla.cli.tui.adapters.slash_gateway",
    )
    assert not _imports_name_from_package(
        slash_bridge,
        "opensquilla.cli.repl",
        "slash_adapter",
    )
    assert not _imports_name_from_package(
        slash_bridge,
        "opensquilla.cli.repl",
        "standalone_slash_adapter",
    )


def test_tui_slash_adapters_use_shared_chat_models() -> None:
    adapter_imports = {
        "src/opensquilla/cli/tui/adapters/slash_gateway.py": {
            "required": {
                "opensquilla.cli.chat.session_state",
                "opensquilla.cli.chat.turn",
            },
            "forbidden": {
                "opensquilla.cli.repl.session_state",
                "opensquilla.cli.repl.stream",
            },
        },
        "src/opensquilla/cli/tui/adapters/slash_bridge.py": {
            "required": {"opensquilla.cli.chat.session_state"},
            "forbidden": {"opensquilla.cli.repl.session_state"},
        },
        "src/opensquilla/cli/tui/adapters/slash_standalone.py": {
            "required": {
                "opensquilla.cli.chat.session_state",
                "opensquilla.cli.chat.turn",
            },
            "forbidden": {
                "opensquilla.cli.repl.session_state",
                "opensquilla.cli.repl.stream",
            },
        },
    }

    for relative_path, modules in adapter_imports.items():
        path = PROJECT_ROOT / relative_path
        for module_name in modules["required"]:
            assert _imports_from_module(path, module_name), (
                f"{relative_path} must import shared chat models from {module_name}"
            )
        for module_name in modules["forbidden"]:
            assert not _imports_from_module(path, module_name), (
                f"{relative_path} must not import shared chat models from {module_name}"
            )


def test_tui_input_and_command_adapters_do_not_import_repl_helpers() -> None:
    adapter_imports = {
        "src/opensquilla/cli/tui/terminal/app.py": {
            "required": {"opensquilla.cli.tui.terminal.paste"},
            "forbidden": {"opensquilla.cli.repl.paste"},
        },
        "src/opensquilla/cli/tui/terminal/prompt.py": {
            "required": {
                "opensquilla.cli.tui.adapters.commands",
                "opensquilla.cli.tui.terminal.paste",
            },
            "forbidden": {
                "opensquilla.cli.repl.commands",
                "opensquilla.cli.repl.paste",
            },
        },
        "src/opensquilla/cli/tui/adapters/slash_gateway.py": {
            "required": {
                "opensquilla.cli.tui.adapters.commands",
                "opensquilla.cli.tui.adapters.input_bridge",
            },
            "forbidden": {
                "opensquilla.cli.repl.commands",
                "opensquilla.cli.repl.input_bridge",
            },
        },
        "src/opensquilla/cli/tui/adapters/slash_standalone.py": {
            "required": {
                "opensquilla.cli.tui.adapters.commands",
                "opensquilla.cli.tui.adapters.input_bridge",
            },
            "forbidden": {
                "opensquilla.cli.repl.commands",
                "opensquilla.cli.repl.input_bridge",
            },
        },
        "src/opensquilla/cli/tui/adapters/chat_compat.py": {
            "required": {"opensquilla.cli.tui.adapters.input_bridge"},
            "forbidden": {"opensquilla.cli.repl.input_bridge"},
        },
        "src/opensquilla/cli/tui/turn_bridge.py": {
            "required": {"opensquilla.cli.tui.adapters.turn_stream_defaults"},
            "forbidden": {"opensquilla.cli.repl.input_bridge"},
        },
        "src/opensquilla/cli/tui/adapters/turn_stream_defaults.py": {
            "required": {"opensquilla.cli.tui.adapters.input_bridge"},
            "forbidden": {"opensquilla.cli.repl.input_bridge"},
        },
        "src/opensquilla/cli/chat/gateway_runtime.py": {
            "required": set(),
            "forbidden": {
                "opensquilla.engine.commands",
                "opensquilla.cli.chat.commands",
                "opensquilla.cli.repl.commands",
                "opensquilla.cli.tui.commands",
            },
        },
        "src/opensquilla/cli/tui/standalone_runtime.py": {
            "required": {"opensquilla.cli.tui.adapters.commands"},
            "forbidden": {"opensquilla.cli.repl.commands"},
        },
    }

    for relative_path, modules in adapter_imports.items():
        path = PROJECT_ROOT / relative_path
        for module_name in modules["required"]:
            assert _imports_from_module(path, module_name), (
                f"{relative_path} must import TUI input helpers from {module_name}"
            )
        for module_name in modules["forbidden"]:
            assert not _imports_from_module(path, module_name), (
                f"{relative_path} must not import TUI input helpers from {module_name}"
            )


def test_tui_owned_compat_modules_do_not_import_repl_modules() -> None:
    paths = [
        PROJECT_ROOT / "src/opensquilla/cli/tui/adapters/chat_compat.py",
        PROJECT_ROOT / "src/opensquilla/cli/tui/standalone_runtime.py",
    ]

    for path in paths:
        assert not _imports_from_package_prefix(path, "opensquilla.cli.repl")


def _imports_from_module(path: Path, module_name: str) -> bool:
    package_name, _, imported_name = module_name.rpartition(".")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == module_name:
                return True
            if node.module == package_name and any(
                alias.name == imported_name for alias in node.names
            ):
                return True
    return False


def _imports_name_from_module(path: Path, module_name: str, imported_name: str) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == module_name and any(
                alias.name == imported_name for alias in node.names
            ):
                return True
    return False


def _imports_from_package_prefix(path: Path, package_prefix: str) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == package_prefix
                or alias.name.startswith(f"{package_prefix}.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == package_prefix
                or node.module.startswith(f"{package_prefix}.")
            ):
                return True
    return False


def _imports_name_from_package(path: Path, package: str, module_name: str) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == f"{package}.{module_name}" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == package and any(alias.name == module_name for alias in node.names):
                return True
    return False


class _ContractSurface:
    async def next_line(self) -> str | None:
        return None

    def set_cancel_callback(self, cb) -> None:  # noqa: ANN001
        return None

    def set_shutdown_callback(self, cb) -> None:  # noqa: ANN001
        return None

    def emit_eof(self) -> None:
        return None

    async def write_through(self, payload: str) -> None:
        return None

    @property
    def redraw_callback(self):
        return lambda: None


class _ContractOutputHandle:
    @property
    def approval_surface(self) -> object:
        return "cli-gateway"

    async def write_through(self, payload: str) -> None:
        return None

    def stream_output(self):
        @asynccontextmanager
        async def _cm() -> AsyncIterator[Callable[[str], None]]:
            yield lambda _payload: None

        return _cm()


class _ContractRenderer:
    async def aappend_text(self, delta: str) -> None:
        return None

    async def atool_start(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        return None

    async def atool_finished(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
    ) -> None:
        return None

    async def astatus(self, message: str, *, style: str = "dim") -> None:
        return None

    async def aerror(self, message: str) -> None:
        return None

    async def afinalize(self, usage=None, *, cancelled: bool = False) -> None:  # noqa: ANN001
        return None

    async def aclose(self) -> None:
        return None


def test_surface_and_renderer_protocols_are_structural() -> None:
    assert isinstance(_ContractSurface(), TuiSurface)
    assert isinstance(_ContractOutputHandle(), TuiOutputHandle)
    assert isinstance(_ContractRenderer(), TuiRenderer)


def test_tui_event_is_explicitly_typed() -> None:
    event = TuiEvent(kind=TuiEventKind.TURN_STARTED, input_text="hello")

    assert event.kind is TuiEventKind.TURN_STARTED
    assert event.input_text == "hello"


def test_runtime_contracts_are_tui_native() -> None:
    hooks = TuiRuntimeHooks()
    config = TuiRuntimeConfig(task_name="chat-turn-test")

    assert config.task_name == "chat-turn-test"
    assert config.classify_input("hello") is TuiInputKind.NORMAL
    assert TuiInputKind.DESTRUCTIVE.value == "destructive"
    assert hooks.notice is None


def test_runtime_module_does_not_import_prompt_toolkit(monkeypatch) -> None:
    for name in list(sys.modules):
        if name == "opensquilla.cli.tui.runtime":
            monkeypatch.delitem(sys.modules, name, raising=False)

    original_import = __import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "prompt_toolkit" or name.startswith("prompt_toolkit."):
            raise AssertionError(f"runtime imported prompt_toolkit via {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _guarded_import)

    importlib.import_module("opensquilla.cli.tui.runtime")


def test_runtime_module_does_not_import_chat_or_engine_surface(monkeypatch) -> None:
    fresh_runtime_modules = {
        "opensquilla.cli.tui.contracts",
        "opensquilla.cli.tui.events",
        "opensquilla.cli.tui.runtime",
        "opensquilla.cli.tui.state",
    }
    for name in list(sys.modules):
        if name in fresh_runtime_modules:
            monkeypatch.delitem(sys.modules, name, raising=False)

    original_import = __import__
    forbidden = {
        "opensquilla.engine.commands",
        "opensquilla.cli.repl.app",
        "opensquilla.cli.repl.prompt",
        "opensquilla.cli.repl.signal_handlers",
        "opensquilla.cli.repl.slash_adapter",
        "opensquilla.cli.repl.slash_bridge",
        "opensquilla.cli.repl.slash_policy",
        "opensquilla.cli.repl.standalone_slash_adapter",
        "opensquilla.cli.repl.approval",
        "opensquilla.cli.repl.terminal_chat_adapter",
        "opensquilla.cli.repl.terminal_bridge",
        "opensquilla.cli.repl.terminal_renderer",
        "opensquilla.cli.repl.terminal_surface",
        "opensquilla.cli.tui.approval_adapter",
        "opensquilla.cli.tui.app",
        "opensquilla.cli.tui.prompt",
        "opensquilla.cli.tui.signal_handlers",
        "opensquilla.cli.tui.slash_adapter",
        "opensquilla.cli.tui.slash_bridge",
        "opensquilla.cli.tui.slash_policy",
        "opensquilla.cli.tui.standalone_slash_adapter",
        "opensquilla.cli.tui.terminal_chat_adapter",
        "opensquilla.cli.tui.terminal_bridge",
        "opensquilla.cli.tui.terminal_renderer",
        "opensquilla.cli.tui.terminal_surface",
    }
    forbidden_fromlist = {
        "opensquilla.cli.repl": {
            "approval",
            "app",
            "prompt",
            "signal_handlers",
            "slash_adapter",
            "slash_bridge",
            "slash_policy",
            "standalone_slash_adapter",
            "terminal_chat_adapter",
            "terminal_bridge",
            "terminal_renderer",
            "terminal_surface",
        },
        "opensquilla.cli.tui": {
            "approval_adapter",
            "app",
            "prompt",
            "signal_handlers",
            "slash_adapter",
            "slash_bridge",
            "slash_policy",
            "standalone_slash_adapter",
            "terminal_chat_adapter",
            "terminal_bridge",
            "terminal_renderer",
            "terminal_surface",
        },
    }

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name in forbidden:
            raise AssertionError(f"runtime imported adapter-owned module {name}")
        requested_fromlist = set(fromlist or ())
        blocked_fromlist = forbidden_fromlist.get(name, set()).intersection(
            requested_fromlist
        )
        if blocked_fromlist:
            blocked = ", ".join(sorted(blocked_fromlist))
            raise AssertionError(
                f"runtime imported adapter-owned module(s) from {name}: {blocked}"
            )
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _guarded_import)

    importlib.import_module("opensquilla.cli.tui.runtime")


def test_chat_cmd_import_does_not_load_terminal_runtime(monkeypatch) -> None:
    for name in list(sys.modules):
        if name == "opensquilla.cli.chat_cmd" or name.startswith("opensquilla.cli.tui."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    original_import = __import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "prompt_toolkit" or name.startswith("prompt_toolkit."):
            raise AssertionError(f"chat_cmd imported prompt_toolkit via {name}")
        if name == "opensquilla.cli.repl" or name.startswith("opensquilla.cli.repl."):
            raise AssertionError(f"chat_cmd imported legacy repl runtime via {name}")
        if name.startswith("opensquilla.cli.tui."):
            raise AssertionError(f"chat_cmd imported TUI compatibility via {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _guarded_import)

    importlib.import_module("opensquilla.cli.chat_cmd")
