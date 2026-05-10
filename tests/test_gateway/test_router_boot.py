from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine.types import DoneEvent
from opensquilla.gateway.boot import (
    _configured_agent_ids,
    _register_dream_crons,
    _warn_workspace_state_mismatch,
    build_flush_service,
    build_services,
    dispatch_task_runtime_turn,
    validate_squilla_router_runtime,
)
from opensquilla.gateway.config import AgentEntryConfig, GatewayConfig
from opensquilla.gateway.diagnostics import DiagnosticsState
from opensquilla.gateway.routing import build_cli_route_envelope, build_cron_route_envelope
from opensquilla.onboarding.mutations import upsert_channel
from opensquilla.scheduler.types import CronJob, JobStatus
from opensquilla.tools.registry import ToolRegistry


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


def test_build_flush_service_respects_memory_flush_enabled_config() -> None:
    service = build_flush_service(
        tool_registry=ToolRegistry(),
        provider_selector=SimpleNamespace(resolve=lambda: object()),
        config=GatewayConfig(memory={"flush_enabled": False}),
    )

    assert service is None


def test_build_flush_service_uses_configured_memory_timeout() -> None:
    service = build_flush_service(
        tool_registry=ToolRegistry(),
        provider_selector=SimpleNamespace(resolve=lambda: object()),
        config=GatewayConfig(memory={"flush_timeout_seconds": 0.25}),
    )

    assert service is not None
    assert service._default_timeout == 0.25


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
    assert tool_context.allowed_tools == {"session_status", "memory_search"}
    assert "exec_command" in tool_context.denied_tools
    assert "web_fetch" in tool_context.denied_tools
