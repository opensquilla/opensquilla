from __future__ import annotations

import asyncio
import builtins
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine.types import AgentConfig, DoneEvent
from opensquilla.gateway.boot import (
    _configured_agent_ids,
    _gateway_home,
    _register_dream_crons,
    _task_runtime_turn_hard_deadline_s,
    _warn_workspace_state_mismatch,
    build_flush_service,
    build_services,
    dispatch_task_runtime_turn,
    emit_skill_filter_banner,
    validate_squilla_router_runtime,
)
from opensquilla.gateway.config import AgentEntryConfig, GatewayConfig
from opensquilla.gateway.diagnostics import DiagnosticsState
from opensquilla.gateway.routing import build_cli_route_envelope, build_cron_route_envelope
from opensquilla.onboarding.mutations import upsert_channel
from opensquilla.provider import Message
from opensquilla.scheduler.types import CronJob, JobStatus
from opensquilla.session.compaction import CompactionConfig
from opensquilla.session.manager import SessionManager
from opensquilla.session.models import SessionIntent
from opensquilla.session.storage import SessionStorage
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import CallerKind, ToolContext, ToolSpec


def test_gateway_boot_bridges_compaction_notifications_to_session_stream() -> None:
    source = Path("src/opensquilla/gateway/boot.py").read_text(encoding="utf-8")

    assert "add_compaction_listener" in source
    assert '"session.event.compaction"' in source
    assert "_compaction_listener_remove" in source


def test_task_runtime_default_hard_deadline_is_unbounded() -> None:
    config = GatewayConfig()

    deadline = _task_runtime_turn_hard_deadline_s(config)

    assert deadline is None


def test_task_runtime_hard_deadline_honors_explicit_config() -> None:
    config = GatewayConfig()
    config.task_runtime.turn_hard_deadline_s = 12.5

    assert _task_runtime_turn_hard_deadline_s(config) == 12.5


def test_gateway_stream_timeouts_allow_long_silent_agent_work() -> None:
    config = GatewayConfig()

    assert config.agent_stream_idle_timeout_seconds == 600.0
    assert config.webui_stream_idle_grace_seconds == 630.0
    assert config.webui_stream_idle_grace_seconds > config.agent_stream_idle_timeout_seconds


def test_compaction_time_budget_defaults_allow_long_chain_work() -> None:
    gateway_config = GatewayConfig()
    agent_config = AgentConfig()
    compaction_config = CompactionConfig()

    assert gateway_config.memory.flush_timeout_seconds == 15.0
    assert gateway_config.memory.flush_background_timeout_seconds == 120.0
    assert gateway_config.compaction.timeout_seconds == 90.0
    assert agent_config.flush_timeout_seconds == 15.0
    assert agent_config.flush_background_timeout_seconds == 120.0
    assert compaction_config.timeout_seconds == 90.0


def test_gateway_home_uses_configured_state_parent(tmp_path: Path) -> None:
    config = GatewayConfig(
        state_dir=str(tmp_path / "instance" / "state"),
        workspace_dir=str(tmp_path / "instance" / "workspace"),
    )

    assert _gateway_home(config) == tmp_path / "instance"


def test_gateway_home_falls_back_to_config_path_parent(tmp_path: Path) -> None:
    config = GatewayConfig(
        state_dir=None,
        config_path=str(tmp_path / "service" / "config.toml"),
        workspace_dir=str(tmp_path / "service" / "workspace"),
    )

    assert _gateway_home(config) == tmp_path / "service"


class _FakeDreamScheduler:
    def __init__(self, jobs: list[CronJob] | None = None) -> None:
        self.jobs = jobs or []
        self.added: list[dict[str, Any]] = []
        self.paused: list[str] = []

    async def list_jobs(self) -> list[CronJob]:
        return self.jobs

    async def add_job(self, **kwargs: Any) -> None:
        self.added.append(kwargs)

    async def pause_job(self, job_id: str) -> None:
        self.paused.append(job_id)
        for job in self.jobs:
            if job.id == job_id:
                job.status = JobStatus.PAUSED


