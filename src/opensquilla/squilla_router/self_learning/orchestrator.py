"""``maybe_run_update_router`` — the offline training entry point.

Invoked opportunistically from the post-dream hook (no daemon). It ties the
trigger gates to dataset building, training, state bookkeeping, and receipts.
Fail-open: any error leaves the active model untouched and is recorded, never
raised onto the caller.

Training runs in a subprocess by default (``subprocess_trainer``) so a long
LightGBM fit cannot contend with the router's 5s on-turn budget; tests inject
``in_process_trainer``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import structlog

from opensquilla.squilla_router.self_learning.dataset import (
    TrainingDataset,
    build_training_dataset,
    export_training_dataset,
)
from opensquilla.squilla_router.self_learning.gates import (
    READY,
    GateResult,
    evaluate_training_gates,
)
from opensquilla.squilla_router.self_learning.state import (
    load_train_state,
    save_train_state,
    scan_event_store,
)
from opensquilla.squilla_router.self_learning.store import router_data_root
from opensquilla.squilla_router.self_learning.train import CandidateInfo, build_candidate_bundle

log = structlog.get_logger(__name__)


class Trainer(Protocol):
    def __call__(
        self,
        dataset: TrainingDataset,
        *,
        base_dir: Path,
        learned_root: Path,
        config: Any,
        parent_version: str | None,
        agent_id: str,
        home: Path | None,
    ) -> CandidateInfo: ...


@dataclass
class UpdateResult:
    ran: bool
    reason: str
    version: str | None = None
    gate_reason: str | None = None
    error: str | None = None
    promoted: bool = False
    rolled_back: bool = False


def _now_iso(now: datetime | None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _learned_root(home: Path | None) -> Path:
    return router_data_root(home) / "learned"


def _default_base_dir(router_cfg: Any) -> Path:
    bundle = getattr(router_cfg, "v4_bundle_dir", None)
    if bundle:
        return Path(bundle)
    from opensquilla.squilla_router.v4_phase3 import default_bundle_dir

    return default_bundle_dir()


def write_receipt(agent_id: str, kind: str, payload: dict, home: Path | None = None) -> Path:
    """Append a JSON receipt for a train/promote/rollback event."""

    receipts_dir = router_data_root(home) / ".receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    path = receipts_dir / f"{agent_id}-{stamp}-{kind}.json"
    path.write_text(
        json.dumps({"agent_id": agent_id, "kind": kind, **payload}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def in_process_trainer(
    dataset: TrainingDataset,
    *,
    base_dir: Path,
    learned_root: Path,
    config: Any,
    parent_version: str | None,
    agent_id: str,
    home: Path | None,
) -> CandidateInfo:
    """Train in the current process (used by tests and as a fallback)."""

    return build_candidate_bundle(
        dataset,
        base_dir=base_dir,
        learned_root=learned_root,
        config=config,
        parent_version=parent_version,
    )


def subprocess_trainer(
    dataset: TrainingDataset,
    *,
    base_dir: Path,
    learned_root: Path,
    config: Any,
    parent_version: str | None,
    agent_id: str,
    home: Path | None,
) -> CandidateInfo:
    """Train in a niced, time-bounded subprocess so it can't stall the router."""

    npz_path = export_training_dataset(dataset, agent_id, home=home)
    cmd = [
        sys.executable,
        "-m",
        "opensquilla.squilla_router.self_learning.train_worker",
        "--dataset",
        str(npz_path),
        "--base",
        str(base_dir),
        "--learned-root",
        str(learned_root),
        "--num-boost-round",
        str(int(getattr(config, "num_boost_round", 60))),
    ]
    if parent_version:
        cmd += ["--parent-version", parent_version]

    timeout_s = float(getattr(config, "train_timeout_seconds", 900.0))
    proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        preexec_fn=_lower_priority if sys.platform != "win32" else None,
        check=True,
    )
    last_line = proc.stdout.strip().splitlines()[-1]
    out = json.loads(last_line)
    manifest = Path(out["bundle_dir"]) / "learned_manifest.json"
    return CandidateInfo(**json.loads(manifest.read_text(encoding="utf-8")))


