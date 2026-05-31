"""Observe-first progress watchdog for agent turns."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ProgressAction = Literal["observe", "warn", "block"]


@dataclass(frozen=True)
class ProgressObservation:
    iteration: int
    provider_call_count: int = 0
    successful_tool_result: bool = False
    user_visible_output: bool = False
    artifact_completed: bool = False
    tool_error_signature: str | None = None
    provider_failure_signature: str | None = None


@dataclass(frozen=True)
class ProgressDecision:
    action: ProgressAction
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProgressWatchdog:
    """Detect repeated no-progress loops without owning the main turn loop."""

    def __init__(
        self,
        *,
        repeated_tool_error_threshold: int = 3,
        repeated_provider_failure_threshold: int = 2,
        observe_only: bool = True,
    ) -> None:
        self.repeated_tool_error_threshold = repeated_tool_error_threshold
        self.repeated_provider_failure_threshold = repeated_provider_failure_threshold
        self.observe_only = observe_only
        self._last_tool_error: str | None = None
        self._tool_error_count = 0
        self._last_provider_failure: str | None = None
        self._provider_failure_count = 0

    def observe(self, observation: ProgressObservation) -> ProgressDecision:
        if _has_progress(observation):
            self._reset_progress_sensitive_counts()
            return ProgressDecision("observe", "progress")

        tool_decision = self._record_repeated_tool_error(observation)
        if tool_decision is not None:
            return tool_decision

        provider_decision = self._record_repeated_provider_failure(observation)
        if provider_decision is not None:
            return provider_decision

        return ProgressDecision("observe", "no_signal")

    def _record_repeated_tool_error(
        self, observation: ProgressObservation
    ) -> ProgressDecision | None:
        signature = observation.tool_error_signature
        if not signature:
            return None
        if signature == self._last_tool_error:
            self._tool_error_count += 1
        else:
            self._last_tool_error = signature
            self._tool_error_count = 1
        if self._tool_error_count < self.repeated_tool_error_threshold:
            return None
        return self._decision(
            "repeated_tool_error",
            self._decision_details(observation, signature, self._tool_error_count),
        )

    def _record_repeated_provider_failure(
        self, observation: ProgressObservation
    ) -> ProgressDecision | None:
        signature = observation.provider_failure_signature
        if not signature:
            return None
        if signature == self._last_provider_failure:
            self._provider_failure_count += 1
        else:
            self._last_provider_failure = signature
            self._provider_failure_count = 1
        if self._provider_failure_count < self.repeated_provider_failure_threshold:
            return None
        return self._decision(
            "repeated_provider_failure",
            self._decision_details(observation, signature, self._provider_failure_count),
        )

    def _decision_details(
        self,
        observation: ProgressObservation,
        signature: str,
        count: int,
    ) -> dict[str, Any]:
        return {
            "signature": signature,
            "count": count,
            "iteration": observation.iteration,
            "provider_call_count": observation.provider_call_count,
        }

    def _decision(self, reason: str, details: dict[str, Any]) -> ProgressDecision:
        if self.observe_only:
            return ProgressDecision("warn", reason, details)
        return ProgressDecision("block", reason, details)

    def _reset_progress_sensitive_counts(self) -> None:
        self._last_tool_error = None
        self._tool_error_count = 0
        self._last_provider_failure = None
        self._provider_failure_count = 0


def _has_progress(observation: ProgressObservation) -> bool:
    return (
        observation.successful_tool_result
        or observation.user_visible_output
        or observation.artifact_completed
    )
