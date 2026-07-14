"""Independent, fail-closed review for one exact sandbox elevation action."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Literal, cast

from opensquilla.engine.guardian_prompt import (
    build_guardian_prompt,
    guardian_output_schema,
    guardian_policy_prompt,
)
from opensquilla.provider import LLMProvider
from opensquilla.provider.types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ProviderHeartbeatEvent,
    ReasoningDeltaEvent,
    TextDeltaEvent,
    ToolUseDeltaEvent,
    ToolUseEndEvent,
    ToolUseStartEvent,
)
from opensquilla.sandbox.approval_runtime import ApprovalAction
from opensquilla.sandbox.elevation import ElevationAction

if TYPE_CHECKING:
    from opensquilla.engine.guardian_session import GuardianReviewSessionManager

RiskLevel = Literal["low", "medium", "high", "critical"]
AuthorizationLevel = Literal["unknown", "low", "medium", "high"]
GuardianOutcome = Literal["allow", "deny"]
GuardianStatus = Literal["completed", "timed_out", "failed_closed", "aborted"]

_RISK_LEVELS = {"low", "medium", "high", "critical"}
_AUTHORIZATION_LEVELS = {"unknown", "low", "medium", "high"}
_OUTCOMES = {"allow", "deny"}
GUARDIAN_POLICY = guardian_policy_prompt()

_TRANSIENT_PROVIDER_CODES = frozenset(
    {
        "server_overloaded",
        "http_connection_failed",
        "response_stream_connection_failed",
        "internal_server_error",
        "response_stream_disconnected",
        "request_error",
        "provider_internal",
        "429",
        "500",
        "502",
        "503",
        "504",
    }
)


class _GuardianProviderError(RuntimeError):
    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True)
class GuardianAssessment:
    risk_level: RiskLevel
    user_authorization: AuthorizationLevel
    outcome: GuardianOutcome
    rationale: str
    status: GuardianStatus = "completed"
    attempt_count: int = 1
    latency_ms: int = 0


@dataclass
class GuardianCircuitBreaker:
    """Codex per-turn denial circuit: 3 consecutive or 10 of the last 50."""

    consecutive_denials: int = 0
    recent_denials: deque[bool] = dataclass_field(
        default_factory=lambda: deque(maxlen=50)
    )
    _interrupt_triggered: bool = False

    @property
    def recent_denial_count(self) -> int:
        return sum(self.recent_denials)

    @property
    def is_open(self) -> bool:
        return self._interrupt_triggered

    def observe(self, assessment: GuardianAssessment) -> bool:
        denied = assessment.status == "completed" and assessment.outcome == "deny"
        self.recent_denials.append(denied)
        if denied:
            self.consecutive_denials += 1
        else:
            self.consecutive_denials = 0
        if self._interrupt_triggered:
            return False
        if self.consecutive_denials >= 3 or self.recent_denial_count >= 10:
            self._interrupt_triggered = True
            return True
        return False


def parse_guardian_assessment(text: str) -> GuardianAssessment:
    """Parse a Guardian assessment with Codex's thin JSON recovery path."""

    stripped = text.strip()
    if not stripped:
        raise ValueError("empty_guardian_response")

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("guardian_response_not_json") from None
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            raise ValueError("guardian_response_not_json") from None

    if not isinstance(payload, dict):
        raise ValueError("invalid_guardian_schema")

    outcome = payload.get("outcome")
    if not isinstance(outcome, str) or outcome not in _OUTCOMES:
        raise ValueError("invalid_guardian_outcome")

    risk = payload.get("risk_level")
    if risk is None:
        risk = "low" if outcome == "allow" else "high"
    if not isinstance(risk, str) or risk not in _RISK_LEVELS:
        raise ValueError("invalid_guardian_risk")

    authorization = payload.get("user_authorization")
    if authorization is None:
        authorization = "unknown"
    if not isinstance(authorization, str) or authorization not in _AUTHORIZATION_LEVELS:
        raise ValueError("invalid_guardian_authorization")

    rationale = payload.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        raise ValueError("invalid_guardian_rationale")
    if not rationale or not rationale.strip():
        rationale = (
            "Auto-review returned a low-risk allow decision."
            if outcome == "allow"
            else "Auto-review returned a deny decision without a rationale."
        )

    return GuardianAssessment(
        risk_level=cast("RiskLevel", risk),
        user_authorization=cast("AuthorizationLevel", authorization),
        outcome=cast("GuardianOutcome", outcome),
        rationale=rationale.strip(),
    )


def enforce_guardian_thresholds(assessment: GuardianAssessment) -> GuardianAssessment:
    """Apply risk gates that a reviewer response can never override."""

    if assessment.risk_level == "critical":
        return replace(
            assessment,
            outcome="deny",
            rationale=f"{assessment.rationale} Critical-risk elevation is never automatic.",
        )
    if assessment.risk_level == "high" and assessment.user_authorization in {
        "unknown",
        "low",
    }:
        return replace(
            assessment,
            outcome="deny",
            rationale=(
                f"{assessment.rationale} High-risk elevation requires explicit, "
                "sufficient user authorization."
            ),
        )
    return assessment