def _lower_priority() -> None:  # pragma: no cover — child-process only
    import os

    try:
        os.nice(10)
    except OSError:
        pass


def maybe_run_update_router(
    agent_id: str,
    *,
    router_cfg: Any,
    home: Path | None = None,
    now: datetime | None = None,
    trainer: Trainer | None = None,
    base_dir: Path | None = None,
) -> UpdateResult:
    """Check gates and, if ready, build a candidate model. Never raises."""

    try:
        sl_cfg = getattr(router_cfg, "self_learning", None)
        if sl_cfg is None:
            return UpdateResult(ran=False, reason="disabled", gate_reason="disabled")

        state = load_train_state(agent_id, home)

        # M4: before anything else, check whether a live candidate has regressed.
        rolled_back = _check_and_maybe_rollback(agent_id, sl_cfg, state, home, now)

        stats = scan_event_store(agent_id, home=home)
        gate: GateResult = evaluate_training_gates(
            config=sl_cfg, state=state, stats=stats, now=now
        )
        if gate.reason != READY:
            return UpdateResult(
                ran=False, reason=gate.reason, gate_reason=gate.reason, rolled_back=rolled_back
            )

        dataset = build_training_dataset(agent_id, home=home)
        if len(dataset) == 0:
            return UpdateResult(ran=False, reason="empty_dataset", gate_reason=gate.reason)

        run_trainer = trainer or subprocess_trainer
        resolved_base = base_dir or _default_base_dir(router_cfg)
        try:
            info = run_trainer(
                dataset,
                base_dir=resolved_base,
                learned_root=_learned_root(home),
                config=sl_cfg,
                parent_version=state.last_version,
                agent_id=agent_id,
                home=home,
            )
        except Exception as exc:  # training failure -> backoff, fail-open
            state.last_attempt_ts = _now_iso(now)
            state.consecutive_failures += 1
            save_train_state(state, agent_id, home)
            write_receipt(
                agent_id,
                "train_failure",
                {"error": str(exc), "consecutive_failures": state.consecutive_failures},
                home,
            )
            log.warning("router_self_learning.train_failed", agent_id=agent_id, error=str(exc))
            return UpdateResult(
                ran=False, reason="train_failed", gate_reason=gate.reason, error=str(exc)
            )

        state.last_train_ts = _now_iso(now)
        state.last_attempt_ts = _now_iso(now)
        state.last_version = info.version

        # M3: gate the candidate before swapping it live.
        decision = _evaluate_candidate(info, resolved_base, sl_cfg)
        if not decision.promote:
            from opensquilla.squilla_router.self_learning.promotion import quarantine_candidate

            quarantine_candidate(info.version, home)
            state.consecutive_failures += 1  # uninformative data -> back off
            save_train_state(state, agent_id, home)
            write_receipt(
                agent_id,
                "rejected",
                {"version": info.version, "reason": decision.reason, "metrics": decision.metrics},
                home,
            )
            log.info(
                "router_self_learning.rejected",
                agent_id=agent_id,
                version=info.version,
                reason=decision.reason,
            )
            return UpdateResult(
                ran=True,
                reason=f"rejected:{decision.reason}",
                version=info.version,
                gate_reason=gate.reason,
                rolled_back=rolled_back,
            )

        # Passed the gate -> atomic swap + cache invalidation.
        from opensquilla.squilla_router.self_learning.promotion import promote_candidate

        previous = promote_candidate(info.version, home)
        _invalidate_router_strategy_cache()
        state.consecutive_failures = 0
        state.active_version = info.version
        state.promoted_at = _now_iso(now)
        state.pre_promotion_complaint_rate = stats.complaint_rate
        save_train_state(state, agent_id, home)
        write_receipt(
            agent_id,
            "promoted",
            {
                "version": info.version,
                "previous": previous,
                "bundle_dir": info.bundle_dir,
                "n_samples": info.n_samples,
                "used_init_model": info.used_init_model,
                "pre_promotion_complaint_rate": stats.complaint_rate,
                "metrics": decision.metrics,
            },
            home,
        )
        log.info(
            "router_self_learning.promoted",
            agent_id=agent_id,
            version=info.version,
            previous=previous,
            n_samples=info.n_samples,
        )
        return UpdateResult(
            ran=True,
            reason="promoted",
            version=info.version,
            gate_reason=gate.reason,
            promoted=True,
            rolled_back=rolled_back,
        )
    except Exception as exc:  # pragma: no cover — orchestration must not raise
        log.warning("router_self_learning.update_error", agent_id=agent_id, error=str(exc))
        return UpdateResult(ran=False, reason="error", error=str(exc))


