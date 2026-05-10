"""Boot sequence orchestration for the gateway."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opensquilla.engine.usage import UsageTracker
    from opensquilla.memory.manager import MemoryManager
    from opensquilla.memory.store import LongTermMemoryStore
    from opensquilla.memory.sync_manager import (
        MemorySyncManager as MemoryFileWatcher,  # SyncManager replaces watcher
    )
    from opensquilla.provider.model_catalog import ModelCatalog
    from opensquilla.provider.selector import ModelSelector
    from opensquilla.scheduler import SchedulerEngine
    from opensquilla.session.manager import SessionManager
    from opensquilla.skills.loader import SkillLoader
    from opensquilla.tools.registry import ToolRegistry

import structlog
import uvicorn
from starlette.applications import Starlette

from opensquilla.agents.scope import resolve_agent_model, resolve_agent_workspace_dir
from opensquilla.asyncio_utils import create_background_task
from opensquilla.engine.usage import UsageTracker as _UsageTracker
from opensquilla.gateway.app import create_gateway_app
from opensquilla.gateway.config import GatewayConfig, is_public_bind
from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config
from opensquilla.gateway.rpc import get_dispatcher
from opensquilla.gateway.session_services import get_session_storage
from opensquilla.gateway.session_streams import get_session_streams
from opensquilla.gateway.websocket import get_registry
from opensquilla.paths import default_opensquilla_home

log = structlog.get_logger(__name__)

_DEBUG_FILE_HANDLER_ATTR = "_opensquilla_debug_file_handler"
_ENABLED_VALUES = {"1", "true", "yes", "on"}
_DISABLED_VALUES = {"0", "false", "no", "off"}
_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.FATAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "TRACE": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


# fmt: off
def _make_channel_rpc_context_factory(svc: ServiceContainer, config: GatewayConfig, *, subscription_manager: Any, channel_manager_ref: Any, turn_runner: Any, heartbeat_service: Any) -> Any:  # noqa: E501
    from opensquilla.channels.command_registry import build_channel_rpc_context

    def _factory(envelope: Any) -> Any:
        names = ("session_manager", "provider_selector", "tool_registry", "usage_tracker", "skill_loader", "cron_scheduler", "task_runtime", "flush_service", "heartbeat_loop", "agent_registry", "memory_managers", "memory_stores", "memory_retrievers")  # noqa: E501
        return build_channel_rpc_context(
            envelope,
            gateway_config=config,
            **{name: getattr(svc, name) for name in names},
            subscription_manager=subscription_manager,
            channel_manager=channel_manager_ref(),
            turn_runner=turn_runner,
            heartbeat_service=heartbeat_service,
        )

    return _factory
# fmt: on


def _interval_h_to_schedule_raw(interval_h: int) -> str:
    """Render an interval schedule accepted by the scheduler parser."""
    return f"every {interval_h}h"


async def _list_scheduler_jobs(scheduler: Any) -> list[Any]:
    list_jobs = getattr(scheduler, "list_jobs", None)
    if not callable(list_jobs):
        return []
    try:
        result = list_jobs()
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:  # noqa: BLE001
        log.warning("boot.dream.list_jobs_failed", error=str(exc))
        return []
    return result if isinstance(result, list) else []


async def _register_dream_crons(
    *,
    scheduler: Any,
    memory_config: Any,
    agent_ids: list[str],
) -> None:
    """Register a `memory_dream` cron per agent when enabled.

    Respects the ``OPENSQUILLA_MEMORY_DREAM_DISABLED=1`` kill switch.
    Prefers ``memory_config.dream.cron`` if set, else derives
    ``every Nh`` from ``interval_h``.
    """
    import os

    from opensquilla.scheduler.types import SessionTarget

    dream_cfg = getattr(memory_config, "dream", None)
    existing_jobs = await _list_scheduler_jobs(scheduler)
    existing_by_name = {
        getattr(job, "name", ""): job
        for job in existing_jobs
        if getattr(job, "name", "").startswith("memory_dream:")
    }
    disabled_reason = None
    if os.getenv("OPENSQUILLA_MEMORY_DREAM_DISABLED") == "1":
        disabled_reason = "kill_switch"
    elif dream_cfg is None or not getattr(dream_cfg, "enabled", False):
        disabled_reason = "disabled"
    elif not getattr(dream_cfg, "auto_schedule", False):
        disabled_reason = "auto_schedule_disabled"

    if disabled_reason is not None:
        await _pause_dream_crons(
            scheduler=scheduler,
            jobs=list(existing_by_name.values()),
            reason=disabled_reason,
        )
        return

    assert dream_cfg is not None
    schedule_raw = (
        dream_cfg.cron
        if getattr(dream_cfg, "cron", None)
        else _interval_h_to_schedule_raw(dream_cfg.interval_h)
    )
    for agent_id in agent_ids:
        name = f"memory_dream:{agent_id}"
        existing = existing_by_name.get(name)
        if existing is not None:
            patch: dict[str, Any] = {}
            if getattr(existing, "schedule_raw", "") != schedule_raw:
                patch["schedule_raw"] = schedule_raw
            if getattr(existing, "payload", {}).get("agent_id") != agent_id:
                patch["payload"] = {"agent_id": agent_id}
            if getattr(existing, "session_target", None) != SessionTarget.ISOLATED:
                patch["session_target"] = SessionTarget.ISOLATED
            update_job = getattr(scheduler, "update_job", None)
            if patch and callable(update_job):
                result = update_job(getattr(existing, "id"), **patch)
                if inspect.isawaitable(result):
                    await result
            log.info(
                "boot.dream.already_registered",
                agent_id=agent_id,
                schedule=schedule_raw,
            )
            continue

        await scheduler.add_job(
            name=name,
            schedule_raw=schedule_raw,
            handler_key="memory_dream",
            payload={"agent_id": agent_id},
            session_target=SessionTarget.ISOLATED,
        )
        log.info(
            "boot.dream.registered",
            agent_id=agent_id,
            schedule=schedule_raw,
        )


async def _pause_dream_crons(*, scheduler: Any, jobs: list[Any], reason: str) -> None:
    """Pause managed Dream cron jobs so persisted rows cannot bypass config."""
    pause_job = getattr(scheduler, "pause_job", None)
    update_job = getattr(scheduler, "update_job", None)
    for job in jobs:
        status = getattr(getattr(job, "status", None), "value", getattr(job, "status", ""))
        if status in {"paused", "disabled", "deleted"}:
            continue
        job_id = getattr(job, "id", None)
        if not job_id:
            continue
        try:
            if callable(pause_job):
                result = pause_job(job_id)
            elif callable(update_job):
                result = update_job(job_id, enabled=False)
            else:
                continue
            if inspect.isawaitable(result):
                await result
            log.info(
                "boot.dream.paused",
                job_id=job_id,
                name=getattr(job, "name", ""),
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "boot.dream.pause_failed",
                job_id=job_id,
                reason=reason,
                error=str(exc),
            )


@dataclass
class ServiceContainer:
    """Typed container for initialized services. Returned by build_services().

    WARNING: build_services() mutates module-level state:
    - tools.builtin.memory_tools (create_memory_tools)
    - tools.builtin.skill_tools (create_skill_tools)
    - tools.builtin.admin (set_gateway_config, set_scheduler)
    - search.providers (configure_search)
    Do not call build_services() twice in the same process without
    understanding these side effects.
    """

    config: GatewayConfig
    provider_selector: ModelSelector | None = None
    tool_registry: ToolRegistry | None = None
    session_manager: SessionManager | None = None
    skill_loader: SkillLoader | None = None
    usage_tracker: UsageTracker | None = None
    cron_scheduler: SchedulerEngine | None = None
    model_catalog: ModelCatalog | None = None
    agent_registry: Any = None
    memory_managers: dict[str, MemoryManager] = field(default_factory=dict)
    # Legacy per-tier dicts. As of Step 1A these are derived views over
    # `memory_managers` populated in build_services(); direct ServiceContainer
    # constructors (e.g. tests) may still set them independently. Step 1B
    # will collapse the consumers in TurnRunner / CLI onto `memory_managers`,
    # at which point these legacy fields can be removed.
    memory_stores: dict[str, LongTermMemoryStore] = field(default_factory=dict)
    memory_sync_managers: dict[str, MemoryFileWatcher] = field(default_factory=dict)
    memory_watchers: list[MemoryFileWatcher] = field(default_factory=list)
    memory_retrievers: dict[str, Any] = field(default_factory=dict)
    turn_capture_services: dict[str, Any] = field(default_factory=dict)
    flush_service: Any = None  # SessionFlushService | None (gated by OPENSQUILLA_SESSION_FLUSH)
    task_runtime: Any = None
    heartbeat_loop: Any = None
    heartbeat_watcher: Any = None

    # Backward-compat alias — returns the "main" store (or None).
    @property
    def memory_store(self) -> LongTermMemoryStore | None:
        return self.memory_stores.get("main")

    async def close(self) -> None:
        """Teardown async resources. Idempotent — safe to call twice.

        Ordering rule: scheduled producers (heartbeat watcher/loop and the
        cron scheduler) MUST stop before the memory tier closes; otherwise
        an in-flight cron job or heartbeat tick can drive TurnRunner ->
        TurnCaptureService.capture_turn against an already-closed store.
        """
        # ── 1. Stop scheduled producers (no further writes after this) ──
        if self.heartbeat_watcher is not None:
            try:
                await self.heartbeat_watcher.stop()
            except Exception:
                pass
        if self.heartbeat_loop is not None:
            try:
                await self.heartbeat_loop.stop()
            except Exception:
                pass
        if self.cron_scheduler is not None:
            try:
                await self.cron_scheduler.stop()
            except Exception:
                pass
            store = getattr(self.cron_scheduler, "_store", None)
            if store is not None and hasattr(store, "close"):
                try:
                    await store.close()
                except Exception:
                    pass
        if self.task_runtime is not None:
            try:
                await self.task_runtime.shutdown()
            except Exception:
                pass
            try:
                from opensquilla.tools.builtin.sessions import set_task_runtime

                set_task_runtime(None)
            except Exception:
                pass

        # ── 2. Tear down memory tier through MemoryManager ──
        # In real boot, the legacy `memory_watchers` / `memory_stores` below
        # are the SAME object identities as those reachable via memory_managers,
        # so the subsequent loops are no-op double-stops/closes (both sync_manager
        # and store close are idempotent — see memory/store.py:642 and
        # memory/sync_manager.py:104). Direct ServiceContainer constructors that
        # only populate the legacy fields (e.g. tests) still get torn down by the
        # legacy paths.
        #
        # Retrievers run BEFORE managers so any in-flight search cleanup runs
        # before the underlying DB connection is closed. Per-retriever timeout
        # prevents one wedged retriever from stalling the entire shutdown.
        for retriever in self.memory_retrievers.values():
            try:
                await asyncio.wait_for(retriever.close(), timeout=5.0)
            except (TimeoutError, Exception) as e:  # noqa: BLE001 — fail-open shutdown
                log.warning("retriever_close_failed_or_timed_out", error=str(e))
        for mgr in self.memory_managers.values():
            try:
                await mgr.close()
            except Exception:
                pass
        for watcher in self.memory_watchers:
            try:
                await watcher.stop()
            except Exception:
                pass
        for store in self.memory_stores.values():
            try:
                await store.close()
            except Exception:
                pass
        if self.session_manager is not None:
            storage = get_session_storage(self.session_manager)
            if storage and hasattr(storage, "close"):
                try:
                    await storage.close()
                except Exception:
                    pass


# Server boot timestamp (set once at first start)
_boot_time_ms: int = 0


def _configured_agent_ids(
    config: GatewayConfig,
    extra: list[str] | None = None,
) -> list[str]:
    """Return agent ids declared by config plus the default main agent.

    ``extra`` lets a caller (e.g. the one-shot CLI runner) opt in additional
    runtime agent ids that are not declared in ``config.channels`` so the
    memory manager / workspace seeding still build per-agent resources for
    them. Legacy ``default`` aliases to the canonical ``main`` agent.
    """
    from opensquilla.session.keys import normalize_agent_id

    declared = {
        normalize_agent_id(getattr(e, "agent_id", "main")) for e in config.channels.channels
    }
    declared.add("main")
    for entry in getattr(config, "agents", []):
        if getattr(entry, "enabled", True):
            declared.add(normalize_agent_id(getattr(entry, "id", "")))
    if extra:
        declared.update(normalize_agent_id(a) for a in extra if a)
    return sorted(declared)


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolved_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve(strict=False)
    except (OSError, ValueError):
        return None


def _warn_workspace_state_mismatch(config: GatewayConfig) -> None:
    workspace = _resolved_path(getattr(config, "workspace_dir", None))
    if workspace is None:
        return

    expected_roots: dict[str, Path] = {}
    env_state = _resolved_path(os.environ.get("OPENSQUILLA_STATE_DIR"))
    if env_state is not None:
        expected_roots["OPENSQUILLA_STATE_DIR"] = env_state
    env_config = _resolved_path(os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))
    if env_config is not None:
        expected_roots["OPENSQUILLA_GATEWAY_CONFIG_PATH"] = env_config.parent
    config_state = _resolved_path(getattr(config, "state_dir", None))
    if config_state is not None:
        expected_roots["config.state_dir"] = config_state.parent
    config_path = _resolved_path(getattr(config, "config_path", None))
    if config_path is not None:
        expected_roots["config.config_path"] = config_path.parent

    mismatches = {
        source: str(root)
        for source, root in expected_roots.items()
        if not _path_is_relative_to(workspace, root)
    }
    if not mismatches:
        return
    log.warning(
        "build_services.workspace_state_mismatch",
        workspace=str(workspace),
        state_dir=getattr(config, "state_dir", None),
        config_path=getattr(config, "config_path", None),
        expected_roots=mismatches,
    )


def _ensure_configured_agent_workspaces(
    config: GatewayConfig,
    *,
    extra_agent_ids: list[str] | None = None,
) -> None:
    """Seed bootstrap templates for explicitly configured agent workspaces."""
    if not config.workspace_dir:
        return

    from opensquilla.identity.bootstrap import ensure_agent_workspace

    for agent_id in _configured_agent_ids(config, extra_agent_ids):
        result = ensure_agent_workspace(resolve_agent_workspace_dir(agent_id, config))
        log.info(
            "build_services.agent_workspace_ready",
            agent_id=agent_id,
            workspace=str(result.workspace_dir),
            created_files=list(result.created_files),
            bootstrap_seeded=result.bootstrap_seeded,
            bootstrap_completed=result.bootstrap_completed,
        )


def _state_path(config: GatewayConfig, filename: str) -> Path:
    state_root = Path(config.state_dir or default_opensquilla_home() / "state")
    return state_root / filename


def _task_runtime_max_concurrency(config: GatewayConfig) -> int:
    return int(config.task_runtime.max_concurrency)


def _task_runtime_max_pending_per_session(config: GatewayConfig) -> int:
    return int(config.task_runtime.max_pending_per_session)


def _task_runtime_envelope_owner(envelope: Any) -> bool:
    """Resolve owner privileges from authenticated route metadata."""
    from opensquilla.gateway.routing import SourceKind

    principal_is_owner = getattr(envelope, "metadata", {}).get("principal_is_owner")
    if isinstance(principal_is_owner, bool):
        return principal_is_owner
    return getattr(envelope, "source_kind", None) == SourceKind.CLI


async def dispatch_task_runtime_turn(
    run: Any,
    *,
    config: Any,
    session_manager: Any,
    turn_runner: Any,
    event_emitter: Any,
) -> None:
    """Drive ``turn_runner.run`` for one ``TaskRun``.

    Pure coroutine extracted from ``build_services``'s
    ``_task_runtime_turn_handler`` closure. Module-level so a
    boot-wiring regression test can drive it with a fake ``turn_runner``
    and capture every kwarg actually flowing into ``turn_runner.run``
    (including the ``semantic_message`` regression surface).
    """
    from opensquilla.gateway.routing import tool_context_from_envelope

    workspace_dir = resolve_agent_workspace_dir(run.agent_id, config)
    workspace_strict = getattr(config, "workspace_strict", None)
    if not isinstance(workspace_strict, bool):
        workspace_strict = bool(workspace_dir)
    is_owner = _task_runtime_envelope_owner(run.envelope)
    tool_context = tool_context_from_envelope(
        run.envelope,
        is_owner=is_owner,
        workspace_dir=str(workspace_dir),
        workspace_strict=workspace_strict,
    )
    tool_context.task_id = run.task_id
    session = None
    if session_manager is not None and hasattr(session_manager, "get_session"):
        session = await session_manager.get_session(run.session_key)
    run_kwargs = build_task_runtime_run_kwargs(
        run,
        tool_context=tool_context,
        model=resolve_agent_model(
            run.agent_id,
            config,
            session_model=getattr(session, "model", None),
        ),
    )
    raw_stream = turn_runner.run(run.message, run.session_key, **run_kwargs)
    stream_idle_timeout = _optional_positive_timeout(
        config, "agent_stream_idle_timeout_seconds", 180.0
    )
    heartbeat_interval = _optional_positive_timeout(
        config, "agent_stream_heartbeat_interval_seconds", 15.0
    )
    await _emit_task_runtime_stream_events(
        raw_stream,
        run.session_key,
        event_emitter,
        idle_timeout=stream_idle_timeout,
        heartbeat_interval=heartbeat_interval,
        stream_event_sink=getattr(run, "stream_event_sink", None),
    )


def build_task_runtime_run_kwargs(
    run: Any,
    *,
    tool_context: Any,
    model: str | None,
) -> dict[str, Any]:
    """Build kwargs for ``turn_runner.run`` from a ``TaskRun``.

    Pure helper extracted from ``_task_runtime_turn_handler`` so the
    boot-level link of the recall-prefetch chain is directly
    testable: a regression that drops ``semantic_message`` forwarding
    here is caught by ``test_boot_task_runtime_kwargs.py`` without
    requiring a live gateway.
    """
    ingress_steps = list(run.ingress_pipeline_steps) or None
    kwargs: dict[str, Any] = {
        "tool_context": tool_context,
        "agent_id": run.agent_id,
        "model": model,
        "attachments": run.attachments,
        "input_provenance": run.input_provenance,
        "run_kind": run.run_kind,
        "no_memory_capture": run.no_memory_capture,
        "ingress_pipeline_steps": ingress_steps,
    }
    if run.semantic_message is not None:
        # Prefetch query shape: channels carry the raw user text
        # separately from the (potentially stamped) persisted message.
        # Only forward when set so web/CLI legacy paths keep
        # ``TurnRunner.run`` falling back to ``message`` as semantic input.
        kwargs["semantic_message"] = run.semantic_message
    return kwargs


def build_cron_result_payload(
    origin_session_key: str,
    text: str,
    entry: Any,
) -> dict[str, Any]:
    """Build the WS payload for a ``session.event.cron_result`` broadcast.

    Pure helper extracted from the cron-forwarder closure so the wire
    contract is testable by gate 4 without spinning up a live gateway.
    The web frontend at ``chat.js:727`` and any other ``cron_result``
    subscriber relies on these exact keys.
    """
    return {
        "sessionKey": origin_session_key,
        "message": {
            "role": "assistant",
            "text": text,
            "timestamp": getattr(entry, "created_at", None),
            "provenanceKind": getattr(entry, "provenance_kind", None),
            "provenanceSourceTool": getattr(entry, "provenance_source_tool", None),
            "provenanceSourceSessionKey": getattr(entry, "provenance_source_session_key", None),
        },
    }


def build_sessions_changed_payload(session_key: str, reason: str) -> dict[str, str]:
    """Build the WS payload for a ``sessions.changed`` broadcast.

    Trivial helper — but having one symbol is the only way to ground a
    gate-4 snapshot in actual production code rather than an invented
    literal that production drift would silently ignore. Sites that
    emit this event must call this helper.
    """
    return {"key": session_key, "reason": reason}


def _optional_positive_timeout(config: Any, attr: str, default: float) -> float | None:
    raw = getattr(config, attr, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else None


async def _emit_task_runtime_stream_events(
    raw_stream: Any,
    session_key: str,
    event_emitter: Any,
    *,
    idle_timeout: float | None = 180.0,
    heartbeat_interval: float | None = None,
    stream_event_sink: Any = None,
) -> None:
    """Emit turn events and fail the task if the stream reports an error."""
    from dataclasses import asdict, is_dataclass

    from opensquilla.engine.stream_wrappers import wrap_stream

    error_message: str | None = None
    async for event in wrap_stream(
        raw_stream,
        idle_timeout=idle_timeout,
        heartbeat_interval=heartbeat_interval,
        heartbeat_message="Agent run is still active",
    ):
        if stream_event_sink is not None:
            try:
                result = stream_event_sink(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.debug(
                    "task_runtime.stream_event_sink_failed",
                    session_key=session_key,
                    event_kind=getattr(event, "kind", event.__class__.__name__),
                    exc_info=True,
                )
        if is_dataclass(event):
            event_dict = asdict(event)
        else:
            event_dict = {
                key: value
                for key, value in getattr(event, "__dict__", {}).items()
                if not key.startswith("_")
            }
        event_kind = event_dict.pop("kind", getattr(event, "kind", event.__class__.__name__))
        await event_emitter(
            session_key,
            f"session.event.{event_kind}",
            event_dict,
        )
        if event_kind == "error":
            message = event_dict.get("message")
            error_message = message if isinstance(message, str) and message else "Agent error"
    if error_message is not None:
        raise RuntimeError(error_message)


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in _ENABLED_VALUES:
        return True
    if value in _DISABLED_VALUES:
        return False
    return None


def _resolve_log_level(config: GatewayConfig) -> int:
    raw = os.environ.get("OPENSQUILLA_LOG_LEVEL") or config.log_level
    return _LOG_LEVELS.get(str(raw).strip().upper(), logging.DEBUG)


def _remove_debug_file_handlers(root: logging.Logger) -> None:
    opensquilla_logger = logging.getLogger("opensquilla")
    for handler in list(root.handlers):
        if getattr(handler, _DEBUG_FILE_HANDLER_ATTR, False):
            previous_level = getattr(handler, "_opensquilla_previous_logger_level", None)
            root.removeHandler(handler)
            handler.close()
            if isinstance(previous_level, int):
                opensquilla_logger.setLevel(previous_level)


def _setup_file_logging(config: GatewayConfig | None = None) -> None:
    """Configure structlog + stdlib logging to write to a debug.log file."""
    config = config or GatewayConfig()
    root = logging.getLogger()
    _remove_debug_file_handlers(root)

    enabled = _env_bool("OPENSQUILLA_LOG_FILE_ENABLED")
    if enabled is None:
        enabled = config.log_file_enabled
    if not enabled:
        return

    log_dir = Path(os.environ.get("OPENSQUILLA_LOG_DIR", str(default_opensquilla_home() / "logs")))
    log_level = _resolve_log_level(config)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "debug.log"
        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=config.log_file_max_bytes,
            backupCount=config.log_file_backup_count,
            encoding="utf-8",
        )
    except OSError as exc:
        logging.getLogger(__name__).warning("file logging disabled: %s", exc)
        return
    setattr(file_handler, _DEBUG_FILE_HANDLER_ATTR, True)
    opensquilla_logger = logging.getLogger("opensquilla")
    setattr(file_handler, "_opensquilla_previous_logger_level", opensquilla_logger.level)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    root.addHandler(file_handler)
    opensquilla_logger.setLevel(log_level)


@dataclass
class GatewayServer:
    """Handle returned after gateway startup. Provides close() method."""

    app: Starlette
    config: GatewayConfig
    _server: uvicorn.Server | None = field(default=None, repr=False)
    _task: asyncio.Task | None = field(default=None, repr=False)
    _channel_manager: Any = field(default=None, repr=False)
    _services: ServiceContainer | None = field(default=None, repr=False)
    _background_completion_manager: Any = field(default=None, repr=False)

    async def close(self, reason: str = "shutdown") -> None:
        """Gracefully shut down: stop channels, broadcast shutdown, close WS, stop server."""
        # Drain in-flight turns FIRST so replies are not lost.
        # task_runtime.shutdown() waits for all running turns to complete before
        # returning; only then do we stop channel delivery.
        if self._services is not None and self._services.task_runtime is not None:
            try:
                await self._services.task_runtime.shutdown(
                    graceful=True, graceful_timeout=30.0
                )
            except Exception:
                pass

        if self._background_completion_manager is not None:
            try:
                await self._background_completion_manager.close(timeout=30.0)
            except Exception:
                log.debug("gateway.background_completion_close_failed", exc_info=True)
            try:
                from opensquilla.gateway.subagent_announce import set_background_completion_manager

                set_background_completion_manager(None)
            except Exception:
                pass
            self._background_completion_manager = None

        # Stop channels after task_runtime is drained (no in-flight turns remain)
        if self._channel_manager is not None:
            await self._channel_manager.stop_all()
            log.info("gateway.channels_stopped")

        registry = get_registry()
        await registry.broadcast("shutdown", {"reason": reason})

        # Close all active WS connections
        for conn in registry.all():
            await conn.close()

        # Close MCP clients
        try:
            from opensquilla.mcp.discovery import close_active_clients

            await close_active_clients()
            log.info("gateway.mcp_clients_closed")
        except ImportError:
            pass

        if self._server is not None:
            self._server.should_exit = True

        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except TimeoutError:
                self._task.cancel()

        if self._services is not None:
            await self._services.close()

        log.info("gateway.stopped", reason=reason)


def build_flush_service(
    *,
    tool_registry: Any,
    provider_selector: Any,
    config: GatewayConfig | None = None,
) -> Any:
    """Construct a :class:`SessionFlushService` gated by flush config.

    Returns ``None`` when the kill-switch env var or gateway memory config
    disables flush. Otherwise returns a service wired to the gateway's tool
    registry and provider selector. ``agent_id`` is threaded through the
    callable signature for future multi-agent support, but today OpenSquilla
    uses a single ModelSelector so we just call its ``resolve()`` and ignore
    the agent id.
    """
    from opensquilla.memory.flush_config import is_session_flush_enabled

    if not is_session_flush_enabled():
        return None
    memory_cfg = getattr(config, "memory", None)
    if memory_cfg is not None and not getattr(memory_cfg, "flush_enabled", True):
        return None

    from opensquilla.memory.session_flush import SessionFlushService
    from opensquilla.tools.dispatch import build_tool_handler

    tool_handler = build_tool_handler(tool_registry)

    def _resolve_provider(_agent_id: str) -> Any:
        if provider_selector is None:
            return None
        resolver = getattr(provider_selector, "resolve", None)
        if resolver is None:
            return None
        try:
            return resolver()
        except Exception:  # noqa: BLE001
            return None

    service_kwargs: dict[str, Any] = {}
    if memory_cfg is not None:
        service_kwargs["default_timeout"] = getattr(
            memory_cfg,
            "flush_timeout_seconds",
            30.0,
        )

    return SessionFlushService(
        provider_selector=_resolve_provider,
        tool_registry=tool_registry,
        tool_handler=tool_handler,
        **service_kwargs,
    )


def emit_skill_filter_banner(skills_cfg: Any) -> None:
    """One-line startup warning when the ONNX embedding backend is
    unreachable but a non-lexical filter strategy is configured.

    Required runtime: ``onnxruntime`` + ``transformers`` (tokenizer) +
    the bundled v4 BGE ONNX dir (or a configured override). All three
    ship via ``uv sync --extra recommended``. The previous non-ONNX
    fallback was removed — there is now exactly one backend.

    The banner fires only when filter_enabled=true, strategy ≠ lexical,
    AND the ONNX path is incomplete. Uses stdlib :mod:`logging` so
    operators see it on the standard ``WARNING`` logger and so tests
    can assert on it via ``caplog``.
    """
    import importlib.util
    import logging

    log_std = logging.getLogger("opensquilla.gateway.boot")

    if not getattr(skills_cfg, "filter_enabled", False):
        return
    if getattr(skills_cfg, "filter_strategy", "lexical") == "lexical":
        return

    onnx_ok = False
    try:
        if importlib.util.find_spec("onnxruntime") is not None and importlib.util.find_spec(
            "transformers"
        ) is not None:
            from opensquilla.memory.embedding import LocalEmbeddingProvider

            model_name = getattr(
                skills_cfg, "filter_embedding_model", LocalEmbeddingProvider.DEFAULT_MODEL
            )
            onnx_ok = LocalEmbeddingProvider._bundled_onnx_dir(model_name) is not None
    except ImportError:
        onnx_ok = False

    if onnx_ok:
        return

    log_std.warning(
        "ONNX embedding backend not available; filter_strategy=%r will run "
        "lexical-only. Install via `uv sync --extra recommended` to get "
        "onnxruntime + transformers, and verify the bundled BGE ONNX dir "
        "is present.",
        getattr(skills_cfg, "filter_strategy", "lexical"),
    )


def _squilla_router_bundle_dir(router_cfg: Any) -> Path:
    configured = getattr(router_cfg, "v4_bundle_dir", None)
    if configured:
        return Path(configured).expanduser()
    return (
        Path(__file__).resolve().parents[1]
        / "squilla_router"
        / "models"
        / "v4.2_phase3_inference"
    )


def validate_squilla_router_runtime(config: GatewayConfig) -> None:
    """Validate router assets without loading the heavy ML runtime."""
    router_cfg = getattr(config, "squilla_router", None)
    if router_cfg is None or not getattr(router_cfg, "enabled", False):
        return

    strategy = getattr(router_cfg, "strategy", "v4_phase3")
    if strategy != "v4_phase3":
        log.warning("build_services.squilla_router_removed_strategy", strategy=strategy)

    bundle_dir = _squilla_router_bundle_dir(router_cfg)
    required = ("runtime_src", "router.runtime.yaml")
    missing = [name for name in required if not (bundle_dir / name).exists()]
    if missing:
        message = f"missing V4 bundle files in {bundle_dir}: {missing}"
        if getattr(router_cfg, "require_router_runtime", False):
            raise RuntimeError(message)
        log.warning(
            "build_services.squilla_router_bundle_missing",
            bundle_dir=str(bundle_dir),
            missing=missing,
        )
        return
    log.info("build_services.squilla_router_bundle_ready", bundle_dir=str(bundle_dir))


def _preload_squilla_router_strategy(router_cfg: Any) -> object:
    from opensquilla.engine.steps.squilla_router import preload_strategy

    return preload_strategy(router_cfg)


async def preload_squilla_router_runtime(config: GatewayConfig) -> None:
    router_cfg = getattr(config, "squilla_router", None)
    if router_cfg is None or not getattr(router_cfg, "enabled", False):
        return

    bundle_dir = _squilla_router_bundle_dir(router_cfg)
    try:
        log.info("gateway.squilla_router_preload_started", bundle_dir=str(bundle_dir))
        strategy = await asyncio.to_thread(_preload_squilla_router_strategy, router_cfg)
        if getattr(strategy, "_available", False):
            log.info("gateway.squilla_router_preloaded", bundle_dir=str(bundle_dir))
            return
        if getattr(router_cfg, "require_router_runtime", False):
            raise RuntimeError("V4 Phase 3 router did not become available")
        log.warning("gateway.squilla_router_preload_unavailable", bundle_dir=str(bundle_dir))
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "gateway.squilla_router_preload_failed",
            bundle_dir=str(bundle_dir),
            error=str(exc),
        )


async def build_services(
    config: GatewayConfig | None = None,
    session_manager: Any = None,
    provider_selector: Any = None,
    tool_registry: Any = None,
    usage_tracker: Any = None,
    session_db_path: str = ":memory:",
    extra_agent_ids: list[str] | None = None,
) -> ServiceContainer:
    """Initialize reusable services without any gateway-specific side effects.

    This is the standalone entry point for service construction. It builds
    all the pieces that both the ASGI gateway and the CLI ``--standalone``
    path need: session storage, provider selector, tool registry, memory,
    skills, scheduler, search, and MCP discovery.

    Parameters that are *None* are auto-constructed from *config* defaults.
    Pass explicit instances to override (useful for tests and embedding).

    Returns a populated :class:`ServiceContainer`.
    """
    # ── Load .env files (cwd/.env > ~/.opensquilla/.env, never override existing) ──
    from opensquilla.env import load_env

    load_env()

    # ── Config ──────────────────────────────────────────────────────
    if config is None:
        config = GatewayConfig.load(os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))
        if config.config_path:
            log.info("build_services.config_loaded", path=config.config_path)
    _warn_workspace_state_mismatch(config)

    validate_squilla_router_runtime(config)
    from opensquilla.memory.embedding_resolver import resolve_memory_embedding

    resolve_memory_embedding(config.memory, local_available=lambda *_: False)
    _ensure_configured_agent_workspaces(config, extra_agent_ids=extra_agent_ids)

    # Inject config into admin tool (needed by both gateway and standalone)
    from opensquilla.tools.builtin.admin import set_gateway_config

    set_gateway_config(config)

    # ── Sandbox runtime ─────────────────────────────────────────────
    # validate_combination emits structured warnings; configure_runtime
    # assembles the backend + gate + ledger so tool handlers can call
    # through the ``@sandboxed`` decorator.
    try:
        from opensquilla.sandbox.integration import configure_runtime

        effective = configure_runtime(
            config.sandbox,
            workspace=Path(config.workspace_dir) if config.workspace_dir else None,
        )
        log.info(
            "build_services.sandbox_ready",
            **effective.effective.as_dict(),
        )
    except Exception as e:  # pragma: no cover - boot diagnostics only
        log.exception("build_services.sandbox_configure_failed", error=str(e))
        raise

    # ── Schema migrations (before any DB connects) ──────────────────
    # Runs pending migrations on the session DB before SessionStorage opens it,
    # so SQLModel-backed tables (SessionNode, TranscriptEntry, SessionSummary)
    # see the expected columns. Skipped for in-memory DBs (CLI standalone) —
    # yoyo would operate on a separate in-memory connection from storage.
    # Migration failures propagate: code ships behind the migration, never
    # ahead of it — silently booting on an out-of-date schema is worse than
    # failing loud. See docs/architecture/schema-migration.md.
    if session_db_path != ":memory:":
        from opensquilla.persistence.migrator import apply_pending

        if "://" not in session_db_path:
            Path(session_db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        env_migrations_dir = os.environ.get("OPENSQUILLA_MIGRATIONS_DIR")
        if env_migrations_dir:
            migrations_dir = Path(env_migrations_dir)
        else:
            migrations_dir = Path(__file__).resolve().parents[3] / "migrations"
        applied = apply_pending(session_db_path, migrations_dir)
        if applied:
            log.info("build_services.migrations_applied", count=len(applied), ids=applied)

    # ── Agent registry (built early so SessionManager can resolve agent configs) ─
    from opensquilla.agents.registry import AgentRegistry

    agent_registry = AgentRegistry(config)

    # ── Session manager ─────────────────────────────────────────────
    if session_manager is None:
        from opensquilla.session.manager import SessionManager
        from opensquilla.session.storage import SessionStorage

        Path(session_db_path).parent.mkdir(parents=True, exist_ok=True)
        storage = SessionStorage(session_db_path)
        await storage.connect()
        session_manager = SessionManager(storage, agent_registry=agent_registry)

    # Wire session manager into tool layer (like set_scheduler, set_gateway_config)
    from opensquilla.tools.builtin.sessions import (
        set_gateway_config as _set_sessions_gateway_config,
    )
    from opensquilla.tools.builtin.sessions import set_session_manager

    set_session_manager(session_manager)
    _set_sessions_gateway_config(config)

    # Wire agent registry into the agents_list tool surface.
    from opensquilla.tools.builtin.agents import set_agent_registry as _set_agent_registry_tool

    _set_agent_registry_tool(agent_registry)

    # ── Provider selector ───────────────────────────────────────────
    llm_runtime = resolve_llm_runtime_config(config)
    api_key = llm_runtime.api_key
    resolved_base = llm_runtime.base_url
    proxy = llm_runtime.proxy
    if provider_selector is None:
        if api_key:
            from opensquilla.provider.selector import (
                ModelSelector,
                ProviderConfig,
                SelectorConfig,
            )

            if resolved_base.endswith("/v1"):
                resolved_base = resolved_base[:-3]
            provider_selector = ModelSelector(
                SelectorConfig(
                    primary=ProviderConfig(
                        provider=llm_runtime.provider,
                        model=llm_runtime.model,
                        api_key=api_key,
                        base_url=resolved_base,
                        proxy=proxy,
                        provider_routing=llm_runtime.provider_routing,
                    )
                )
            )
            log.info(
                "build_services.provider_ready",
                provider=llm_runtime.provider,
                model=llm_runtime.model,
            )

    # ── Model catalog (boot order: after provider selector) ──────────
    # Keep a catalog for every provider so direct-provider runtime paths still
    # get static fallback capabilities (for example DeepSeek v4 thinking
    # replay) even when only OpenRouter performs a remote model-list fetch.
    from opensquilla.provider.model_catalog import ModelCatalog

    model_catalog = ModelCatalog()
    if api_key and config.llm.provider == "openrouter":
        try:
            await asyncio.wait_for(
                model_catalog.fetch_openrouter(api_key, resolved_base, proxy),
                timeout=5.0,
            )
            log.info("build_services.model_catalog_ready", count=len(model_catalog))
        except Exception as e:
            log.warning("build_services.model_catalog_failed", error=str(e))

        try:
            from opensquilla.engine.pricing import refresh_live_prices

            pricing_models = {str(config.llm.model)} if config.llm.model else set()
            router_cfg = getattr(config, "squilla_router", None)
            if router_cfg is not None:
                for tier_cfg in getattr(router_cfg, "tiers", {}).values():
                    model_id = tier_cfg.get("model") if isinstance(tier_cfg, dict) else None
                    if model_id:
                        pricing_models.add(str(model_id))
            await asyncio.to_thread(
                refresh_live_prices,
                pricing_models,
                f"{resolved_base.rstrip('/')}/v1",
            )
            log.info("build_services.pricing_cache_ready", count=len(pricing_models))
        except Exception as e:
            log.warning("build_services.pricing_cache_failed", error=str(e))

    # ── Tool registry ───────────────────────────────────────────────
    if tool_registry is None:
        from opensquilla.tools.registry import get_default_registry

        tool_registry = get_default_registry()

    try:
        from opensquilla.tools.builtin.media import configure_image_generation

        configure_image_generation(config.image_generation, llm_config=config.llm)
    except Exception as e:
        log.warning("build_services.image_generation_config_failed", error=str(e))

    # ── Memory tools (boot order 18) — per-agent stores ──────────────
    # Pre-bind to empty defaults so the ServiceContainer init below and
    # the deferred TurnRunner-ref callback both work even if the try
    # block aborts.
    memory_managers: dict[str, MemoryManager] = {}
    memory_stores: dict[str, Any] = {}
    memory_retrievers: dict[str, Any] = {}
    memory_sync_managers: dict[str, Any] = {}
    turn_capture_services: dict[str, Any] = {}
    memory_watchers: list[Any] = []
    _turn_runner_ref: list = []
    try:
        from opensquilla.memory.manager import build_memory_managers
        from opensquilla.tools.builtin.memory_tools import create_memory_tools

        agent_ids = _configured_agent_ids(config, extra_agent_ids)
        memory_managers = await build_memory_managers(config, agent_ids)

        # Derive legacy per-tier views from the managers. These remain in
        # `ServiceContainer` until Step 1B migrates downstream consumers
        # (TurnRunner, CLI, memory_tools) onto `memory_managers` directly.
        memory_stores = {aid: m.store for aid, m in memory_managers.items()}
        memory_retrievers = {aid: m.retriever for aid, m in memory_managers.items()}
        memory_sync_managers = {aid: m.sync_manager for aid, m in memory_managers.items()}
        turn_capture_services = {aid: m.turn_capture for aid, m in memory_managers.items()}
        memory_watchers = [m.sync_manager for m in memory_managers.values()]

        # Deferred callback: TurnRunner doesn't exist yet, so we capture a
        # mutable list ref that start_gateway_server() will populate later.
        def _on_memory_write(agent_id: str) -> None:
            if _turn_runner_ref:
                _turn_runner_ref[0].refresh_memory_snapshot(agent_id)

        if memory_stores and memory_retrievers:
            create_memory_tools(
                stores=memory_stores,
                retrievers=memory_retrievers,
                memory_base=config.state_dir,
                registry=tool_registry,
                memory_source=getattr(config.memory, "source", "state"),
                on_memory_write=_on_memory_write,
                memory_config=config.memory,
                workspace_base=config.workspace_dir
                if getattr(config.memory, "source", "state") == "workspace"
                else None,
            )
            log.info("build_services.memory_tools_registered", agents=list(memory_stores))
    except Exception as e:
        log.warning("build_services.memory_tools_failed", error=str(e))

    # ── Skill loader (boot order 19) ────────────────────────────────
    skill_loader = None
    try:
        from opensquilla.skills.loader import SkillLoader
        from opensquilla.skills.paths import resolve_skill_layer_dirs

        workspace_root_raw = getattr(config, "workspace_dir", None)
        workspace_root = Path(workspace_root_raw) if workspace_root_raw else None
        workspace_override = (
            Path(config.skills.workspace_dir) if config.skills.workspace_dir else None
        )
        layer_dirs = resolve_skill_layer_dirs(
            allow_bundled=config.skills.allow_bundled,
            workspace_root=workspace_root,
            workspace_override=workspace_override,
            managed_override=config.skills.managed_dir,
            extra_dirs=[Path(d) for d in config.skills.extra_dirs],
        )
        skill_loader = SkillLoader(
            bundled_dir=layer_dirs.bundled_dir,
            workspace_dir=layer_dirs.workspace_dir,
            managed_dir=layer_dirs.managed_dir,
            personal_agents_dir=layer_dirs.personal_agents_dir,
            project_agents_dir=layer_dirs.project_agents_dir,
            extra_dirs=layer_dirs.extra_dirs,
        )
        log.info(
            "build_services.skill_loader_initialized",
            bundled_dir=str(layer_dirs.bundled_dir),
        )

        # Register skill_list and skill_view tools
        from opensquilla.tools.builtin.skill_tools import create_skill_tools

        create_skill_tools(skill_loader)
        log.info("build_services.skill_tools_registered")
    except Exception as e:
        log.warning("build_services.skill_loader_failed", error=str(e))

    # ── Cron scheduler (boot order 20) ──────────────────────────────
    cron_scheduler = None
    try:
        from opensquilla.scheduler import JobStore, SchedulerEngine

        scheduler_db = Path(
            os.environ.get("OPENSQUILLA_SCHEDULER_DB", str(_state_path(config, "scheduler.db")))
        )
        scheduler_db.parent.mkdir(parents=True, exist_ok=True)
        job_store = JobStore(db_path=str(scheduler_db))
        await job_store.open()
        cron_scheduler = SchedulerEngine(
            store=job_store,
            session_store=storage,  # SessionStorage instance from session manager boot
            config={
                "max_concurrent_runs": int(os.environ.get("OPENSQUILLA_CRON_MAX_CONCURRENT", "3")),
                "max_catchup_jobs": int(os.environ.get("OPENSQUILLA_CRON_MAX_CATCHUP", "5")),
                "session_retention": int(
                    os.environ.get("OPENSQUILLA_CRON_SESSION_RETENTION", "86400")
                ),
            },
        )
        await cron_scheduler.start()
        # Inject into admin tool so `cron` tool can dispatch to the scheduler
        from opensquilla.tools.builtin.admin import set_scheduler

        set_scheduler(cron_scheduler)
        log.info("build_services.cron_scheduler_started")
    except Exception as e:
        log.warning("build_services.cron_scheduler_failed", error=str(e))

    # ── Usage tracker ───────────────────────────────────────────────
    if usage_tracker is None:
        usage_tracker = _UsageTracker()

    # ── Search provider (brave > duckduckgo fallback) ───────────────
    try:
        import opensquilla.search.providers.brave  # noqa: F401 — registers provider
        import opensquilla.search.providers.duckduckgo  # noqa: F401 — registers provider
        from opensquilla.search.registry import get_provider_spec
        from opensquilla.tools.builtin.web import configure_search

        provider = config.search_provider
        search_api_key = config.search_api_key
        if not search_api_key:
            env_key = config.search_api_key_env or get_provider_spec(provider).env_key
            search_api_key = os.environ.get(env_key, "") if env_key else ""
        # Auto-select: use brave if key is available and provider is default
        if provider == "duckduckgo":
            if search_api_key or os.environ.get("BRAVE_SEARCH_API_KEY"):
                provider = "brave"

        configure_search(
            provider_name=provider,
            max_results=config.search_max_results,
            api_key=search_api_key,
            proxy=config.search_proxy,
            use_env_proxy=config.search_use_env_proxy,
            fallback_policy=config.search_fallback_policy,
            diagnostics=config.search_diagnostics,
        )
        log.info("build_services.search_provider_initialized", provider=provider)
    except Exception as e:
        log.warning("build_services.search_provider_failed", error=str(e))

    # ── MCP discovery (boot order 22) ───────────────────────────────
    if config.mcp.enabled and config.mcp.servers:
        from opensquilla.mcp.discovery import discover_and_register
        from opensquilla.mcp.types import MCPServerConfig

        timeout = config.mcp.connect_timeout_seconds
        for entry in config.mcp.servers:
            try:
                mcp_cfg = MCPServerConfig(
                    name=entry.name,
                    transport=entry.transport,
                    command=entry.command,
                    args=entry.args,
                    url=entry.url,
                    env=entry.env,
                    tool_timeout_seconds=entry.tool_timeout_seconds,
                )
                names = await asyncio.wait_for(
                    discover_and_register(mcp_cfg, tool_registry),
                    timeout=timeout,
                )
                log.info(
                    "build_services.mcp_server_registered",
                    server=entry.name,
                    tools=len(names),
                )
            except TimeoutError:
                log.warning(
                    "build_services.mcp_server_timeout",
                    server=entry.name,
                    timeout=timeout,
                )
            except Exception as e:
                log.warning(
                    "build_services.mcp_server_failed",
                    server=entry.name,
                    error=str(e),
                )
    elif config.mcp.enabled:
        log.info("build_services.mcp_enabled_no_servers")

    flush_service = build_flush_service(
        tool_registry=tool_registry,
        provider_selector=provider_selector,
        config=config,
    )
    if flush_service is not None:
        log.info("build_services.session_flush_service_ready")
    else:
        log.info("build_services.session_flush_service_disabled")

    svc = ServiceContainer(
        config=config,
        provider_selector=provider_selector,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=skill_loader,
        usage_tracker=usage_tracker,
        cron_scheduler=cron_scheduler,
        model_catalog=model_catalog,
        agent_registry=agent_registry,
        memory_managers=memory_managers,
        memory_stores=memory_stores,
        memory_sync_managers=memory_sync_managers,
        memory_watchers=memory_watchers,
        memory_retrievers=memory_retrievers,
        turn_capture_services=turn_capture_services,
        flush_service=flush_service,
    )
    # Attach deferred callback ref so start_gateway_server can wire TurnRunner
    svc._turn_runner_ref = _turn_runner_ref  # type: ignore[attr-defined]
    return svc


def build_turn_runner_from_services(
    svc: Any,
    *,
    config: GatewayConfig | None = None,
) -> Any:
    """Build a TurnRunner with every service-backed memory integration wired.

    Provides a standalone per-session lock dict for CLI/standalone paths (no
    TaskRuntime).  When the caller is the gateway boot path, the boot wiring
    overrides ``task_runtime._get_session_lock_for_turn`` so both classes
    share a single lock per session.
    """
    import asyncio as _asyncio

    from opensquilla.engine.runtime import TurnRunner

    resolved_config = config if config is not None else svc.config
    # Standalone lock dict for CLI / test paths (no TaskRuntime involved).
    # Gateway path replaces this with task_runtime._get_session_lock_for_turn
    # immediately after task_runtime is constructed (see boot.py §7b wiring).
    _standalone_locks: dict[str, _asyncio.Lock] = {}

    def _standalone_lock_provider(session_key: str) -> _asyncio.Lock:
        return _standalone_locks.setdefault(session_key, _asyncio.Lock())

    return TurnRunner(
        provider_selector=svc.provider_selector,
        tool_registry=svc.tool_registry,
        session_manager=svc.session_manager,
        skill_loader=svc.skill_loader,
        usage_tracker=svc.usage_tracker,
        config=resolved_config,
        memory_sync_managers=getattr(svc, "memory_sync_managers", None) or None,
        model_catalog=getattr(svc, "model_catalog", None),
        memory_retrievers=getattr(svc, "memory_retrievers", None) or None,
        turn_capture_services=getattr(svc, "turn_capture_services", None) or None,
        session_flush_service=getattr(svc, "flush_service", None),
        session_lock_provider=_standalone_lock_provider,
    )


async def start_gateway_server(
    port: int | None = None,
    config: GatewayConfig | None = None,
    session_manager: Any = None,
    provider_selector: Any = None,
    tool_registry: Any = None,
    subscription_manager: Any = None,
    channel_manager: Any = None,
    usage_tracker: Any = None,
    run: bool = True,
) -> GatewayServer:
    """
    Boot sequence:
    1. Load/validate config
    2. Ensure auth token exists
    3. Build ASGI app
    4. Start uvicorn server
    """
    # ── Gateway-specific config handling ─────────────────────────────
    if config is None:
        config = GatewayConfig.load(os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))

    # Apply runtime port override
    if port is not None:
        config = config.model_copy(update={"port": port})

    _setup_file_logging(config)
    if config.config_path:
        log.info("gateway.config_loaded", path=config.config_path)

    # Gateway-specific: set env var for other components to discover
    os.environ["OPENSQUILLA_GATEWAY_PORT"] = str(config.port)

    # Gateway-specific: ensure auth token exists
    if config.auth.mode == "token" and not config.auth.token:
        token = secrets.token_urlsafe(32)
        config.auth = config.auth.model_copy(update={"token": token})
        config.mark_runtime_secret("auth.token")
        log.info("gateway.auth_token_generated")

    # Gateway-specific: resolve Control UI root directory (boot order 17)
    if config.control_ui.enabled:
        from opensquilla.gateway.control_ui import _STATIC_DIR, _TEMPLATE_DIR

        if not _TEMPLATE_DIR.is_dir():
            log.warning("gateway.control_ui.templates_missing", path=str(_TEMPLATE_DIR))
        if not _STATIC_DIR.is_dir():
            log.warning("gateway.control_ui.static_missing", path=str(_STATIC_DIR))
        log.info(
            "gateway.control_ui.resolved",
            base_path=config.control_ui.base_path,
            templates=str(_TEMPLATE_DIR),
            static=str(_STATIC_DIR),
        )
    else:
        log.info("gateway.control_ui.disabled")

    # Surface lexical degradation when the operator enabled filter_enabled=true
    # with a strategy that needs the local ONNX embedding backend.
    emit_skill_filter_banner(config.skills)

    # ── PID file lock ───────────────────────────────────────────────
    # Prevents two gateway instances from sharing the same STATE_DIR.
    # Must run before build_services so the lock is held before any DB work.
    from opensquilla.gateway.pidlock import GatewayPidLock

    _pid_lock = GatewayPidLock(_state_path(config, ""))
    _pid_lock.acquire()

    # ── Reusable service initialization via build_services ───────────
    svc = await build_services(
        config=config,
        session_manager=session_manager,
        provider_selector=provider_selector,
        tool_registry=tool_registry,
        usage_tracker=usage_tracker,
        session_db_path=str(_state_path(config, "sessions.db")),
    )

    # Record boot time for uptime calculation (gateway-specific)
    global _boot_time_ms
    _boot_time_ms = int(time.time() * 1000)

    log.info(
        "gateway.starting",
        host=config.host,
        port=config.port,
        auth_mode=config.auth.mode,
    )

    # ── TurnRunner (shared agent orchestration layer) ────────────────
    turn_runner = build_turn_runner_from_services(svc, config=config)
    # Patch deferred callback so memory writes refresh TurnRunner snapshots
    if hasattr(svc, "_turn_runner_ref"):
        svc._turn_runner_ref.append(turn_runner)  # type: ignore[attr-defined]

    # Lazy ref for channel_manager — cron handler captures it via closure,
    # populated after channel_manager is constructed below.
    _cm_holder: list = [None]
    from opensquilla.scheduler.heartbeat import (
        HeartbeatConfigWatcher,
        HeartbeatRunner,
    )
    from opensquilla.scheduler.heartbeat_loop import HeartbeatLoop
    from opensquilla.scheduler.heartbeat_service import HeartbeatService

    heartbeat_service = HeartbeatService(
        turn_runner=turn_runner,
        session_storage=get_session_storage(svc.session_manager) or svc.session_manager,
        channel_manager_ref=lambda: _cm_holder[0],
    )
    heartbeat_loop = HeartbeatLoop(
        config=config,
        heartbeat_service=heartbeat_service,
    )

    from opensquilla.gateway.background_completion import BackgroundCompletionManager
    from opensquilla.gateway.event_bridge import EventBridge
    from opensquilla.gateway.subagent_announce import set_background_completion_manager
    from opensquilla.gateway.task_runtime import TaskRun, TaskRuntime

    runtime_event_bridge = EventBridge(
        subscription_manager=subscription_manager,
        connection_registry=get_registry(),
    )
    background_completion_manager = BackgroundCompletionManager(
        session_manager=svc.session_manager,
        event_emitter=runtime_event_bridge.emit,
        channel_manager_ref=lambda: _cm_holder[0],
    )
    set_background_completion_manager(background_completion_manager)

    async def _subagent_completion_listener(event: Any) -> None:
        from opensquilla.gateway.subagent_announce import announce_subagent_completion

        await announce_subagent_completion(
            event,
            session_manager=svc.session_manager,
            event_emitter=runtime_event_bridge.emit,
            channel_manager=_cm_holder[0],
            task_runtime=task_runtime,
        )

    async def _task_runtime_turn_handler(run: TaskRun) -> None:
        await dispatch_task_runtime_turn(
            run,
            config=config,
            session_manager=svc.session_manager,
            turn_runner=turn_runner,
            event_emitter=runtime_event_bridge.emit,
        )

    task_runtime = TaskRuntime(
        storage=get_session_storage(svc.session_manager) or svc.session_manager,
        turn_handler=_task_runtime_turn_handler,
        event_emitter=runtime_event_bridge.emit,
        terminal_listener=_subagent_completion_listener,
        max_concurrency=_task_runtime_max_concurrency(config),
        max_pending_per_session=_task_runtime_max_pending_per_session(config),
        subagent_reserved_slots=int(
            getattr(getattr(config, "subagents", None), "subagent_reserved_slots", 0)
        ),
    )
    # Wire task_runtime's lock provider into turn_runner so both share a
    # single asyncio.Lock per session_key.
    turn_runner.set_session_lock_provider(task_runtime._get_session_lock_for_turn)
    svc.task_runtime = task_runtime
    # Wire the runtime into SessionManager so kill_session can cascade-cancel.
    attach_runtime = getattr(svc.session_manager, "attach_task_runtime", None)
    if callable(attach_runtime):
        attach_runtime(task_runtime)
    from opensquilla.tools.builtin.sessions import set_task_runtime

    set_task_runtime(task_runtime)

    # Resolve HEARTBEAT.md path; instantiate Runner + Watcher;
    # start Watcher BEFORE the Loop so the first tick already sees any
    # frontmatter overrides. ``reload_now()`` runs synchronously at start.
    heartbeat_runner = HeartbeatRunner()
    workspace_dir = config.workspace_dir or ""
    md_path_setting = getattr(config.heartbeat, "config_path", None)
    if md_path_setting:
        heartbeat_md_path = Path(md_path_setting).expanduser()
    elif workspace_dir:
        heartbeat_md_path = Path(workspace_dir).expanduser() / "HEARTBEAT.md"
    else:
        heartbeat_md_path = Path.home() / ".opensquilla" / "workspace" / "HEARTBEAT.md"
    heartbeat_watcher = HeartbeatConfigWatcher(
        heartbeat_runner,
        heartbeat_md_path,
        loop_listener=heartbeat_loop.apply_overrides,
    )
    await heartbeat_watcher.start()
    svc.heartbeat_watcher = heartbeat_watcher

    await heartbeat_loop.start()
    svc.heartbeat_loop = heartbeat_loop

    # Register cron agent_run handler (DI-based, no monkey-patch)
    if svc.cron_scheduler is not None:
        from opensquilla.memory.dream_factory import build_dream_factory
        from opensquilla.scheduler.delivery import DeliveryChain
        from opensquilla.scheduler.dream_handler import make_memory_dream_handler
        from opensquilla.scheduler.handlers import make_agent_run_handler, make_system_event_handler
        from opensquilla.scheduler.heartbeat_service import HeartbeatService

        async def _cron_ws_emitter(topic: str, event: str, payload: dict) -> int:
            """Targeted WS push with per-connection error isolation."""
            _registry = get_registry()
            _sub_mgr = subscription_manager
            if _sub_mgr is None:
                return 0
            conn_ids = _sub_mgr.get_topic_subscribers(topic)
            conn_ids |= _sub_mgr.get_topic_subscribers("cron:*")
            sent = 0
            for conn_id in conn_ids:
                conn = _registry.get(conn_id)
                if conn:
                    try:
                        await conn.send_event(event, payload)
                        sent += 1
                    except Exception:
                        pass
            return sent

        async def _session_forwarder(
            origin_session_key: str,
            text: str,
            provenance: dict,
        ) -> None:
            if svc.session_manager is None:
                return

            entry = await svc.session_manager.append_message(
                origin_session_key,
                role="assistant",
                content=text,
                provenance=provenance,
            )

            _sub_mgr = subscription_manager
            if _sub_mgr is None:
                return

            payload = build_cron_result_payload(origin_session_key, text, entry)

            _registry = get_registry()
            stream_payload = get_session_streams().record(
                origin_session_key,
                "session.event.cron_result",
                payload,
            )
            for conn_id in _sub_mgr.get_message_subscribers(origin_session_key):
                conn = _registry.get(conn_id)
                if conn:
                    try:
                        await conn.send_event("session.event.cron_result", stream_payload)
                    except Exception:
                        pass

            sessions_changed_payload = build_sessions_changed_payload(
                origin_session_key, "cron_result"
            )
            for conn_id in (
                _sub_mgr.get_message_subscribers(origin_session_key)
                | _sub_mgr.get_session_subscribers()
            ):
                conn = _registry.get(conn_id)
                if conn:
                    try:
                        await conn.send_event("sessions.changed", sessions_changed_payload)
                    except Exception:
                        pass

        async def _emit_session_event(
            session_key: str,
            event_name: str,
            payload: dict[str, Any],
        ) -> None:
            _sub_mgr = subscription_manager
            if _sub_mgr is None:
                return

            _registry = get_registry()
            stream_payload = (
                get_session_streams().record(session_key, event_name, payload)
                if event_name.startswith("session.event.")
                else payload
            )
            conn_ids = _sub_mgr.get_message_subscribers(session_key)
            if event_name.startswith("sessions."):
                conn_ids |= _sub_mgr.get_session_subscribers()

            for conn_id in conn_ids:
                conn = _registry.get(conn_id)
                if conn:
                    try:
                        await conn.send_event(event_name, stream_payload)
                    except Exception:
                        pass

        delivery_chain = DeliveryChain(
            channel_manager_ref=lambda: _cm_holder[0],
            ws_emitter=_cron_ws_emitter,
            session_forwarder=_session_forwarder,
        )

        def _cron_workspace_resolver(agent_id: str) -> tuple[str | None, bool]:
            workspace_dir = resolve_agent_workspace_dir(agent_id, config)
            workspace_strict = getattr(config, "workspace_strict", None)
            if not isinstance(workspace_strict, bool):
                workspace_strict = bool(workspace_dir)
            return str(workspace_dir), workspace_strict

        agent_handler = make_agent_run_handler(
            delivery_chain=delivery_chain,
            turn_runner_ref=lambda: turn_runner,
            session_manager_ref=lambda: svc.session_manager,
            task_runtime_ref=lambda: task_runtime,
            workspace_resolver=_cron_workspace_resolver,
        )
        system_handler = make_system_event_handler(
            delivery_chain=delivery_chain,
            turn_runner_ref=lambda: turn_runner,
            session_manager_ref=lambda: svc.session_manager,
            session_event_emitter=_emit_session_event,
            heartbeat_service_ref=lambda: heartbeat_service,
            heartbeat_loop_ref=lambda: heartbeat_loop,
            workspace_resolver=_cron_workspace_resolver,
        )
        dream_handler = make_memory_dream_handler(
            build_dream=build_dream_factory(
                config=config,
                provider_selector=svc.provider_selector,
                tool_registry=svc.tool_registry,
                turn_runner=turn_runner,
            ),
            should_skip=lambda: (
                "disabled" if not getattr(config.memory.dream, "enabled", False) else None
            ),
        )
        svc.cron_scheduler.register_handler("agent_run", agent_handler)
        svc.cron_scheduler.register_handler("system_event", system_handler)
        svc.cron_scheduler.register_handler("memory_dream", dream_handler)
        log.info("gateway.cron_handler_registered", handler_key="agent_run")
        log.info("gateway.cron_handler_registered", handler_key="system_event")
        log.info("gateway.cron_handler_registered", handler_key="memory_dream")
        await _register_dream_crons(
            scheduler=svc.cron_scheduler,
            memory_config=config.memory,
            agent_ids=_configured_agent_ids(config),
        )

    # Build channel adapters (don't start yet -- app doesn't exist)
    webhook_routes: list = []
    if channel_manager is None and config.channels.channels:
        from opensquilla.channels.manager import ChannelManager
        from opensquilla.gateway.event_bridge import EventBridge

        event_bridge = EventBridge(
            subscription_manager=subscription_manager,
            connection_registry=get_registry(),
        )
        channel_rpc_context_factory = _make_channel_rpc_context_factory(
            svc,
            config,
            subscription_manager=subscription_manager,
            channel_manager_ref=lambda: _cm_holder[0],
            turn_runner=turn_runner,
            heartbeat_service=heartbeat_service,
        )
        channel_manager = ChannelManager.from_config(
            config.channels.channels,
            turn_runner=turn_runner,
            session_manager=svc.session_manager,
            event_bridge=event_bridge,
            config=config,
            task_runtime=task_runtime,
            rpc_dispatcher=get_dispatcher(),
            channel_rpc_context_factory=channel_rpc_context_factory,
        )
        webhook_routes = channel_manager.collect_webhook_routes()
        # Populate lazy ref so cron handler can deliver to channels
        _cm_holder[0] = channel_manager
        log.info(
            "gateway.channels_built",
            count=len(config.channels.channels),
            webhooks=len(webhook_routes),
        )

    # Ensure lazy ref covers pre-injected channel_manager too
    if channel_manager is not None:
        _cm_holder[0] = channel_manager

    # ── ASGI app ─────────────────────────────────────────────────────
    app = create_gateway_app(
        config,
        session_manager=svc.session_manager,
        provider_selector=svc.provider_selector,
        tool_registry=svc.tool_registry,
        subscription_manager=subscription_manager,
        channel_manager=channel_manager,
        usage_tracker=svc.usage_tracker,
        skill_loader=svc.skill_loader,
        cron_scheduler=svc.cron_scheduler,
        turn_runner=turn_runner,
        task_runtime=task_runtime,
        flush_service=svc.flush_service,
        heartbeat_service=heartbeat_service,
        heartbeat_loop=heartbeat_loop,
        agent_registry=svc.agent_registry,
        memory_managers=svc.memory_managers,
        memory_stores=svc.memory_stores,
        memory_retrievers=svc.memory_retrievers,
        extra_routes=webhook_routes or None,
    )
    app.state.gateway_ready = False

    server_handle = GatewayServer(app=app, config=config)
    server_handle._channel_manager = channel_manager
    server_handle._services = svc
    server_handle._background_completion_manager = background_completion_manager

    if run:
        uv_config = uvicorn.Config(
            app=app,
            host=config.host,
            port=config.port,
            log_level="info" if not config.debug else "debug",
        )
        server = uvicorn.Server(uv_config)
        server_handle._server = server

        task = create_background_task(server.serve())
        server_handle._task = task

        # Warn loudly before the normal started line so operators
        # see the network-exposure notice even on info-level log streams.
        if is_public_bind(config.host):
            log.warning(
                "gateway.bind.public",
                host=config.host,
                port=config.port,
                message=(
                    "gateway bound to a wildcard address; reachable from "
                    "every interface. Opt-in required — only expose behind "
                    "a trusted reverse proxy or VPN."
                ),
            )
        log.info("gateway.started", host=config.host, port=config.port)
        create_background_task(preload_squilla_router_runtime(config))

    # Start channels (after app is ready to receive webhooks)
    if channel_manager is not None:
        results = await channel_manager.start_all()
        start_errors_fn = getattr(channel_manager, "start_errors", None)
        start_errors = start_errors_fn() if start_errors_fn is not None else {}
        for name, ok in results.items():
            if ok:
                log.info("gateway.channel_started", channel=name)
            else:
                details = start_errors.get(name, {})
                log.warning(
                    "gateway.channel_failed",
                    channel=name,
                    error_type=details.get("error_type"),
                    error=details.get("error"),
                    exception=details.get("exception"),
                )

    app.state.gateway_ready = True
    return server_handle