def test_build_turn_runner_from_services_wires_memory_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeTurnRunner:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    from opensquilla.gateway import boot

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    services = SimpleNamespace(
        provider_selector=object(),
        tool_registry=object(),
        session_manager=object(),
        skill_loader=object(),
        usage_tracker=object(),
        config=GatewayConfig(),
        memory_sync_managers={"main": object()},
        memory_retrievers={"main": object()},
        turn_capture_services={"main": object()},
        flush_service=object(),
        model_catalog=object(),
    )

    runner = boot.build_turn_runner_from_services(services)

    assert isinstance(runner, FakeTurnRunner)
    assert captured["memory_sync_managers"] is services.memory_sync_managers
    assert captured["memory_retrievers"] is services.memory_retrievers
    assert captured["turn_capture_services"] is services.turn_capture_services
    assert captured["session_flush_service"] is services.flush_service
    assert captured["model_catalog"] is services.model_catalog


def test_build_turn_runner_from_services_wires_diagnostics_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeTurnRunner:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    services = SimpleNamespace(
        provider_selector=object(),
        tool_registry=object(),
        session_manager=object(),
        skill_loader=object(),
        usage_tracker=object(),
        config=GatewayConfig(),
    )
    state = DiagnosticsState.from_config(GatewayConfig())

    from opensquilla.gateway import boot

    runner = boot.build_turn_runner_from_services(services, diagnostics_state=state)

    assert isinstance(runner, FakeTurnRunner)
    assert captured["diagnostics_state"] is state


