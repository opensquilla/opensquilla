from __future__ import annotations

import ast
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "src/opensquilla/session"
GATEWAY = ROOT / "src/opensquilla/gateway"

SESSION_MANAGEMENT_SERVICE = SESSION / "management_service.py"
SESSION_SERVICES = SESSION / "services.py"
GATEWAY_SESSION_MANAGEMENT_SERVICE = GATEWAY / "session_management_service.py"
GATEWAY_SESSION_SERVICES = GATEWAY / "session_services.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports_from(path: Path) -> set[tuple[str, str]]:
    return {
        (node.module or "", alias.name)
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def _top_level_defs(path: Path) -> set[str]:
    return {
        node.name
        for node in _tree(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_session_package_owns_management_service_implementation() -> None:
    assert SESSION_MANAGEMENT_SERVICE.is_file()
    assert {
        "agent_registry_has",
        "agent_registry_model",
        "create_session",
        "create_session_key",
        "model_value",
        "patch_session",
        "require_session_key",
        "session_turn_model",
    } <= _top_level_defs(SESSION_MANAGEMENT_SERVICE)
    assert (
        "opensquilla.session.management_service",
        "create_session",
    ) in _imports_from(GATEWAY / "rpc_session_management.py")
    assert (
        "opensquilla.session.management_service",
        "session_turn_model",
    ) in _imports_from(GATEWAY / "rpc_session_send.py")


def test_session_package_owns_runtime_service_accessors() -> None:
    assert SESSION_SERVICES.is_file()
    assert {
        "SessionEpochCache",
        "SessionLockProvider",
        "SessionStorageProvider",
        "get_session_epoch",
        "get_session_lock",
        "get_session_storage",
        "set_session_epoch",
    } <= _top_level_defs(SESSION_SERVICES)

    gateway_modules = [
        GATEWAY / "boot.py",
        GATEWAY / "rpc" / "registry.py",
        GATEWAY / "rpc_session_events.py",
        GATEWAY / "rpc_session_lifecycle.py",
        GATEWAY / "rpc_session_read_queries.py",
        GATEWAY / "rpc_session_send.py",
    ]
    for path in gateway_modules:
        assert not any(
            module == "opensquilla.gateway.session_services"
            for module, _name in _imports_from(path)
        ), path


def test_gateway_session_service_modules_remain_compatibility_facades() -> None:
    assert not _top_level_defs(GATEWAY_SESSION_MANAGEMENT_SERVICE)
    assert not _top_level_defs(GATEWAY_SESSION_SERVICES)
    assert (
        "opensquilla.session.management_service",
        "create_session",
    ) in _imports_from(GATEWAY_SESSION_MANAGEMENT_SERVICE)
    assert (
        "opensquilla.session.services",
        "get_session_storage",
    ) in _imports_from(GATEWAY_SESSION_SERVICES)


def test_legacy_gateway_service_imports_reexport_session_boundary_objects() -> None:
    session_management = importlib.import_module("opensquilla.session.management_service")
    gateway_management = importlib.import_module("opensquilla.gateway.session_management_service")
    session_services = importlib.import_module("opensquilla.session.services")
    gateway_services = importlib.import_module("opensquilla.gateway.session_services")

    assert gateway_management.create_session is session_management.create_session
    assert gateway_management.patch_session is session_management.patch_session
    assert gateway_management.session_turn_model is session_management.session_turn_model
    assert gateway_services.get_session_storage is session_services.get_session_storage
    assert gateway_services.get_session_epoch is session_services.get_session_epoch
    assert gateway_services.get_session_lock is session_services.get_session_lock
