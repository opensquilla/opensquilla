"""Structured, content-free decision logs for every ensemble selection mode."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import structlog

log = structlog.get_logger(__name__)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value]


def _candidate_fields(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: candidate.get(key)
        for key in (
            "identity",
            "provider",
            "model",
            "version",
            "source",
            "vendor",
            "family",
            "status",
            "roles",
            "context_window",
            "modalities",
            "health",
            "credential_available",
            "tier_prior",
            "quality_prior",
            "cost_latency_prior",
            "architecture",
            "profile_hash",
        )
        if key in candidate
    }


def _log_observability_failure(
    *,
    decision_id: str,
    selection_mode: str,
    stage: str,
    emitted_sequence: int | None = None,
) -> None:
    fields: dict[str, Any] = {
        "decision_id": decision_id,
        "selection_mode": selection_mode,
        "stage": stage,
        "exc_info": True,
    }
    if emitted_sequence is not None:
        fields["emitted_sequence"] = emitted_sequence
    try:
        log.warning("llm_ensemble.routing.decision_log_failed", **fields)
    except Exception:  # noqa: BLE001 - even a broken log processor must fail open
        pass


def log_ensemble_decision_started(
    *,
    decision_id: str,
    selection_mode: str,
    turn_metadata: Mapping[str, Any] | None,
    user_profile_enabled: bool | None,
) -> None:
    """Log the local-router input before an ensemble strategy starts."""

    try:
        metadata = _mapping(turn_metadata)
        extra = _mapping(metadata.get("routing_extra"))
        complaint_terms = extra.get("complaint_terms")
        complaint_terms_count = (
            len(complaint_terms)
            if isinstance(complaint_terms, Sequence)
            and not isinstance(complaint_terms, (str, bytes))
            else 0
        )
        log.info(
            "llm_ensemble.routing.decision_started",
            decision_id=decision_id,
            sequence=0,
            selection_mode=selection_mode,
            routed_tier=metadata.get("routed_tier"),
            routed_model=metadata.get("routed_model")
            or metadata.get("routed_model_before_ensemble"),
            routing_confidence=metadata.get("routing_confidence"),
            routing_source=metadata.get("routing_source"),
            route_class=extra.get("route_class"),
            base_tier=extra.get("base_tier"),
            pre_confidence_tier=extra.get("pre_confidence_tier"),
            final_tier=extra.get("final_tier"),
            final_route_class=extra.get("final_route_class"),
            confidence_threshold=extra.get("confidence_threshold"),
            confidence_gate_applied=extra.get("confidence_gate_applied"),
            anti_downgrade_applied=extra.get("anti_downgrade_applied"),
            previous_tier=extra.get("previous_tier"),
            complaint_upgrade_applied=extra.get("complaint_upgrade_applied"),
            complaint_terms_count=complaint_terms_count,
            large_context_floor_applied=extra.get("large_context_floor_applied"),
            large_context_floor_from_tier=extra.get(
                "large_context_floor_from_tier"
            ),
            large_context_floor_min_tier=extra.get("large_context_floor_min_tier"),
            probabilities=extra.get("probabilities"),
            margin=extra.get("margin"),
            user_profile_enabled=user_profile_enabled,
        )
    except Exception:  # noqa: BLE001 - observability must never break routing
        _log_observability_failure(
            decision_id=decision_id,
            selection_mode=selection_mode,
            stage="started",
        )


def log_ensemble_decision_failed(
    *,
    decision_id: str,
    selection_mode: str,
    reason: str,
    error: BaseException,
) -> None:
    """Log a failed selection after ``decision_started``."""

    try:
        log.warning(
            "llm_ensemble.routing.decision_failed",
            decision_id=decision_id,
            sequence=1,
            selection_mode=selection_mode,
            reason=reason,
            error_type=type(error).__name__,
            error=str(error),
        )
    except Exception:  # noqa: BLE001 - observability must never break routing
        _log_observability_failure(
            decision_id=decision_id,
            selection_mode=selection_mode,
            stage="failed",
        )


def log_ensemble_decision_skipped(
    *,
    decision_id: str,
    selection_mode: str,
    reason: str,
) -> None:
    """Log an ensemble attempt rejected by a readiness gate."""

    try:
        log.warning(
            "llm_ensemble.routing.decision_skipped",
            decision_id=decision_id,
            sequence=1,
            selection_mode=selection_mode,
            reason=reason,
        )
    except Exception:  # noqa: BLE001 - observability must never break routing
        _log_observability_failure(
            decision_id=decision_id,
            selection_mode=selection_mode,
            stage="skipped",
        )


def log_ensemble_decision_steps(
    *,
    decision_id: str,
    selection_mode: str,
    profile_name: str,
    selection_plan: Mapping[str, Any],
) -> None:
    """Emit replay-oriented selection steps without prompts or profile contents."""

    sequence = 0

    def emit(event: str, **fields: Any) -> None:
        nonlocal sequence
        sequence += 1
        log.info(
            event,
            decision_id=decision_id,
            sequence=sequence,
            selection_mode=selection_mode,
            profile=profile_name,
            **fields,
        )

    try:
        plan = _mapping(selection_plan)
        strategy = str(plan.get("strategy") or selection_mode)
        if selection_mode == "router_dynamic":
            emit(
                "llm_ensemble.routing.task_analysis_recorded",
                task_analyzer=dict(_mapping(plan.get("task_analyzer"))),
                task_profile_hash=plan.get("task_profile_hash"),
                request_context_hash=plan.get("request_context_hash"),
            )
            emit(
                "llm_ensemble.routing.proposer_bounds_recorded",
                effective_tier=plan.get("effective_tier"),
                N_min=plan.get("N_min"),
                N_max=plan.get("N_max"),
                bound_reasons=plan.get("bound_reasons"),
                top_l=plan.get("top_l"),
                quality_floor=plan.get("quality_floor"),
            )
            session = _mapping(plan.get("session"))
            emit(
                "llm_ensemble.routing.session_adjustment_recorded",
                session=dict(session),
            )
        candidate_pool = _rows(plan.get("candidate_pool"))
        for index, candidate in enumerate(candidate_pool):
            emit(
                "llm_ensemble.routing.candidate_recorded",
                candidate_index=index,
                candidate=_candidate_fields(candidate),
            )

        if selection_mode == "router_dynamic":
            hard_filter = _mapping(plan.get("hard_filter"))
            for row in [
                *_rows(hard_filter.get("proposer_results")),
                *_rows(hard_filter.get("aggregator_results")),
            ]:
                emit(
                    "llm_ensemble.routing.hard_filter_recorded",
                    result=dict(row),
                )
            for row in _rows(plan.get("model_scores")):
                emit(
                    "llm_ensemble.routing.model_score_recorded",
                    result=dict(row),
                )
            for row in _rows(plan.get("selection_steps")):
                emit(
                    "llm_ensemble.routing.proposer_step_recorded",
                    result=dict(row),
                )
            aggregator = _mapping(plan.get("aggregator"))
            for rank, row in enumerate(_rows(aggregator.get("scores")), start=1):
                emit(
                    "llm_ensemble.routing.aggregator_score_recorded",
                    rank=rank,
                    result=dict(row),
                )
        elif selection_mode == "router_tree_baseline":
            for row in _rows(plan.get("slots")):
                emit(
                    "llm_ensemble.routing.proposer_step_recorded",
                    result=dict(row),
                )
            aggregator = _mapping(plan.get("aggregator"))
            for rank, row in enumerate(_rows(aggregator.get("top_candidates")), start=1):
                emit(
                    "llm_ensemble.routing.aggregator_score_recorded",
                    rank=rank,
                    result=dict(row),
                )
        else:
            for index, identity in enumerate(_strings(plan.get("selected_P")), start=1):
                emit(
                    "llm_ensemble.routing.proposer_step_recorded",
                    result={
                        "step": index,
                        "selected": identity,
                        "selection_source": strategy,
                    },
                )

        selected_p = _strings(plan.get("selected_P"))
        selected_a = str(plan.get("selected_A") or "")
        aggregator_plan = _mapping(plan.get("aggregator"))
        if selection_mode == "router_dynamic":
            aggregator_detail = dict(_mapping(aggregator_plan.get("selected")))
        elif aggregator_plan:
            aggregator_detail = dict(aggregator_plan)
        else:
            aggregator_detail = {
                "model": plan.get("aggregator_model"),
                "selection_source": strategy,
            }
        emit(
            "llm_ensemble.routing.aggregator_selected",
            selected_A=selected_a,
            result=aggregator_detail,
        )
        emit(
            "llm_ensemble.routing.decision_completed",
            strategy=strategy,
            routed_tier=plan.get("routed_tier"),
            effective_tier=plan.get("effective_tier"),
            routing_confidence=plan.get("routing_confidence"),
            user_profile_enabled=plan.get("user_profile_enabled"),
            # Which profile, not just whether one was on: a learned profile
            # changes with every thumb, so the enabled bit alone cannot
            # explain a decision after the fact. Both are safe to log — a
            # content hash and an enum.
            user_profile_version=plan.get("user_profile_version"),
            user_profile_source=plan.get("user_profile_source"),
            selected_P=selected_p,
            selected_A=selected_a,
            proposer_count=len(selected_p),
            stop_reason=plan.get("stop_reason"),
            coverage_shortfall=plan.get("coverage_shortfall"),
            ranking_version=plan.get("ranking_version"),
            algorithm_version=plan.get("algorithm_version"),
            config_version=plan.get("ranking_config_version") or plan.get("config_version"),
            config_hash=plan.get("ranking_config_hash") or plan.get("config_hash"),
            effective_min_successful_proposers=plan.get("effective_min_successful_proposers"),
            effective_proposer_timeout_seconds=plan.get("effective_proposer_timeout_seconds"),
            effective_aggregator_timeout_seconds=plan.get("effective_aggregator_timeout_seconds"),
            effective_shuffle_candidates=plan.get("effective_shuffle_candidates"),
        )
    except Exception:  # noqa: BLE001 - observability must never break routing
        _log_observability_failure(
            decision_id=decision_id,
            selection_mode=selection_mode,
            stage="steps",
            emitted_sequence=sequence,
        )