@pytest.mark.asyncio
async def test_start_gateway_server_shares_diagnostics_state_between_app_and_turn_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_runner: dict[str, Any] = {}

    class FakeTurnRunner:
        def __init__(self, **kwargs: Any) -> None:
            captured_runner.update(kwargs)

        def set_session_lock_provider(self, provider: Any) -> None:
            captured_runner["session_lock_provider"] = provider

    async def fake_build_services(**kwargs: Any) -> Any:
        config = kwargs["config"]

        async def close() -> None:
            return None

        return SimpleNamespace(
            provider_selector=object(),
            tool_registry=object(),
            session_manager=object(),
            skill_loader=object(),
            usage_tracker=object(),
            config=config,
            memory_sync_managers={},
            model_catalog=None,
            memory_retrievers={},
            turn_capture_services={},
            flush_service=None,
            cron_scheduler=None,
            task_runtime=None,
            agent_registry=None,
            memory_managers={},
            memory_stores={},
            _turn_runner_ref=[],
            close=close,
        )

    from opensquilla.gateway import boot

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr(boot, "build_services", fake_build_services)
    monkeypatch.setattr(boot, "_setup_file_logging", lambda config: None)
    monkeypatch.setattr(boot, "emit_skill_filter_banner", lambda config: None)
    monkeypatch.setattr(
        "opensquilla.gateway.pidlock.GatewayPidLock.acquire",
        lambda self: None,
    )
    monkeypatch.setattr(
        "opensquilla.gateway.pidlock.GatewayPidLock.release",
        lambda self: None,
    )
    config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        workspace_dir=str(tmp_path / "workspace"),
        control_ui={"enabled": False},
        channels={"channels": []},
        diagnostics_enabled=True,
    )

    server = await boot.start_gateway_server(config=config, run=False)

    try:
        state = server.app.state.diagnostics_state
        assert isinstance(state, DiagnosticsState)
        assert captured_runner["diagnostics_state"] is state
        state.set_runtime(enabled=True, raw=True)
        assert captured_runner["diagnostics_state"].raw_turn_call_enabled() is True
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_start_gateway_server_creates_default_subscription_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_bridge: dict[str, Any] = {}

    class FakeTurnRunner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def set_session_lock_provider(self, _provider: Any) -> None:
            pass

    class FakeEventBridge:
        def __init__(self, *, subscription_manager: Any, connection_registry: Any) -> None:
            captured_bridge["subscription_manager"] = subscription_manager
            captured_bridge["connection_registry"] = connection_registry

        async def emit(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    async def fake_build_services(**kwargs: Any) -> Any:
        config = kwargs["config"]

        async def close() -> None:
            return None

        return SimpleNamespace(
            provider_selector=object(),
            tool_registry=object(),
            session_manager=object(),
            skill_loader=object(),
            usage_tracker=object(),
            config=config,
            memory_sync_managers={},
            model_catalog=None,
            memory_retrievers={},
            turn_capture_services={},
            flush_service=None,
            cron_scheduler=None,
            task_runtime=None,
            agent_registry=None,
            memory_managers={},
            memory_stores={},
            _turn_runner_ref=[],
            close=close,
        )

    from opensquilla.gateway import boot
    from opensquilla.gateway.websocket import SubscriptionManager

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr("opensquilla.gateway.event_bridge.EventBridge", FakeEventBridge)
    monkeypatch.setattr(boot, "build_services", fake_build_services)
    monkeypatch.setattr(boot, "_setup_file_logging", lambda config: None)
    monkeypatch.setattr(boot, "emit_skill_filter_banner", lambda config: None)
    monkeypatch.setattr(
        "opensquilla.gateway.pidlock.GatewayPidLock.acquire",
        lambda self: None,
    )
    monkeypatch.setattr(
        "opensquilla.gateway.pidlock.GatewayPidLock.release",
        lambda self: None,
    )
    config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        workspace_dir=str(tmp_path / "workspace"),
        control_ui={"enabled": False},
        channels={"channels": []},
    )

    server = await boot.start_gateway_server(config=config, run=False)

    try:
        assert isinstance(captured_bridge["subscription_manager"], SubscriptionManager)
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_start_gateway_server_schedules_router_preload_after_channels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeTurnRunner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def set_session_lock_provider(self, _provider: Any) -> None:
            pass

    class FakeChannelManager:
        async def start_all(self) -> dict[str, bool]:
            events.append("channels.start_all")
            return {"feishu": True}

        def start_errors(self) -> dict[str, dict[str, str]]:
            return {}

        async def stop_all(self) -> None:
            return None

    class FakeServer:
        def __init__(self, _config: Any) -> None:
            self.should_exit = False

        async def serve(self) -> None:
            return None

    async def fake_build_services(**kwargs: Any) -> Any:
        config = kwargs["config"]

        async def close() -> None:
            return None

        return SimpleNamespace(
            provider_selector=object(),
            tool_registry=object(),
            session_manager=object(),
            skill_loader=object(),
            usage_tracker=object(),
            config=config,
            memory_sync_managers={},
            model_catalog=None,
            memory_retrievers={},
            turn_capture_services={},
            flush_service=None,
            cron_scheduler=None,
            task_runtime=None,
            agent_registry=None,
            memory_managers={},
            memory_stores={},
            _turn_runner_ref=[],
            close=close,
        )

    def fake_create_background_task(coro: Any) -> Any:
        code = getattr(coro, "cr_code", None)
        name = getattr(code, "co_name", "")
        if name == "preload_squilla_router_runtime":
            events.append("router.preload.scheduled")
        elif name == "serve":
            events.append("server.serve.scheduled")
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return __import__("asyncio").create_task(__import__("asyncio").sleep(0))

    from opensquilla.gateway import boot

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr(boot, "build_services", fake_build_services)
    monkeypatch.setattr(boot, "_setup_file_logging", lambda config: None)
    monkeypatch.setattr(boot, "emit_skill_filter_banner", lambda config: None)
    monkeypatch.setattr(boot, "create_background_task", fake_create_background_task)
    monkeypatch.setattr(boot.uvicorn, "Server", FakeServer)
    monkeypatch.setattr(
        "opensquilla.gateway.pidlock.GatewayPidLock.acquire",
        lambda self: None,
    )

    config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        workspace_dir=str(tmp_path / "workspace"),
        control_ui={"enabled": False},
        channels={"channels": []},
    )
    config.squilla_router.enabled = True

    server = await boot.start_gateway_server(
        config=config,
        channel_manager=FakeChannelManager(),
        run=True,
    )

    try:
        assert events.index("channels.start_all") < events.index("router.preload.scheduled")
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_start_gateway_server_wires_cron_failure_dispatcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Driver-level guard for the production cron failure-destination wire.

    When ``svc.cron_scheduler`` exists, boot must register
    ``DeliveryChain.dispatch_failure_alert`` as the global failure dispatcher
    in ``scheduler.jobs`` so failed cron runs reach the configured FD at
    runtime. Without this wire the dispatch plumbing is dead in production
    even though unit tests cover the hook directly.
    """
    captured: dict[str, Any] = {}

    class FakeTurnRunner:
        def __init__(self, **_kw: Any) -> None: ...

        def set_session_lock_provider(self, _provider: Any) -> None: ...

    class FakeCronScheduler:
        def __init__(self) -> None:
            self.registered: dict[str, Any] = {}

        def register_handler(self, key: str, fn: Any) -> None:
            self.registered[key] = fn

        async def list_jobs(self) -> list:
            return []

    cron_sched = FakeCronScheduler()

    async def fake_build_services(**kwargs: Any) -> Any:
        async def close() -> None:
            return None

        return SimpleNamespace(
            provider_selector=object(),
            tool_registry=object(),
            session_manager=None,
            skill_loader=object(),
            usage_tracker=object(),
            config=kwargs["config"],
            memory_sync_managers={},
            model_catalog=None,
            memory_retrievers={},
            turn_capture_services={},
            flush_service=None,
            cron_scheduler=cron_sched,
            task_runtime=None,
            agent_registry=None,
            memory_managers={},
            memory_stores={},
            _turn_runner_ref=[],
            close=close,
        )

    from opensquilla.gateway import boot
    from opensquilla.scheduler import jobs as scheduler_jobs

    def _record_dispatcher(fn: Any) -> None:
        captured["dispatcher"] = fn

    monkeypatch.setattr("opensquilla.engine.runtime.TurnRunner", FakeTurnRunner)
    monkeypatch.setattr(boot, "build_services", fake_build_services)
    monkeypatch.setattr(boot, "_setup_file_logging", lambda config: None)
    monkeypatch.setattr(boot, "emit_skill_filter_banner", lambda config: None)
    monkeypatch.setattr(scheduler_jobs, "set_failure_dispatcher", _record_dispatcher)
    monkeypatch.setattr(
        "opensquilla.gateway.pidlock.GatewayPidLock.acquire", lambda self: None
    )
    monkeypatch.setattr(
        "opensquilla.gateway.pidlock.GatewayPidLock.release", lambda self: None
    )

    config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        workspace_dir=str(tmp_path / "workspace"),
        control_ui={"enabled": False},
        channels={"channels": []},
    )

    server = await boot.start_gateway_server(config=config, run=False)
    try:
        assert callable(captured.get("dispatcher")), (
            "set_failure_dispatcher was not called during boot — the cron "
            "failure-destination wire is missing from gateway/boot.py"
        )
        # The wire must register DeliveryChain.dispatch_failure_alert
        # (a bound method), not some unrelated callable.
        assert (
            getattr(captured["dispatcher"], "__name__", "")
            == "dispatch_failure_alert"
        )
        # Handler factories ran, confirming the wire ran inside the cron-init
        # branch (not just by coincidence).
        assert set(cron_sched.registered) >= {
            "agent_run",
            "static_message",
            "system_event",
        }
    finally:
        await server.close()


def test_build_flush_service_respects_memory_flush_enabled_config() -> None:
    service = build_flush_service(
        tool_registry=ToolRegistry(),
        provider_selector=SimpleNamespace(resolve=lambda: object()),
        config=GatewayConfig(memory={"flush_enabled": False}),
    )

    assert service is None


def test_build_flush_service_uses_configured_background_memory_timeout() -> None:
    service = build_flush_service(
        tool_registry=ToolRegistry(),
        provider_selector=SimpleNamespace(resolve=lambda: object()),
        config=GatewayConfig(
            memory={
                "flush_timeout_seconds": 0.25,
                "flush_background_timeout_seconds": 42.0,
            }
        ),
    )

    assert service is not None
    assert service._default_timeout == 42.0


@pytest.mark.asyncio
async def test_build_flush_service_wires_durable_receipt_writer(tmp_path: Path) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.sqlite"))
    session_manager = SessionManager(storage)
    registry = ToolRegistry()

    async def memory_save(path: str, content: str, mode: str) -> str:
        assert mode == "append"
        assert content.startswith("# Raw flush")
        return f"Saved to {path} (0 chunks indexed)."

    registry.register(
        ToolSpec(
            name="memory_save",
            description="Save memory",
            parameters={
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string"},
            },
            required=["path", "content", "mode"],
        ),
        memory_save,
    )
    try:
        session_key = "agent:main:webchat:s1"
        session = await session_manager.create(session_key)
        service = build_flush_service(
            tool_registry=registry,
            provider_selector=SimpleNamespace(resolve=lambda: None),
            config=GatewayConfig(),
            session_manager=session_manager,
        )

        receipt = await service.execute(
            [Message(role="user", content="temporary transcript")],
            session_key,
            agent_id="main",
        )
        rows = await storage.list_memory_durable_receipts(session_key=session_key)

        assert receipt.result_status == "ok_archive_only"
        assert len(rows) == 1
        assert rows[0].session_id == session.session_id
        assert rows[0].scope == "repair"
        assert rows[0].status == "repair_pending"
        assert rows[0].reason == "ok_archive_only"
        assert rows[0].target_path == receipt.flushed_paths[0]
        assert rows[0].source_path == f"session:{session_key}:flush:1-1"
        assert rows[0].content_hash == receipt.content_hash
        assert rows[0].turn_id == "flush:1-1"
        assert rows[0].idempotency_key.startswith(
            f"flush-receipt:repair:{session_key}:{session.session_id}:flush:1-1:"
        )
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_build_flush_service_receipt_uses_session_id_captured_before_rotation(
    tmp_path: Path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.sqlite"))
    session_manager = SessionManager(storage)
    registry = ToolRegistry()
    save_started = asyncio.Event()
    allow_save = asyncio.Event()

    async def memory_save(path: str, content: str, mode: str) -> str:
        save_started.set()
        await allow_save.wait()
        return f"Saved to {path} (0 chunks indexed)."

    registry.register(
        ToolSpec(
            name="memory_save",
            description="Save memory",
            parameters={
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string"},
            },
            required=["path", "content", "mode"],
        ),
        memory_save,
    )
    try:
        session_key = "agent:main:webchat:s1"
        original = await session_manager.create(session_key)
        service = build_flush_service(
            tool_registry=registry,
            provider_selector=SimpleNamespace(resolve=lambda: None),
            config=GatewayConfig(),
            session_manager=session_manager,
        )

        task = asyncio.create_task(
            service.execute(
                [Message(role="user", content="temporary transcript")],
                session_key,
                agent_id="main",
            )
        )
        await asyncio.wait_for(save_started.wait(), timeout=2.0)
        rotated, did_rotate = await session_manager.apply_intent(
            session_key,
            SessionIntent.RESET_SAME_KEY,
        )
        allow_save.set()
        receipt = await task
        rows = await storage.list_memory_durable_receipts(session_key=session_key)

        assert did_rotate
        assert rotated.session_id != original.session_id
        assert receipt.session_id == original.session_id
        assert len(rows) == 1
        assert rows[0].session_id == original.session_id
        assert rows[0].session_id != rotated.session_id
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_build_flush_service_receipts_distinguish_same_window_different_content(
    tmp_path: Path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.sqlite"))
    session_manager = SessionManager(storage)
    registry = ToolRegistry()

    async def memory_save(path: str, content: str, mode: str) -> str:
        return f"Saved to {path} (0 chunks indexed)."

    registry.register(
        ToolSpec(
            name="memory_save",
            description="Save memory",
            parameters={
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string"},
            },
            required=["path", "content", "mode"],
        ),
        memory_save,
    )
    try:
        session_key = "agent:main:webchat:s1"
        await session_manager.create(session_key)
        service = build_flush_service(
            tool_registry=registry,
            provider_selector=SimpleNamespace(resolve=lambda: None),
            config=GatewayConfig(),
            session_manager=session_manager,
        )

        first = await service.execute(
            [Message(role="user", content="first content")],
            session_key,
            agent_id="main",
        )
        second = await service.execute(
            [Message(role="user", content="second content")],
            session_key,
            agent_id="main",
        )
        rows = await storage.list_memory_durable_receipts(session_key=session_key)

        assert first.content_hash != second.content_hash
        assert len(rows) == 2
        assert len({row.content_hash for row in rows}) == 2
        assert len({row.idempotency_key for row in rows}) == 2
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_build_flush_service_archive_failed_without_checkpoint_is_checkpoint_failed(
    tmp_path: Path,
) -> None:
    storage = await SessionStorage.open(str(tmp_path / "sessions.sqlite"))
    session_manager = SessionManager(storage)
    registry = ToolRegistry()

    async def memory_save(path: str, content: str, mode: str) -> str:
        raise RuntimeError("disk full")

    registry.register(
        ToolSpec(
            name="memory_save",
            description="Save memory",
            parameters={
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string"},
            },
            required=["path", "content", "mode"],
        ),
        memory_save,
    )
    try:
        session_key = "agent:main:webchat:s1"
        session = await session_manager.create(session_key)
        service = build_flush_service(
            tool_registry=registry,
            provider_selector=SimpleNamespace(resolve=lambda: None),
            config=GatewayConfig(),
            session_manager=session_manager,
        )

        receipt = await service.execute(
            [Message(role="user", content="temporary transcript")],
            session_key,
            agent_id="main",
        )
        rows = await storage.list_memory_durable_receipts(session_key=session_key)

        assert receipt.result_status == "archive_failed"
        assert len(rows) == 1
        assert rows[0].session_id == session.session_id
        assert rows[0].scope == "checkpoint"
        assert rows[0].status == "checkpoint_failed"
        assert rows[0].reason == "archive_failed"
        assert rows[0].content_hash == receipt.content_hash
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_build_services_registers_session_search_tool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "opensquilla.sandbox.integration.configure_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            effective=SimpleNamespace(as_dict=lambda: {})
        ),
    )

    captured_memory_kwargs: dict[str, Any] = {}

    async def fake_build_memory_managers(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        captured_memory_kwargs.update(_kwargs)
        return {}

    monkeypatch.setattr(
        "opensquilla.memory.manager.build_memory_managers",
        fake_build_memory_managers,
    )
    registry = ToolRegistry()
    config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        workspace_dir=str(tmp_path / "workspace"),
        control_ui={"enabled": False},
        channels={"channels": []},
        mcp={"enabled": False},
        memory={"flush_enabled": False},
    )

    services = await build_services(
        config=config,
        tool_registry=registry,
        session_db_path=str(tmp_path / "sessions.sqlite"),
    )
    try:
        session_search = registry.get("session_search")
        assert session_search is not None
        assert "Full-text search across persisted session transcripts" in (
            session_search.spec.description
        )
        assert "defaults to curated memory source files" in (
            session_search.spec.description
        )
        assert "use source=sessions or source=all" in session_search.spec.description
        owner_names = {
            tool["name"]
            for tool in await registry.list_tools(
                caller_kind=CallerKind.AGENT,
                is_owner=True,
            )
        }
        channel_names = {
            tool.name
            for tool in registry.to_tool_definitions(
                ToolContext(is_owner=False, caller_kind=CallerKind.CHANNEL)
            )
        }
        assert "session_search" in owner_names
        assert "session_search" not in channel_names

        await services.session_manager.create("agent:main:main")
        await services.session_manager.append_message(
            "agent:main:main",
            "user",
            "needle transcript detail",
        )

        output = await session_search.handler(query="needle", limit=5)

        assert "needle" in output
        assert "agent:main:main" in output
        assert captured_memory_kwargs["session_storage"] is services.session_manager.storage
    finally:
        await services.close()


def test_router_boot_validation_does_not_load_heavy_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = tmp_path / "v4_bundle"
    (bundle_dir / "runtime_src").mkdir(parents=True)
    (bundle_dir / "router.runtime.yaml").write_text("v4: {}\n", encoding="utf-8")

    config = GatewayConfig()
    config.squilla_router.v4_bundle_dir = str(bundle_dir)
    config.squilla_router.require_router_runtime = True

    real_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "opensquilla.squilla_router.v4_phase3":
            raise AssertionError("boot validation must not load V4Phase3Strategy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    validate_squilla_router_runtime(config)


def test_router_boot_validation_still_fails_when_required_bundle_missing(tmp_path: Path) -> None:
    config = GatewayConfig()
    config.squilla_router.v4_bundle_dir = str(tmp_path / "missing")
    config.squilla_router.require_router_runtime = True

    with pytest.raises(RuntimeError, match="missing V4 bundle files"):
        validate_squilla_router_runtime(config)


def test_skill_filter_banner_accepts_tokenizers_without_transformers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from opensquilla.memory.embedding import LocalEmbeddingProvider

    def fake_find_spec(name: str):
        if name in {"onnxruntime", "tokenizers"}:
            return object()
        if name == "transformers":
            return None
        raise AssertionError(name)

    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)
    monkeypatch.setattr(
        LocalEmbeddingProvider,
        "_bundled_onnx_dir",
        classmethod(lambda cls, model_name: tmp_path),
    )

    emit_skill_filter_banner(
        SimpleNamespace(filter_enabled=True, filter_strategy="semantic", filter_embedding_model="")
    )

    assert "ONNX embedding backend not available" not in caplog.text


@pytest.mark.asyncio
async def test_build_services_fails_fast_for_explicit_remote_memory_without_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "opensquilla.sandbox.integration.configure_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            effective=SimpleNamespace(as_dict=lambda: {})
        ),
    )
    config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        workspace_dir=str(tmp_path / "workspace"),
        memory={"embedding": {"provider": "openai"}},
    )

    with pytest.raises(ValueError, match="memory.embedding.remote.api_key"):
        await build_services(config=config)


def test_configured_agent_ids_include_enabled_registry_agents_and_channels() -> None:
    result = upsert_channel(
        GatewayConfig(
            agents=[
                AgentEntryConfig(id="ops"),
                AgentEntryConfig(id="disabled", enabled=False),
            ]
        ),
        entry_payload={"type": "slack", "name": "work", "token": "x", "agent_id": "channel"},
    )

    assert _configured_agent_ids(result.config) == ["channel", "main", "ops"]


def test_workspace_state_mismatch_emits_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[dict[str, Any]] = []
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "gateway-3"))
    monkeypatch.setenv(
        "OPENSQUILLA_GATEWAY_CONFIG_PATH",
        str(tmp_path / "gateway-3" / "config.toml"),
    )
    monkeypatch.setattr(
        "opensquilla.gateway.boot.log.warning",
        lambda event, **kwargs: warnings.append({"event": event, **kwargs}),
    )
    config = GatewayConfig(
        state_dir=str(tmp_path / "gateway-3" / "state"),
        workspace_dir=str(tmp_path / "gateway-1" / "workspace"),
        config_path=str(tmp_path / "gateway-3" / "config.toml"),
    )

    _warn_workspace_state_mismatch(config)

    assert warnings
    assert warnings[0]["event"] == "build_services.workspace_state_mismatch"
    assert "OPENSQUILLA_STATE_DIR" in warnings[0]["expected_roots"]


def test_dream_defaults_are_fail_closed() -> None:
    config = GatewayConfig()

    assert config.memory.dream.enabled is False
    assert config.memory.dream.preview_mode is True
    assert config.memory.dream.auto_schedule is False


def test_memory_mode_fingerprint_keeps_dream_auto_schedule_visible() -> None:
    config = GatewayConfig(memory={"dream": {"enabled": True}})

    assert config.memory.dream.enabled is True
    assert config.memory.dream.preview_mode is True
    assert config.memory.dream.auto_schedule is False
    assert config.memory_mode_fingerprint()["dream_auto_schedule"] == "false"


@pytest.mark.asyncio
async def test_dream_boot_does_not_register_when_auto_schedule_is_off() -> None:
    scheduler = _FakeDreamScheduler()
    config = GatewayConfig(memory={"dream": {"enabled": True}})

    await _register_dream_crons(
        scheduler=scheduler,
        memory_config=config.memory,
        agent_ids=["main"],
    )

    assert scheduler.added == []


@pytest.mark.asyncio
async def test_dream_boot_pauses_existing_jobs_when_auto_schedule_is_off() -> None:
    existing = CronJob(id="dream-main", name="memory_dream:main", status=JobStatus.PENDING)
    scheduler = _FakeDreamScheduler([existing])
    config = GatewayConfig(memory={"dream": {"enabled": True}})

    await _register_dream_crons(
        scheduler=scheduler,
        memory_config=config.memory,
        agent_ids=["main"],
    )

    assert scheduler.paused == ["dream-main"]
    assert existing.status == JobStatus.PAUSED
    assert scheduler.added == []


@pytest.mark.asyncio
async def test_dream_boot_pauses_existing_jobs_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_MEMORY_DREAM_DISABLED", "1")
    existing = CronJob(id="dream-main", name="memory_dream:main", status=JobStatus.PENDING)
    scheduler = _FakeDreamScheduler([existing])
    config = GatewayConfig(
        memory={"dream": {"enabled": True, "auto_schedule": True}},
    )

    await _register_dream_crons(
        scheduler=scheduler,
        memory_config=config.memory,
        agent_ids=["main"],
    )

    assert scheduler.paused == ["dream-main"]
    assert existing.status == JobStatus.PAUSED
    assert scheduler.added == []


@pytest.mark.asyncio
async def test_task_runtime_turn_uses_agent_registry_model_when_session_has_no_model() -> None:
    class RecordingTurnRunner:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def run(self, message: str, session_key: str, **kwargs: Any):
            self.calls.append(kwargs)
            yield DoneEvent()

    class SessionManager:
        async def get_session(self, session_key: str) -> Any:
            return SimpleNamespace(model=None)

    events: list[tuple[str, str, dict[str, Any]]] = []

    async def emit(session_key: str, event_name: str, payload: dict[str, Any]) -> None:
        events.append((session_key, event_name, payload))

    config = GatewayConfig(
        agents=[AgentEntryConfig(id="ops", model="agent/default")],
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=1.0,
    )
    run = SimpleNamespace(
        agent_id="ops",
        task_id="task-1",
        session_key="agent:ops:task-runtime",
        message="hello",
        envelope=build_cli_route_envelope(
            session_key="agent:ops:task-runtime",
            agent_id="ops",
        ),
        attachments=[],
        input_provenance={},
        run_kind="interactive",
        no_memory_capture=False,
        ingress_pipeline_steps=[],
        semantic_message=None,
        stream_event_sink=None,
    )
    runner = RecordingTurnRunner()

    await dispatch_task_runtime_turn(
        run,
        config=config,
        session_manager=SessionManager(),
        turn_runner=runner,
        event_emitter=emit,
    )

    assert runner.calls[0]["model"] == "agent/default"


@pytest.mark.asyncio
async def test_task_runtime_turn_applies_cron_job_tool_policy() -> None:
    class RecordingTurnRunner:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def run(self, message: str, session_key: str, **kwargs: Any):
            self.calls.append(kwargs)
            yield DoneEvent()

    events: list[tuple[str, str, dict[str, Any]]] = []

    async def emit(session_key: str, event_name: str, payload: dict[str, Any]) -> None:
        events.append((session_key, event_name, payload))

    job = CronJob(
        id="cron-policy",
        name="Policy",
        payload={"kind": "agent_turn", "agent_id": "ops"},
        tool_policy={
            "profile": "minimal",
            "also_allow": ["memory_search", "exec_command"],
            "deny": ["web_fetch"],
        },
    )
    run = SimpleNamespace(
        agent_id="ops",
        task_id="task-1",
        session_key="cron:cron-policy:run:1",
        message="hello",
        envelope=build_cron_route_envelope(
            job,
            session_key="cron:cron-policy:run:1",
            agent_id="ops",
        ),
        attachments=[],
        input_provenance={},
        run_kind="cron_turn",
        no_memory_capture=False,
        ingress_pipeline_steps=[],
        semantic_message=None,
        stream_event_sink=None,
    )
    runner = RecordingTurnRunner()

    await dispatch_task_runtime_turn(
        run,
        config=GatewayConfig(),
        session_manager=None,
        turn_runner=runner,
        event_emitter=emit,
    )

    tool_context = runner.calls[0]["tool_context"]
    assert tool_context.allowed_tools == {"session_status"}
    assert "exec_command" in tool_context.denied_tools
    assert "web_fetch" in tool_context.denied_tools


@pytest.mark.asyncio
async def test_task_runtime_turn_uses_owner_boundary_for_owner_cron_job() -> None:
    class RecordingTurnRunner:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def run(self, message: str, session_key: str, **kwargs: Any):
            self.calls.append(kwargs)
            yield DoneEvent()

    async def emit(session_key: str, event_name: str, payload: dict[str, Any]) -> None:
        return None

    job = CronJob(
        id="cron-owner",
        name="Owner",
        payload={"kind": "agent_turn", "agent_id": "ops"},
        creator_is_owner=True,
        tool_policy={
            "profile": "minimal",
            "also_allow": ["memory_search", "exec_command"],
            "deny": ["web_fetch"],
        },
    )
    run = SimpleNamespace(
        agent_id="ops",
        task_id="task-1",
        session_key="cron:cron-owner:run:1",
        message="hello",
        envelope=build_cron_route_envelope(
            job,
            session_key="cron:cron-owner:run:1",
            agent_id="ops",
        ),
        attachments=[],
        input_provenance={},
        run_kind="cron_turn",
        no_memory_capture=False,
        ingress_pipeline_steps=[],
        semantic_message=None,
        stream_event_sink=None,
    )
    runner = RecordingTurnRunner()

    await dispatch_task_runtime_turn(
        run,
        config=GatewayConfig(),
        session_manager=None,
        turn_runner=runner,
        event_emitter=emit,
    )

    tool_context = runner.calls[0]["tool_context"]
    assert tool_context.is_owner is True
    assert tool_context.allowed_tools is None
    assert tool_context.tool_policy == job.tool_policy
    assert "exec_command" not in tool_context.denied_tools
