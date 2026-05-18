from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
SESSION = ROOT / "src/opensquilla/session"
RPC_SESSION_MANAGEMENT = GATEWAY / "rpc_session_management.py"
RPC_SESSION_SEND = GATEWAY / "rpc_session_send.py"
SESSION_MANAGEMENT_SERVICE = SESSION / "management_service.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = _tree(path)
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def _top_level_functions(path: Path) -> set[str]:
    tree = _tree(path)
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_session_management_service_owns_create_patch_and_model_defaults() -> None:
    assert SESSION_MANAGEMENT_SERVICE.is_file()

    service_functions = _top_level_functions(SESSION_MANAGEMENT_SERVICE)
    management_functions = _top_level_functions(RPC_SESSION_MANAGEMENT)
    management_imports = _imports_from(RPC_SESSION_MANAGEMENT)

    assert {
        "agent_registry_has",
        "agent_registry_model",
        "create_session",
        "create_session_key",
        "model_value",
        "patch_session",
        "require_session_key",
        "session_turn_model",
    } <= service_functions
    assert {
        "agent_registry_has",
        "agent_registry_model",
        "create_session_key",
        "model_value",
        "require_session_key",
        "session_turn_model",
    }.isdisjoint(management_functions)
    assert {
        ("opensquilla.session.rpc_payload", "session_agent_not_found_details"),
        ("opensquilla.session.rpc_payload", "session_create_response"),
        ("opensquilla.session.rpc_payload", "session_create_stub_response"),
        ("opensquilla.session.rpc_payload", "session_patch_response"),
    }.isdisjoint(management_imports)
    assert (
        "opensquilla.session.management_service",
        "create_session",
    ) in management_imports
    assert (
        "opensquilla.session.management_service",
        "patch_session",
    ) in management_imports


def test_session_send_uses_service_instead_of_rpc_management_module() -> None:
    imports = _imports_from(RPC_SESSION_SEND)

    assert (
        "opensquilla.session.management_service",
        "require_session_key",
    ) in imports
    assert (
        "opensquilla.session.management_service",
        "session_turn_model",
    ) in imports
    assert not any(
        module == "opensquilla.gateway.rpc_session_management"
        for module, _name in imports
    )
