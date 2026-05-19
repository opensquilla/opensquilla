from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "src/opensquilla/gateway/boot.py"
EXTENSION_RUNTIME = ROOT / "src/opensquilla/extension_services/gateway_runtime.py"


def _runtime_imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()

    class Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                for child in node.orelse:
                    self.visit(child)
                return
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                for alias in node.names:
                    imports.add((node.module, alias.name))

    Visitor().visit(tree)
    return imports


def test_gateway_boot_delegates_extension_services_to_boundary() -> None:
    imports = _runtime_imports_from(BOOT)

    assert (
        "opensquilla.extension_services.gateway_runtime",
        "build_extension_services_runtime",
    ) in imports
    assert (
        "opensquilla.memory.gateway_runtime",
        "build_memory_gateway_runtime",
    ) not in imports
    assert (
        "opensquilla.skills.runtime",
        "create_configured_skill_loader",
    ) not in imports
    assert ("opensquilla.scheduler", "SchedulerEngine") not in imports
    assert ("opensquilla.search.runtime", "sync_search_runtime_from_config") not in imports


def test_extension_services_runtime_file_owns_all_bootstrap_domains() -> None:
    source = EXTENSION_RUNTIME.read_text(encoding="utf-8")

    for token in (
        "build_memory_gateway_runtime",
        "create_configured_skill_loader",
        "create_skill_tools",
        "SchedulerEngine",
        "sync_search_runtime_from_config",
    ):
        assert token in source


@pytest.mark.asyncio
async def test_build_extension_services_runtime_preserves_bootstrap_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.extension_services import gateway_runtime

    events: list[tuple[str, Any]] = []

    memory_runtime = SimpleNamespace(
        memory_managers={"main": "manager"},
        memory_stores={"main": "store"},
        memory_retrievers={"main": "retriever"},
        memory_sync_managers={"main": "sync"},
        turn_capture_services={"main": "capture"},
        memory_watchers=["watcher"],
    )

    async def fake_build_memory_gateway_runtime(**kwargs: Any) -> Any:
        events.append(("memory", kwargs["agent_ids"]))
        assert kwargs["turn_runner_ref"] == []
        return memory_runtime

    class FakeJobStore:
        def __init__(self, db_path: str) -> None:
            events.append(("job_store", Path(db_path).name))
            self.db_path = db_path

        async def open(self) -> None:
            events.append(("job_store_open", Path(self.db_path).name))

    class FakeScheduler:
        def __init__(self, **kwargs: Any) -> None:
            events.append(("scheduler", kwargs["session_store"]))

        async def start(self) -> None:
            events.append(("scheduler_start", None))

    skill_loader = object()

    def fake_create_configured_skill_loader(skills_config: Any, *, workspace_dir: Any) -> Any:
        events.append(("skills", workspace_dir))
        return SimpleNamespace(
            loader=skill_loader,
            layer_dirs=SimpleNamespace(bundled_dir=tmp_path / "bundled"),
        )

    def fake_create_skill_tools(loader: Any) -> None:
        events.append(("skill_tools", loader is skill_loader))

    def fake_configure_tool_services(**kwargs: Any) -> None:
        events.append(("tool_services", kwargs))

    def fake_sync_search_runtime_from_config(config: Any) -> Any:
        events.append(("search", config.search_provider))
        return SimpleNamespace(provider_name=config.search_provider)

    monkeypatch.setattr(
        "opensquilla.memory.gateway_runtime.build_memory_gateway_runtime",
        fake_build_memory_gateway_runtime,
    )
    monkeypatch.setattr(
        "opensquilla.skills.runtime.create_configured_skill_loader",
        fake_create_configured_skill_loader,
    )
    monkeypatch.setattr(
        "opensquilla.tools.builtin.skill_tools.create_skill_tools",
        fake_create_skill_tools,
    )
    monkeypatch.setattr("opensquilla.scheduler.JobStore", FakeJobStore)
    monkeypatch.setattr("opensquilla.scheduler.SchedulerEngine", FakeScheduler)
    monkeypatch.setattr(
        "opensquilla.tools.services.configure_tool_services",
        fake_configure_tool_services,
    )
    monkeypatch.setattr(
        "opensquilla.search.runtime.sync_search_runtime_from_config",
        fake_sync_search_runtime_from_config,
    )

    config = SimpleNamespace(
        skills=SimpleNamespace(),
        workspace_dir=tmp_path / "workspace",
        search_provider="duckduckgo",
    )

    runtime = await gateway_runtime.build_extension_services_runtime(
        config=config,
        tool_registry=object(),
        session_storage="storage",
        agent_ids=["main", "ops"],
        state_path_factory=lambda _config, name: tmp_path / name,
        logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None),
    )

    assert runtime.memory_managers == {"main": "manager"}
    assert runtime.memory_stores == {"main": "store"}
    assert runtime.memory_retrievers == {"main": "retriever"}
    assert runtime.memory_sync_managers == {"main": "sync"}
    assert runtime.turn_capture_services == {"main": "capture"}
    assert runtime.memory_watchers == ["watcher"]
    assert runtime.skill_loader is skill_loader
    assert runtime.cron_scheduler is not None
    assert runtime.turn_runner_ref == []
    assert events == [
        ("memory", ["main", "ops"]),
        ("skills", tmp_path / "workspace"),
        ("skill_tools", True),
        ("job_store", "scheduler.db"),
        ("job_store_open", "scheduler.db"),
        ("scheduler", "storage"),
        ("scheduler_start", None),
        ("tool_services", {"scheduler": runtime.cron_scheduler}),
        ("search", "duckduckgo"),
    ]


