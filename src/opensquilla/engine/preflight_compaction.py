"""Engine-owned pre-history compaction coordination."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

import structlog

from opensquilla.engine.cache_break_monitor import notify_compaction

DEFAULT_PREFLIGHT_COMPACT_RATIO: Final[float] = 0.85
T3_NOT_APPLICABLE: Final[str] = "not_applicable"
T3_HANDLED: Final[str] = "handled"
T3_FLUSH_FAILED: Final[str] = "flush_failed"
T3_COMPACT_FAILED: Final[str] = "compact_failed"
_SAFE_FLUSH_OUTPUT_COVERAGE_STATUSES: Final[frozenset[str]] = frozenset(
    {"ok", "unverifiable"}
)
_SAFE_FLUSH_OBLIGATION_STATUSES: Final[frozenset[str]] = frozenset(
    {"ok", "backfilled", "unverifiable"}
)

log = structlog.get_logger(__name__)


def preflight_compact_ratio(config: Any | None) -> float:
    raw_ratio = getattr(config, "preflight_compact_ratio", None)
    if raw_ratio is None:
        return DEFAULT_PREFLIGHT_COMPACT_RATIO
    try:
        ratio = float(raw_ratio)
    except (TypeError, ValueError):
        return DEFAULT_PREFLIGHT_COMPACT_RATIO
    if ratio <= 0.0 or ratio > 1.0:
        return DEFAULT_PREFLIGHT_COMPACT_RATIO
    return ratio


def pre_compaction_flush_enabled(config: Any | None, session_flush_service: Any | None) -> bool:
    from opensquilla.memory.flush_config import is_session_flush_enabled

    if not is_session_flush_enabled():
        return False

    memory_cfg = getattr(config, "memory", None)
    if memory_cfg is None:
        return session_flush_service is not None

    raw_enabled = getattr(memory_cfg, "flush_enabled", True)
    if isinstance(raw_enabled, str):
        return raw_enabled.strip().lower() not in {"0", "false", "no", "off"}
    return bool(raw_enabled)


def pre_compaction_flush_timeout_seconds(config: Any | None) -> float:
    memory_cfg = getattr(config, "memory", None)
    raw_timeout = getattr(memory_cfg, "flush_timeout_seconds", 5.0)
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        return 5.0
    return max(timeout, 0.0)


def _receipt_value(receipt: Any, name: str, default: Any) -> Any:
    if isinstance(receipt, Mapping):
        return receipt.get(name, default)
    return getattr(receipt, name, default)


def _receipt_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def flush_receipt_allows_destructive_compaction(receipt: Any) -> bool:
    if _receipt_value(receipt, "mode", None) != "llm":
        return False
    if _receipt_int(_receipt_value(receipt, "indexed_chunk_count", 0)) <= 0:
        return False
    integrity_status = str(
        _receipt_value(receipt, "integrity_status", "unverified") or "unverified"
    )
    if integrity_status != "ok":
        return False
    output_coverage_status = str(
        _receipt_value(receipt, "output_coverage_status", "unverified") or "unverified"
    )
    if output_coverage_status not in _SAFE_FLUSH_OUTPUT_COVERAGE_STATUSES:
        return False
    if _receipt_int(_receipt_value(receipt, "invalid_candidate_count", 0)) > 0:
        return False
    if _receipt_value(receipt, "candidate_missing_ids", []):
        return False
    obligation_status = str(
        _receipt_value(receipt, "obligation_status", "unverified") or "unverified"
    )
    if obligation_status not in _SAFE_FLUSH_OBLIGATION_STATUSES:
        return False
    return not _receipt_value(receipt, "obligation_missing_ids", [])


@dataclass(slots=True)
class PreflightCompactionCoordinator:
    """Coordinate pre-history flush and compaction while persistence stays in sessions."""

    session_manager: Any | None
    session_flush_service: Any | None
    config: Any | None
    compaction_circuit_open: Callable[[str], bool]
    record_compaction_failure: Callable[[str], None]
    record_compaction_success: Callable[[str], None]
    compaction_notifier: Callable[[str], None] = notify_compaction

    async def maybe_compact_on_t3_upgrade(
        self,
        session_key: str,
        turn: Any,
        context_window_tokens: int,
        *,
        compaction_provider: Any | None = None,
        compaction_model: str | None = None,
    ) -> str:
        """Flush memory and compact transcript when the router upgrades into t3."""

        router_cfg = getattr(self.config, "squilla_router", None)
        if not getattr(router_cfg, "upgrade_to_t3_compaction_enabled", False):
            return T3_NOT_APPLICABLE

        routed_tier = turn.metadata.get("routed_tier")
        if routed_tier != "t3":
            return T3_NOT_APPLICABLE

        if not turn.metadata.get("routing_applied", False):
            return T3_NOT_APPLICABLE

        routing_extra = turn.metadata.get("routing_extra", {})
        previous = routing_extra.get("previous_tier")
        if previous is None:
            final = routing_extra.get("final_tier")
            base = routing_extra.get("base_tier")
            if final == "t3" and base in {"t0", "t1", "t2"}:
                previous = base
            else:
                return T3_NOT_APPLICABLE

        if previous not in {"t0", "t1", "t2"}:
            return T3_NOT_APPLICABLE

        if session_key.startswith(("cron:", "subagent:")):
            return T3_NOT_APPLICABLE

        if self.session_manager is None:
            return T3_NOT_APPLICABLE

        if self.compaction_circuit_open(session_key):
            return T3_HANDLED

        try:
            transcript = await self.session_manager.get_transcript(session_key)
        except KeyError:
            return T3_HANDLED
        if not transcript:
            return T3_HANDLED

        log.info(
            "t3_upgrade_compaction.triggered",
            session_key=session_key,
            previous_tier=previous,
            final_tier="t3",
            context_window_tokens=context_window_tokens,
        )

        flush_status = await self._flush_before_compaction(
            transcript,
            session_key,
            event_prefix="t3_upgrade_compaction",
            log_success=True,
        )
        if flush_status == "failed":
            return T3_FLUSH_FAILED

        compacted = await self._compact_transcript(
            session_key,
            context_window_tokens,
            compaction_provider=compaction_provider,
            compaction_model=compaction_model,
            failed_event="t3_upgrade_compaction.compact_failed",
        )
        if compacted is None:
            return T3_COMPACT_FAILED

        log.info(
            "t3_upgrade_compaction.compact_done",
            session_key=session_key,
            summary_produced=bool(compacted),
            summary_length=len(compacted) if compacted else 0,
        )
        return T3_HANDLED

    async def maybe_preflight_compact(
        self,
        session_key: str,
        context_window_tokens: int,
        *,
        compaction_provider: Any | None = None,
        compaction_model: str | None = None,
    ) -> None:
        """Compact proactively if session history exceeds token budget."""

        if self.session_manager is None:
            return
        if session_key.startswith(("cron:", "subagent:")):
            return
        if self.compaction_circuit_open(session_key):
            return
        try:
            transcript = await self.session_manager.get_transcript(session_key)
        except KeyError:
            return
        if not transcript:
            return

        from opensquilla.session.tokenizer import estimate_tokens

        total_tokens = sum(estimate_tokens(e.content or "") for e in transcript)
        ratio = preflight_compact_ratio(self.config)
        threshold = int(context_window_tokens * ratio)
        if total_tokens <= threshold:
            return

        log.info(
            "preflight_compaction.triggered",
            session_key=session_key,
            total_tokens=total_tokens,
            threshold=threshold,
            ratio=ratio,
        )

        flush_status = await self._flush_before_compaction(
            transcript,
            session_key,
            event_prefix="preflight_compaction",
            log_success=False,
        )
        if flush_status == "failed":
            return

        await self._compact_transcript(
            session_key,
            context_window_tokens,
            compaction_provider=compaction_provider,
            compaction_model=compaction_model,
            failed_event="preflight_compaction.compact_failed",
        )

    async def _flush_before_compaction(
        self,
        transcript: Any,
        session_key: str,
        *,
        event_prefix: str,
        log_success: bool,
    ) -> str:
        if not pre_compaction_flush_enabled(self.config, self.session_flush_service):
            return "skipped"
        if self.session_flush_service is None:
            log.warning(
                f"{event_prefix}.flush_failed",
                session_key=session_key,
                error="flush_service_unavailable",
            )
            self.record_compaction_failure(session_key)
            return "failed"

        flush_t0 = time.monotonic()
        try:
            from opensquilla.session.keys import parse_agent_id

            receipt = await self.session_flush_service.execute(
                transcript,
                session_key,
                agent_id=parse_agent_id(session_key),
                message_window=0,
                segment_mode="auto",
                timeout=pre_compaction_flush_timeout_seconds(self.config),
            )
            if not flush_receipt_allows_destructive_compaction(receipt):
                log.warning(
                    f"{event_prefix}.flush_failed",
                    session_key=session_key,
                    error=getattr(receipt, "error", None) or "degraded_flush_receipt",
                    mode=getattr(receipt, "mode", "unknown"),
                    integrity_status=getattr(receipt, "integrity_status", None),
                    indexed_chunk_count=getattr(receipt, "indexed_chunk_count", None),
                    output_coverage_status=getattr(
                        receipt,
                        "output_coverage_status",
                        None,
                    ),
                    invalid_candidate_count=getattr(
                        receipt,
                        "invalid_candidate_count",
                        None,
                    ),
                    candidate_missing_ids=getattr(receipt, "candidate_missing_ids", None),
                    obligation_status=getattr(receipt, "obligation_status", None),
                    obligation_missing_ids=getattr(receipt, "obligation_missing_ids", None),
                )
                self.record_compaction_failure(session_key)
                return "failed"
            if log_success:
                log.info(
                    f"{event_prefix}.flush_done",
                    session_key=session_key,
                    mode=getattr(receipt, "mode", "unknown"),
                    message_count=getattr(receipt, "message_count", 0),
                    duration_ms=int((time.monotonic() - flush_t0) * 1000),
                )
            return "flushed"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning(
                f"{event_prefix}.flush_failed",
                session_key=session_key,
                error=str(exc),
            )
            self.record_compaction_failure(session_key)
            return "failed"

    async def _compact_transcript(
        self,
        session_key: str,
        context_window_tokens: int,
        *,
        compaction_provider: Any | None,
        compaction_model: str | None,
        failed_event: str,
    ) -> str | None:
        if self.session_manager is None:
            return ""
        compaction_config = None
        if compaction_provider is not None or compaction_model:
            from opensquilla.session.compaction import build_compaction_config_from_provider

            compaction_config = build_compaction_config_from_provider(
                compaction_provider,
                model_override=compaction_model,
                compaction_config=getattr(getattr(self, "config", None), "compaction", None),
            )
        from opensquilla.session.compaction import call_compact_with_optional_config

        try:
            result = await call_compact_with_optional_config(
                self.session_manager.compact,
                session_key,
                context_window_tokens,
                compaction_config,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning(
                failed_event,
                session_key=session_key,
                error=str(exc),
            )
            self.record_compaction_failure(session_key)
            return None
        self.record_compaction_success(session_key)
        if result:
            self.compaction_notifier(session_key)
        return result