def _message_content_text(message: Message) -> str:
    if isinstance(message.content, str):
        return message.content

    parts: list[str] = []
    for block in message.content:
        block_type = getattr(block, "type", "unknown")
        if block_type == "text":
            parts.append(str(getattr(block, "text", "")))
        elif block_type == "tool_use":
            parts.append(
                json.dumps(
                    {
                        "tool": getattr(block, "name", ""),
                        "input": getattr(block, "input", {}),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
            )
        elif block_type == "tool_result":
            parts.append(str(getattr(block, "content", "")))
        elif block_type in {"image", "document"}:
            parts.append(f"[{block_type} content omitted]")
        elif block_type == "compaction":
            parts.append(str(getattr(block, "content", "")))
    return "\n".join(part for part in parts if part)


def project_guardian_transcript(
    messages: list[Message],
    *,
    max_chars: int = 12_000,
) -> list[dict[str, str]]:
    """Return a bounded recent transcript with explicit trust labels."""

    if max_chars <= 0:
        return []

    projected: list[dict[str, str]] = []
    remaining = max_chars
    for message in reversed(messages):
        content = _message_content_text(message)
        if not content:
            continue
        if len(content) > remaining:
            content = content[-remaining:]
        projected.append(
            {
                "role": message.role,
                "trust": (
                    "trusted_user" if message.role == "user" else "untrusted_assistant"
                ),
                "content": content,
            }
        )
        remaining -= len(content)
        if remaining <= 0:
            break
    projected.reverse()
    return projected


class GuardianReviewer:
    """Review elevated actions under one Codex-compatible overall deadline."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        timeout_seconds: float = 90.0,
        max_attempts: int = 3,
        session: GuardianReviewSessionManager | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("guardian_timeout_must_be_positive")
        if not 1 <= max_attempts <= 3:
            raise ValueError("guardian_max_attempts_out_of_range")
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._session = session

    async def review(
        self,
        action: ElevationAction | ApprovalAction,
        transcript: list[Message],
    ) -> GuardianAssessment:
        proposed_action = (
            action.guardian_payload()
            if isinstance(action, ApprovalAction)
            else action.canonical_payload()
        )
        request_payload = build_guardian_prompt(transcript, proposed_action).text
        started = time.monotonic()
        try:
            assessment = await asyncio.wait_for(
                self._review_attempts(
                    request_payload,
                    proposed_action=proposed_action,
                    transcript=transcript,
                ),
                timeout=self._timeout_seconds,
            )
            return replace(
                assessment,
                latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
        except TimeoutError:
            return GuardianAssessment(
                risk_level="high",
                user_authorization="unknown",
                outcome="deny",
                rationale="Automatic approval review timed out and failed closed.",
                status="timed_out",
                latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
        except asyncio.CancelledError:
            return GuardianAssessment(
                risk_level="high",
                user_authorization="unknown",
                outcome="deny",
                rationale="Automatic approval review was aborted and failed closed.",
                status="aborted",
                latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            )

    async def _review_attempts(
        self,
        request_payload: str,
        *,
        proposed_action: dict[str, object],
        transcript: list[Message],
    ) -> GuardianAssessment:
        last_error = "unknown review error"
        for _attempt in range(self._max_attempts):
            try:
                return replace(
                    await self._review_once(
                        request_payload,
                        proposed_action=proposed_action,
                        transcript=transcript,
                    ),
                    attempt_count=_attempt + 1,
                )
            except ValueError as exc:
                last_error = str(exc) or type(exc).__name__
                continue
            except _GuardianProviderError as exc:
                last_error = str(exc) or type(exc).__name__
                if exc.transient:
                    continue
                break
            except TimeoutError:
                raise
            except Exception as exc:
                last_error = str(exc) or type(exc).__name__
                if bool(getattr(exc, "transient", False)):
                    continue
                break

        return GuardianAssessment(
            risk_level="high",
            user_authorization="unknown",
            outcome="deny",
            rationale=f"Automatic approval review failed closed: {last_error}",
            status="failed_closed",
            attempt_count=_attempt + 1,
        )

    async def _review_once(
        self,
        request_payload: str,
        *,
        proposed_action: dict[str, object],
        transcript: list[Message],
    ) -> GuardianAssessment:
        if self._session is not None:
            response = await self._session.review_action(
                transcript,
                proposed_action,
                response_validator=parse_guardian_assessment,
            )
            return parse_guardian_assessment(response)

        response_parts: list[str] = []
        completed = False
        config = ChatConfig(
            system=GUARDIAN_POLICY,
            max_tokens=1_000,
            temperature=0,
            thinking=False,
            timeout=self._timeout_seconds,
            cache_mode="off",
            output_json_schema=guardian_output_schema(),
            output_json_schema_strict=False,
        )
        stream = self._provider.chat(
            [Message(role="user", content=request_payload)],
            tools=None,
            config=config,
        )
        async for event in stream:
            if isinstance(event, TextDeltaEvent):
                response_parts.append(event.text)
            elif isinstance(event, ErrorEvent):
                code = str(event.code or "").strip().lower()
                raise _GuardianProviderError(
                    event.message or code or "guardian_provider_error",
                    transient=code in _TRANSIENT_PROVIDER_CODES,
                )
            elif isinstance(event, (ToolUseStartEvent, ToolUseDeltaEvent, ToolUseEndEvent)):
                raise ValueError("guardian_requested_tool")
            elif isinstance(event, DoneEvent):
                completed = True
            elif isinstance(
                event,
                (ReasoningDeltaEvent, ProviderHeartbeatEvent),
            ):
                continue
        if not completed:
            raise RuntimeError("guardian_stream_incomplete")
        return parse_guardian_assessment("".join(response_parts))