@pytest.mark.asyncio
async def test_build_extension_services_runtime_keeps_fail_open_boundaries_independent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.extension_services import gateway_runtime

    warnings: list[tuple[str, str]] = []

    async def failing_memory_runtime(**_kwargs: Any) -> Any:
        raise RuntimeError("memory unavailable")

    def failing_skill_loader(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("skills unavailable")

    class FailingJobStore:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("scheduler unavailable")

    def failing_search_runtime(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("search unavailable")

    monkeypatch.setattr(
        "opensquilla.memory.gateway_runtime.build_memory_gateway_runtime",
        failing_memory_runtime,
    )
    monkeypatch.setattr(
        "opensquilla.skills.runtime.create_configured_skill_loader",
        failing_skill_loader,
    )
    monkeypatch.setattr("opensquilla.scheduler.JobStore", FailingJobStore)
    monkeypatch.setattr(
        "opensquilla.search.runtime.sync_search_runtime_from_config",
        failing_search_runtime,
    )

    runtime = await gateway_runtime.build_extension_services_runtime(
        config=SimpleNamespace(
            skills=SimpleNamespace(),
            workspace_dir=tmp_path / "workspace",
            search_provider="duckduckgo",
        ),
        tool_registry=object(),
        session_storage="storage",
        agent_ids=["main"],
        state_path_factory=lambda _config, name: tmp_path / name,
        logger=SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda event, **kwargs: warnings.append((event, kwargs["error"])),
        ),
    )

    assert runtime.memory_managers == {}
    assert runtime.memory_stores == {}
    assert runtime.memory_retrievers == {}
    assert runtime.memory_sync_managers == {}
    assert runtime.turn_capture_services == {}
    assert runtime.memory_watchers == []
    assert runtime.skill_loader is None
    assert runtime.cron_scheduler is None
    assert runtime.turn_runner_ref == []
    assert warnings == [
        ("build_services.memory_tools_failed", "memory unavailable"),
        ("build_services.skill_loader_failed", "skills unavailable"),
        ("build_services.cron_scheduler_failed", "scheduler unavailable"),
        ("build_services.search_provider_failed", "search unavailable"),
    ]
