"""Unit tests for the auto-propose cron handler factory."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from opensquilla.gateway.config import MetaSkillAutoProposeConfig
from opensquilla.scheduler.auto_propose_handler import make_auto_propose_handler
from opensquilla.scheduler.types import CronJob
from opensquilla.skills.creator.auto_propose import AutoProposeResult


def _make_job(agent_id: str = "main") -> CronJob:
    return CronJob(
        id=f"auto_propose-{agent_id}",
        name=f"auto_propose:{agent_id}",
        payload={"agent_id": agent_id},
    )


def _make_config(**overrides: object) -> MetaSkillAutoProposeConfig:
    base: dict[str, object] = {
        "enabled": True,
        "window_days": 7,
        "min_freq": 2,
        "top_k": 3,
    }
    base.update(overrides)
    return MetaSkillAutoProposeConfig(**base)


@pytest.mark.asyncio
async def test_kill_switch_short_circuits_before_orchestrator_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AUTO_PROPOSE_DISABLED", "1")

    def build(_aid: str) -> object:
        raise AssertionError("orchestrator should not be built when kill switch on")

    def guard() -> bool:
        raise AssertionError("predicate should not be called when kill switch on")

    handler = make_auto_propose_handler(
        build_orchestrator=build,
        skill_loader=MagicMock(),
        log_dir=tmp_path / "logs",
        proposals_dir=tmp_path / "proposals",
        config=_make_config(),
        enabled_predicate=guard,
    )
    result = await handler(_make_job())
    assert result.delivery_status == "skipped"
    assert "kill_switch" in result.summary


@pytest.mark.asyncio
async def test_predicate_false_skips_without_running_pipeline(
    tmp_path: Path,
) -> None:
    def build(_aid: str) -> object:
        raise AssertionError("orchestrator should not be built when predicate is false")

    handler = make_auto_propose_handler(
        build_orchestrator=build,
        skill_loader=MagicMock(),
        log_dir=tmp_path / "logs",
        proposals_dir=tmp_path / "proposals",
        config=_make_config(enabled=False),
        enabled_predicate=lambda: False,
    )
    result = await handler(_make_job())
    assert result.delivery_status == "skipped"
    assert "disabled" in result.summary


@pytest.mark.asyncio
async def test_happy_path_runs_pipeline_and_summarises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock the auto_propose library so we don't hit a real DAG; just
    verify the handler glues kwargs together and surfaces the summary."""
    captured: dict[str, object] = {}

    async def fake_auto_propose(**kwargs: object) -> AutoProposeResult:
        captured.update(kwargs)
        return AutoProposeResult(
            proposals_created=["aaaaaaaa", "bbbbbbbb"],
            skipped=[{"reason": "below_min_freq"}],
            errors=[],
            triggered_by="cron",
        )

    monkeypatch.setattr(
        "opensquilla.scheduler.auto_propose_handler.auto_propose",
        fake_auto_propose,
    )

    fake_orch = MagicMock(name="orchestrator")
    fake_loader = MagicMock(name="skill_loader")
    log_dir = tmp_path / "logs"
    proposals_dir = tmp_path / "proposals"

    handler = make_auto_propose_handler(
        build_orchestrator=lambda _aid: fake_orch,
        skill_loader=fake_loader,
        log_dir=log_dir,
        proposals_dir=proposals_dir,
        config=_make_config(
            window_days=14,
            min_freq=4,
            top_k=7,
            auto_enable=True,
            auto_enable_max_risk="medium",
        ),
        enabled_predicate=lambda: True,
    )
    result = await handler(_make_job(agent_id="agent-x"))

    # HandlerResult shape
    assert result.delivery_status == "delivered"
    assert "proposals=2" in result.summary
    assert "skipped=1" in result.summary
    assert "errors=0" in result.summary
    assert "via=cron" in result.summary

    # Kwargs threaded into the library function
    assert captured["orchestrator"] is fake_orch
    assert captured["skill_loader"] is fake_loader
    assert captured["log_dir"] == log_dir
    assert captured["proposals_dir"] == proposals_dir
    assert captured["window_days"] == 14
    assert captured["min_freq"] == 4
    assert captured["top_k"] == 7
    assert captured["triggered_by"] == "cron"
    assert captured["auto_enable"] is True
    assert captured["auto_enable_max_risk"] == "medium"


@pytest.mark.asyncio
async def test_orchestrator_build_failure_returns_failed_result(
    tmp_path: Path,
) -> None:
    def build(_aid: str) -> object:
        raise RuntimeError("provider not configured")

    handler = make_auto_propose_handler(
        build_orchestrator=build,
        skill_loader=MagicMock(),
        log_dir=tmp_path / "logs",
        proposals_dir=tmp_path / "proposals",
        config=_make_config(),
        enabled_predicate=lambda: True,
    )
    result = await handler(_make_job())
    assert result.delivery_status == "failed"
    assert "provider not configured" in result.summary


def test_config_defaults_off() -> None:
    """Sanity: zero-arg construction yields a fully-disabled config —
    matches the user requirement that the feature is off until they
    explicitly opt in via toml."""
    cfg = MetaSkillAutoProposeConfig()
    assert cfg.enabled is False
    assert cfg.on_dream_complete is False
    assert cfg.auto_enable is False
    assert cfg.auto_enable_max_risk == "low"
    assert cfg.cron == "0 5 * * *"
    assert cfg.min_freq == 3
    assert cfg.window_days == 30
    assert cfg.top_k == 5
    assert cfg.agent_ids == []


