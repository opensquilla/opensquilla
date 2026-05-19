"""Architecture guards for builtin tool service wiring."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from opensquilla.tools import services
from opensquilla.tools.builtin import admin as admin_tool
from opensquilla.tools.builtin import agents as agents_tool
from opensquilla.tools.builtin import sessions as sessions_tool

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src" / "opensquilla"

BUILTIN_SERVICE_MODULES = (
    SOURCE_ROOT / "tools" / "builtin" / "admin.py",
    SOURCE_ROOT / "tools" / "builtin" / "agents.py",
    SOURCE_ROOT / "tools" / "builtin" / "sessions.py",
)

FORBIDDEN_TOP_LEVEL_SERVICE_GLOBALS = {
    "_agent_registry",
    "_gateway_config",
    "_scheduler",
    "_session_manager",
    "_spawn_group_closer",
    "_task_runtime",
}


class _Scheduler:
    pass


async def _close_spawn_group(*_args: Any, **_kwargs: Any) -> bool:
    return True


def _top_level_assigned_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def test_builtin_tool_modules_do_not_store_service_globals() -> None:
    offenders = {
        path.name: sorted(_top_level_assigned_names(path) & FORBIDDEN_TOP_LEVEL_SERVICE_GLOBALS)
        for path in BUILTIN_SERVICE_MODULES
    }

    assert offenders == {"admin.py": [], "agents.py": [], "sessions.py": []}


def test_legacy_builtin_setters_delegate_to_shared_tool_services() -> None:
    session_manager = object()
    task_runtime = object()
    config = object()
    registry = object()
    scheduler = _Scheduler()
    services.reset_tool_services()

    try:
        sessions_tool.set_session_manager(session_manager)
        sessions_tool.set_task_runtime(task_runtime)
        sessions_tool.set_gateway_config(config)
        sessions_tool.set_spawn_group_closer(_close_spawn_group)
        agents_tool.set_agent_registry(registry)
        admin_tool.set_scheduler(scheduler)

        wired = services.current_tool_services()
        assert wired.session_manager is session_manager
        assert wired.task_runtime is task_runtime
        assert wired.gateway_config is config
        assert wired.spawn_group_closer is _close_spawn_group
        assert wired.agent_registry is registry
        assert wired.scheduler is scheduler
        assert sessions_tool.session_manager_available() is True
        assert sessions_tool.task_runtime_available() is True
        assert admin_tool.gateway_config_available() is True
        assert admin_tool.scheduler_available() is True
    finally:
        services.reset_tool_services()


def test_gateway_boot_uses_shared_tool_service_wiring() -> None:
    text = (SOURCE_ROOT / "gateway" / "boot.py").read_text(encoding="utf-8")

    assert "from opensquilla.tools.services import configure_tool_services" in text
    assert "from opensquilla.tools.builtin.admin import set_" not in text
    assert "from opensquilla.tools.builtin.agents import set_" not in text
    assert "from opensquilla.tools.builtin.sessions import set_session_manager" not in text
    assert "from opensquilla.tools.builtin.sessions import set_task_runtime" not in text