def _invalidate_router_strategy_cache() -> None:
    """Force the running router to reload the (now swapped) active bundle."""

    try:
        from opensquilla.engine.steps.squilla_router import invalidate_strategy_cache

        invalidate_strategy_cache()
    except Exception as exc:  # pragma: no cover — best effort
        log.warning("router_self_learning.cache_invalidate_failed", error=str(exc))


def _evaluate_candidate(info: CandidateInfo, base_dir: Path, config: Any):
    """Run the golden-set tripwire (if configured) and apply the promotion gate.

    The rolling-holdout CV metrics already live on ``info.cv_metrics`` (computed
    during training); here we add the optional frozen golden comparison.
    """

    from opensquilla.squilla_router.self_learning.evaluate import (
        PromotionDecision,
        decide_promotion,
        evaluate_golden,
    )

    golden = None
    baseline_golden = None
    golden_path = getattr(config, "golden_eval_path", None)
    if golden_path:
        try:
            import lightgbm as lgb

            cand = lgb.Booster(model_file=str(Path(info.bundle_dir) / "lgbm_main.bin"))
            golden = evaluate_golden(cand, Path(golden_path))
            base_lgbm = base_dir / "lgbm_main.bin"
            if base_lgbm.is_file():
                try:
                    baseline_golden = evaluate_golden(
                        lgb.Booster(model_file=str(base_lgbm)), Path(golden_path)
                    )
                except Exception:  # noqa: BLE001 — baseline optional (e.g. LFS pointer)
                    baseline_golden = None
        except Exception as exc:  # noqa: BLE001
            log.warning("router_self_learning.golden_eval_failed", error=str(exc))
            return PromotionDecision(False, "golden_eval_error", {"error": str(exc)})

    return decide_promotion(
        info.cv_metrics or {}, golden=golden, baseline_golden=baseline_golden, config=config
    )


def _check_and_maybe_rollback(
    agent_id: str,
    config: Any,
    state,
    home: Path | None,
    now: datetime | None,
) -> bool:
    """Revert a promoted candidate that regressed on live traffic. Returns True
    if a rollback happened."""

    if state.active_version is None or state.promoted_at is None:
        return False
    from opensquilla.squilla_router.self_learning.promotion import (
        quarantine_candidate,
        rollback_active,
        should_rollback,
    )

    post = scan_event_store(agent_id, home=home, since_ts=state.promoted_at)
    if not should_rollback(
        pre_complaint_rate=state.pre_promotion_complaint_rate,
        post_complaint_rate=post.complaint_rate,
        post_n=post.total,
        config=config,
    ):
        return False

    bad_version = state.active_version
    pre_rate = state.pre_promotion_complaint_rate
    rollback_active(home)
    quarantine_candidate(bad_version, home)
    _invalidate_router_strategy_cache()
    state.active_version = None
    state.promoted_at = None
    state.pre_promotion_complaint_rate = None
    state.consecutive_failures += 1  # don't immediately re-promote the same data
    save_train_state(state, agent_id, home)
    write_receipt(
        agent_id,
        "rollback",
        {
            "rolled_back_version": bad_version,
            "reverted_to": "baseline",
            "pre_complaint_rate": pre_rate,
            "post_complaint_rate": post.complaint_rate,
            "post_samples": post.total,
        },
        home,
    )
    log.warning(
        "router_self_learning.rolled_back",
        agent_id=agent_id,
        version=bad_version,
        post_complaint_rate=post.complaint_rate,
    )
    return True


__all__ = [
    "Trainer",
    "UpdateResult",
    "in_process_trainer",
    "maybe_run_update_router",
    "subprocess_trainer",
    "write_receipt",
]