def test_config_validation_rejects_zero_min_freq() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MetaSkillAutoProposeConfig(min_freq=0)


def test_config_validation_rejects_negative_window() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MetaSkillAutoProposeConfig(window_days=0)


@pytest.mark.asyncio
async def test_register_auto_propose_crons_resumes_a_paused_job(
    tmp_path: Path,
) -> None:
    """Reg-on the WebUI toggle false→true edge must un-pause a previously
    paused job. ``pause()`` sets ``status=PAUSED`` and ``resume()``
    flips it back; ``update_job(enabled=True)`` alone is insufficient
    because ``enabled`` and ``status`` are independent fields.
    """
    from unittest.mock import AsyncMock, MagicMock

    from opensquilla.gateway.boot import _register_auto_propose_crons
    from opensquilla.scheduler.types import JobStatus, SessionTarget

    paused_job = MagicMock()
    paused_job.id = "job-id-1"
    paused_job.name = "auto_propose:main"
    paused_job.schedule_raw = "*/5 * * * *"
    paused_job.payload = {"agent_id": "main"}
    paused_job.session_target = SessionTarget.ISOLATED
    paused_job.status = JobStatus.PAUSED

    scheduler = MagicMock()
    scheduler.list_jobs = MagicMock(return_value=[paused_job])
    scheduler.update_job = AsyncMock()
    scheduler.resume_job = AsyncMock()
    scheduler.add_job = AsyncMock()

    auto_cfg = _make_config(cron="*/5 * * * *")
    await _register_auto_propose_crons(
        scheduler=scheduler, auto_cfg=auto_cfg, agent_ids=["main"],
    )
    scheduler.resume_job.assert_called_once_with("job-id-1")
    # No new job added since one already exists.
    scheduler.add_job.assert_not_called()


@pytest.mark.asyncio
async def test_register_auto_propose_crons_uses_structured_schedule_for_new_jobs(
    tmp_path: Path,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from opensquilla.gateway.boot import _register_auto_propose_crons
    from opensquilla.scheduler.types import ScheduleKind, SessionTarget

    scheduler = MagicMock()
    scheduler.list_jobs = MagicMock(return_value=[])
    scheduler.update_job = AsyncMock()
    scheduler.resume_job = AsyncMock()
    scheduler.add_job = AsyncMock()

    auto_cfg = _make_config(cron="*/5 * * * *")
    await _register_auto_propose_crons(
        scheduler=scheduler, auto_cfg=auto_cfg, agent_ids=["main"],
    )

    scheduler.add_job.assert_called_once_with(
        name="auto_propose:main",
        schedule_kind=ScheduleKind.CRON,
        schedule_value="*/5 * * * *",
        handler_key="auto_propose",
        payload={"agent_id": "main"},
        session_target=SessionTarget.ISOLATED,
    )


@pytest.mark.asyncio
async def test_register_auto_propose_crons_updates_schedule_with_structured_patch(
    tmp_path: Path,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from opensquilla.gateway.boot import _register_auto_propose_crons
    from opensquilla.scheduler.types import JobStatus, ScheduleKind, SessionTarget

    existing = MagicMock()
    existing.id = "job-id-3"
    existing.name = "auto_propose:main"
    existing.schedule_raw = "0 5 * * *"
    existing.payload = {"agent_id": "main"}
    existing.session_target = SessionTarget.ISOLATED
    existing.status = JobStatus.PENDING

    scheduler = MagicMock()
    scheduler.list_jobs = MagicMock(return_value=[existing])
    scheduler.update_job = AsyncMock()
    scheduler.resume_job = AsyncMock()
    scheduler.add_job = AsyncMock()

    auto_cfg = _make_config(cron="*/5 * * * *")
    await _register_auto_propose_crons(
        scheduler=scheduler, auto_cfg=auto_cfg, agent_ids=["main"],
    )

    scheduler.update_job.assert_called_once_with(
        "job-id-3",
        schedule_kind=ScheduleKind.CRON,
        schedule_value="*/5 * * * *",
    )
    scheduler.add_job.assert_not_called()


@pytest.mark.asyncio
async def test_register_auto_propose_crons_does_not_resume_active_jobs(
    tmp_path: Path,
) -> None:
    """An already-running job stays running — no spurious resume_job
    call (idempotent re-register at boot)."""
    from unittest.mock import AsyncMock, MagicMock

    from opensquilla.gateway.boot import _register_auto_propose_crons
    from opensquilla.scheduler.types import JobStatus, SessionTarget

    active_job = MagicMock()
    active_job.id = "job-id-2"
    active_job.name = "auto_propose:main"
    active_job.schedule_raw = "*/5 * * * *"
    active_job.payload = {"agent_id": "main"}
    active_job.session_target = SessionTarget.ISOLATED
    active_job.status = JobStatus.PENDING

    scheduler = MagicMock()
    scheduler.list_jobs = MagicMock(return_value=[active_job])
    scheduler.update_job = AsyncMock()
    scheduler.resume_job = AsyncMock()
    scheduler.add_job = AsyncMock()

    auto_cfg = _make_config(cron="*/5 * * * *")
    await _register_auto_propose_crons(
        scheduler=scheduler, auto_cfg=auto_cfg, agent_ids=["main"],
    )
    scheduler.resume_job.assert_not_called()
    scheduler.add_job.assert_not_called()
