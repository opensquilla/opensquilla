from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.channels.delivery import resolve_delivery_target
from opensquilla.channels.manager import ChannelManager

ROOT = Path(__file__).resolve().parents[2]
CHANNEL_MANAGER = ROOT / "src" / "opensquilla" / "channels" / "manager.py"
CHANNEL_DELIVERY = ROOT / "src" / "opensquilla" / "channels" / "delivery.py"


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _class_methods(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return set()


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_channel_delivery_module_owns_target_resolution_policy() -> None:
    assert CHANNEL_DELIVERY.exists()
    assert "resolve_delivery_target" in _top_level_functions(CHANNEL_DELIVERY)
    assert "_build_delivery_resolution" not in _class_methods(CHANNEL_MANAGER, "ChannelManager")
    assert "opensquilla.channels.delivery" in _imported_modules(CHANNEL_MANAGER)


def test_channel_delivery_resolves_entry_type_account_and_thread_policy() -> None:
    channels = {"slack-work": object(), "slack-alerts": object(), "teams": object()}
    channel_types = {
        "slack-work": "slack",
        "slack-alerts": "slack",
        "teams": "msteams",
    }

    by_name = resolve_delivery_target(
        channels=channels,
        channel_types=channel_types,
        target="slack-work",
        to="C123",
        thread_id="1700000000.000100",
    )
    assert by_name.ok is True
    assert by_name.adapter is channels["slack-work"]
    assert by_name.adapter_name == "slack-work"
    assert by_name.channel_type == "slack"
    assert by_name.to == "C123"
    assert by_name.thread_id == "1700000000.000100"

    ambiguous = resolve_delivery_target(
        channels=channels,
        channel_types=channel_types,
        target="slack",
    )
    assert ambiguous.ok is False
    assert ambiguous.reason == "ambiguous_account"

    account = resolve_delivery_target(
        channels=channels,
        channel_types=channel_types,
        target="slack",
        account_id="slack-alerts",
        to="C456",
    )
    assert account.ok is True
    assert account.adapter is channels["slack-alerts"]
    assert account.adapter_name == "slack-alerts"
    assert account.account_id == "slack-alerts"

    wrong_account = resolve_delivery_target(
        channels=channels,
        channel_types=channel_types,
        target="slack",
        account_id="teams",
    )
    assert wrong_account.ok is False
    assert wrong_account.reason == "unsupported_account"

    unsupported_thread = resolve_delivery_target(
        channels=channels,
        channel_types=channel_types,
        target="teams",
        thread_id="not-supported",
    )
    assert unsupported_thread.ok is False
    assert unsupported_thread.reason == "unsupported_thread"


def test_channel_manager_delegates_delivery_resolution_without_changing_public_contract() -> None:
    adapter = object()
    manager = ChannelManager(
        {"work": adapter},
        None,
        None,
        _channel_types={"work": "slack"},
    )

    resolved = manager.resolve_delivery_target(
        target="slack",
        to="C123",
        account_id="work",
        thread_id="1700000000.000100",
    )

    assert resolved.ok is True
    assert resolved.adapter is adapter
    assert resolved.adapter_name == "work"
    assert resolved.channel_type == "slack"
    assert resolved.to == "C123"
    assert resolved.account_id == "work"
    assert resolved.thread_id == "1700000000.000100"
