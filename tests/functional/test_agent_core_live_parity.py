"""Opt-in live parity gate for selectable agent kernels.

These tests spend real API credits and are skipped unless explicitly enabled.
They exercise the public ``AgentEvent`` boundary rather than CLI/TUI contracts.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import structlog.testing

from opensquilla.engine import Agent, AgentConfig, ToolCall, ToolResult
from opensquilla.engine.agent_core import build_agent_for_kernel
from opensquilla.engine.agent_core_metrics import (
    AgentCoreParityThresholds,
    collect_agent_core_run_metrics,
    compare_agent_core_metrics,
)
from opensquilla.engine.types import AgentEvent, DoneEvent, RunHeartbeatEvent
from opensquilla.provider.openai import OpenAIProvider
from opensquilla.provider.types import ToolDefinition, ToolInputSchema, ToolParam

_PROMPT = (
    "Call echo_marker with marker LIVE_AGENT_CORE_PARITY, then reply with exactly "
    "the tool result and no extra words."
)
_ORCHESTRATION_PROMPT = (
    "First call sessions_spawn with prompt CHILD_PARITY_PROBE. "
    "Then call sessions_send to agent:main:live-agent-core-child with message "
    "CHILD_PARITY_MESSAGE. Then call sessions_yield with reason "
    "LIVE_AGENT_CORE_YIELD. After all tool calls finish, reply with exactly "
    "YIELDED."
)


class _FixedLiveParityDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        fixed = cls(2026, 6, 8, 12, 0, tzinfo=UTC)
        if tz is not None:
            return fixed.astimezone(tz)
        return fixed


def _freeze_live_runtime_context(monkeypatch: pytest.MonkeyPatch) -> None:
    import opensquilla.engine.agent as agent_module

    monkeypatch.setattr(agent_module, "datetime", _FixedLiveParityDateTime)


def _stable_live_events(events: list[AgentEvent]) -> list[AgentEvent]:
    return [
        event
        for event in events
        if not (
            isinstance(event, RunHeartbeatEvent)
            and event.phase == "llm_fallback"
            and "stream timed out" in event.message
        )
    ]

_PROVIDER_PROOF_IDENTITY_KEYS = (
    "proof_budget",
    "raw_proof_budget",
    "effective_proof_budget",
    "proof_headroom_chars",
    "fallback_reason",
    "compact_needed",
    "tool_argument_projection_scrubbed",
    "recent_tail_too_large",
    "compaction_not_smaller",
    "tool_payload_compaction_not_smaller",
    "tail_compaction_not_smaller",
    "emergency_current_turn_compacted",
    "emergency_compaction_not_smaller",
    "final_hard_cap_compacted",
    "final_hard_cap_not_smaller",
)

_PROVIDER_PROOF_INTEGER_METADATA_KEYS = (
    "proof_budget",
    "raw_proof_budget",
    "effective_proof_budget",
    "proof_headroom_chars",
)

_PROVIDER_PROOF_BOOLEAN_METADATA_KEYS = (
    "compact_needed",
    "tool_argument_projection_scrubbed",
    "recent_tail_too_large",
    "compaction_not_smaller",
    "tool_payload_compaction_not_smaller",
    "tail_compaction_not_smaller",
    "emergency_current_turn_compacted",
    "emergency_compaction_not_smaller",
    "final_hard_cap_compacted",
    "final_hard_cap_not_smaller",
)

_PROVIDER_PROOF_STRING_METADATA_KEYS = ("fallback_reason",)


@dataclass(frozen=True)
class _LiveRunResult:
    events: list[AgentEvent]
    provider_proofs: tuple[dict[str, Any], ...]
    session_write_count: int = 0
    session_write_fingerprints: tuple[str, ...] = ()


class _SessionWriteRecorder:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    async def append_message(self, session_key: str, **kwargs: Any) -> None:
        self.writes.append({"session_key": session_key, **kwargs})


def _provider_proofs_from_logs(logs: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            key: value
            for key, value in log_entry.items()
            if key not in {"event", "log_level"}
        }
        for log_entry in logs
        if log_entry.get("event") == "provider.request_proof"
    )

_FAKE_PI_LIVE_COMMAND_MARKERS = (
    "fake_pi",
    "fake-pi",
    "fakepi",
    "fake_sidecar",
    "fake-sidecar",
    "mock_pi",
    "mock-pi",
    "mock_sidecar",
    "mock-sidecar",
    "fixture_pi",
    "fixture-pi",
    "pi_fixture",
    "pi-fixture",
    "fixture_sidecar",
    "fixture-sidecar",
    "sleeping_pi",
    "feedback_pi",
    "contract_test",
    "contract-test",
    "test_fixture",
    "test-fixture",
    "test_agent_core",
    "tests/",
    "tests\\",
    "/tests/",
    "\\tests\\",
    "-m tests.",
    "example_pi",
    "example-pi",
    "example_sidecar",
    "example-sidecar",
    "sample_pi",
    "sample-pi",
    "sample_sidecar",
    "sample-sidecar",
    "demo_pi",
    "demo-pi",
    "demo_sidecar",
    "demo-sidecar",
    "examples/",
    "examples\\",
    "/examples/",
    "\\examples\\",
    "-m examples.",
    "samples/",
    "samples\\",
    "/samples/",
    "\\samples\\",
    "-m samples.",
    "demos/",
    "demos\\",
    "/demos/",
    "\\demos\\",
    "-m demos.",
    "example",
    "sample",
    "demo",
)
_FAKE_PI_LIVE_PROVENANCE_MARKERS = (
    "fake",
    "mock",
    "dummy",
    "stub",
    "fixture",
    "test fixture",
    "test-only",
    "contract test",
    "contract-test",
    "example",
    "sample",
    "demo",
)
_PI_LIVE_TEST_FIXTURE_OPT_IN_ENV_VARS = (
    "OPENSQUILLA_AGENT_CORE_ALLOW_TEST_PI_RPC_COMMAND",
    "OPENSQUILLA_AGENT_CORE_ALLOW_TEST_PI_RPC_CLIENT",
    "OPENSQUILLA_ALLOW_TEST_PI_RPC_COMMAND",
    "OPENSQUILLA_ALLOW_TEST_PI_RPC_CLIENT",
)


def _live_pi_rpc_command_provenance() -> str | None:
    provenance = os.environ.get(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE",
        "",
    ).strip()
    return provenance or None


def _looks_like_fake_or_test_pi_live_command(value: str | None) -> bool:
    if value is None:
        return False
    lowered = value.lower()
    return any(marker in lowered for marker in _FAKE_PI_LIVE_COMMAND_MARKERS)


def _looks_like_fake_or_test_pi_live_provenance(value: str | None) -> bool:
    if value is None:
        return False
    lowered = value.lower()
    return any(marker in lowered for marker in _FAKE_PI_LIVE_PROVENANCE_MARKERS)


@pytest.mark.parametrize(
    "command",
    [
        "python examples/pi_sidecar.py",
        "python -m examples.pi_sidecar",
        "python samples/pi_sidecar.py",
        "python -m samples.pi_sidecar",
        "python demos/pi_sidecar.py",
        "python -m demos.pi_sidecar",
        "python /opt/example_pi_bridge.py",
        "python /opt/sample-sidecar.py",
        "python /opt/demo_pi_rpc.py",
    ],
)
def test_live_pi_command_marker_rejects_example_sample_demo_sidecars(
    command: str,
) -> None:
    assert _looks_like_fake_or_test_pi_live_command(command) is True


@pytest.mark.parametrize(
    "provenance",
    [
        "example wrapper around github.com/earendil-works/pi",
        "sample bridge around github.com/earendil-works/pi",
        "demo sidecar around github.com/earendil-works/pi",
    ],
)
def test_live_pi_provenance_marker_rejects_example_sample_demo_sidecars(
    provenance: str,
) -> None:
    assert _looks_like_fake_or_test_pi_live_provenance(provenance) is True


def _live_pi_test_fixture_opt_ins_enabled() -> tuple[str, ...]:
    return tuple(
        name
        for name in _PI_LIVE_TEST_FIXTURE_OPT_IN_ENV_VARS
        if os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}
    )


def _live_pi_rpc_command() -> str:
    if os.environ.get("OPENSQUILLA_AGENT_CORE_LIVE_PARITY") != "1":
        pytest.fail(
            "OPENSQUILLA_AGENT_CORE_LIVE_PARITY=1 is required with "
            "OPENSQUILLA_AGENT_CORE_PI_LIVE=1 so Pi parity runs alongside "
            "direct Python and OpenSquilla kernel parity"
        )
    if enabled_opt_ins := _live_pi_test_fixture_opt_ins_enabled():
        pytest.fail(
            "Pi live parity must not enable contract test-fixture opt-ins: "
            + ", ".join(enabled_opt_ins)
        )
    command = os.environ.get("OPENSQUILLA_PI_AGENT_RPC_COMMAND", "").strip()
    if not command:
        pytest.fail("OPENSQUILLA_PI_AGENT_RPC_COMMAND is required for live Pi parity")
    provenance = _live_pi_rpc_command_provenance()
    if _looks_like_fake_or_test_pi_live_command(
        command
    ) or _looks_like_fake_or_test_pi_live_provenance(provenance):
        pytest.fail(
            "OPENSQUILLA_PI_AGENT_RPC_COMMAND must point to a real upstream Pi "
            "runtime, CLI, package wrapper, or equivalent upstream RPC process; "
            "fake/test sidecars are contract-test fixtures only"
        )

    from opensquilla.engine.agent_core import _validate_pi_rpc_command

    try:
        _validate_pi_rpc_command(
            command,
            provenance=provenance,
            allow_test_command=False,
        )
    except ValueError as exc:
        pytest.fail(
            "OPENSQUILLA_PI_AGENT_RPC_COMMAND must point to a real upstream Pi "
            "runtime, CLI, package wrapper, or equivalent upstream RPC process; "
            f"{exc}"
        )
    return command


def _live_provider() -> OpenAIProvider:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        if (
            os.environ.get("OPENSQUILLA_AGENT_CORE_LIVE_PARITY") == "1"
            or os.environ.get("OPENSQUILLA_AGENT_CORE_PI_LIVE") == "1"
        ):
            pytest.fail(
                "OPENROUTER_API_KEY is required when live agent-core parity is enabled"
            )
        pytest.skip("OPENROUTER_API_KEY not set")
    return OpenAIProvider(
        api_key=api_key,
        model=os.environ.get("LLM_TEST_MODEL", "openai/gpt-4o-mini"),
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        provider_kind="openrouter",
    )


def _live_agent_config(
    *,
    max_iterations: int,
    max_tokens: int,
    system_prompt: str = "You must use tools when a tool is available and requested.",
) -> AgentConfig:
    return AgentConfig(
        max_iterations=max_iterations,
        max_tokens=max_tokens,
        request_timeout=60.0,
        temperature=0.0,
        cache_mode="auto",
        system_prompt=system_prompt,
        model_id=os.environ.get("LLM_TEST_MODEL", "openai/gpt-4o-mini"),
        provider_request_proof_max_chars=int(
            os.environ.get("OPENSQUILLA_AGENT_CORE_PROOF_MAX_CHARS", "8000")
        ),
    )


def test_live_agent_config_factory_returns_distinct_equivalent_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_TEST_MODEL", "openai/test-live-parity")

    first = _live_agent_config(max_iterations=2, max_tokens=128)
    second = _live_agent_config(max_iterations=2, max_tokens=128)

    assert first == second
    assert first is not second
    first.request_context_prompt = "mutated baseline context"
    assert second.request_context_prompt is None


def test_stable_live_events_filters_provider_stream_timeout_heartbeat() -> None:
    stable = RunHeartbeatEvent(phase="queue", message="task still running")
    done = DoneEvent(text="ok")

    assert _stable_live_events(
        [
            RunHeartbeatEvent(
                phase="llm_fallback",
                message="OpenRouter stream timed out; retrying without streaming.",
            ),
            stable,
            done,
        ]
    ) == [stable, done]


def _tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="echo_marker",
            description="Return the marker exactly.",
            input_schema=ToolInputSchema(
                properties={
                    "marker": ToolParam(type="string", description="Marker to echo"),
                },
                required=["marker"],
            ),
        )
    ]


async def _tool_handler(call: ToolCall) -> ToolResult:
    marker = str(call.arguments.get("marker") or "")
    return ToolResult(
        tool_use_id=call.tool_use_id,
        tool_name=call.tool_name,
        content=marker,
    )


def _orchestration_tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="sessions_spawn",
            description="Spawn a deterministic child session parity probe.",
            input_schema=ToolInputSchema(
                properties={
                    "prompt": ToolParam(type="string", description="Child prompt"),
                },
                required=["prompt"],
            ),
        ),
        ToolDefinition(
            name="sessions_yield",
            description="Yield the current session after child work is queued.",
            input_schema=ToolInputSchema(
                properties={
                    "reason": ToolParam(type="string", description="Yield reason"),
                },
                required=["reason"],
            ),
        ),
        ToolDefinition(
            name="sessions_send",
            description="Send a deterministic message to a child session parity probe.",
            input_schema=ToolInputSchema(
                properties={
                    "session_key": ToolParam(
                        type="string",
                        description="Target child session key",
                    ),
                    "message": ToolParam(type="string", description="Message to send"),
                },
                required=["session_key", "message"],
            ),
        ),
    ]


async def _orchestration_tool_handler(call: ToolCall) -> ToolResult:
    if call.tool_name == "sessions_spawn":
        content = (
            '{"session_key":"agent:main:live-agent-core-child",'
            '"status":"spawned"}'
        )
    elif call.tool_name == "sessions_yield":
        content = '{"status":"yielded"}'
    elif call.tool_name == "sessions_send":
        content = '{"status":"sent"}'
    else:
        content = f'{{"status":"unexpected","tool_name":"{call.tool_name}"}}'
    return ToolResult(
        tool_use_id=call.tool_use_id,
        tool_name=call.tool_name,
        content=content,
    )


def _session_write_records(recorder: Any | None) -> list[Any]:
    if recorder is None or not hasattr(recorder, "writes"):
        return []
    writes = getattr(recorder, "writes")
    if not isinstance(writes, list):
        raise RuntimeError("session write recorder writes must be a list")
    return writes


def _session_write_count(recorder: Any | None) -> int:
    return len(_session_write_records(recorder))


def _json_live_fingerprint_payload(payload: object, *, label: str) -> str:
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} must be JSON-compatible") from exc


def _session_write_fingerprint(write: dict[str, Any]) -> str:
    session_key = write.get("session_key")
    if not isinstance(session_key, str) or not session_key.strip():
        raise RuntimeError(
            "session write fingerprint session_key must be a non-empty string"
        )
    role = write.get("role")
    if not isinstance(role, str) or not role.strip():
        raise RuntimeError("session write fingerprint role must be a non-empty string")
    if role not in {"assistant", "tool", "user"}:
        raise RuntimeError(
            "session write fingerprint role must be one of assistant, tool, user"
        )
    if "content" in write and not isinstance(write["content"], str):
        raise RuntimeError("session write fingerprint content must be a string")
    if (
        "reasoning_content" in write
        and write["reasoning_content"] is not None
        and not isinstance(write["reasoning_content"], str)
    ):
        raise RuntimeError(
            "session write fingerprint reasoning_content must be a string or null"
        )
    payload = {
        key: value
        for key, value in write.items()
        if key not in {"session_key", "role"}
    }
    normalized_payload = _json_live_fingerprint_payload(
        payload,
        label="session write fingerprint payload",
    )
    return f"{session_key}|{role}|{normalized_payload}"


def _session_write_fingerprints(
    recorder: Any | None,
    *,
    start_index: int = 0,
) -> tuple[str, ...]:
    writes = _session_write_records(recorder)

    fingerprints: list[str] = []
    for write in writes[start_index:]:
        if not isinstance(write, dict):
            raise RuntimeError("session write fingerprint record must be an object")
        fingerprints.append(_session_write_fingerprint(write))
    return tuple(fingerprints)


async def _run_live(
    agent: Any,
    *,
    prompt: str = _PROMPT,
    session_write_count: int = 0,
    session_write_recorder: Any | None = None,
) -> _LiveRunResult:
    writes_before = _session_write_count(session_write_recorder)
    with structlog.testing.capture_logs() as captured:
        events = [event async for event in agent.run_turn(prompt)]
    writes_after = _session_write_count(session_write_recorder)
    return _LiveRunResult(
        events=_stable_live_events(events),
        provider_proofs=_provider_proofs_from_logs(captured),
        session_write_count=session_write_count + max(0, writes_after - writes_before),
        session_write_fingerprints=_session_write_fingerprints(
            session_write_recorder,
            start_index=writes_before,
        ),
    )


def _live_parity_float_env(
    env_name: str,
    default: str,
    *,
    label: str,
    minimum: float | None = None,
) -> float:
    raw_value = os.environ.get(env_name, default)
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{label} must be a finite number") from exc
    if not math.isfinite(value):
        raise RuntimeError(f"{label} must be a finite number")
    if minimum is not None and value < minimum:
        raise RuntimeError(f"{label} must be at least {minimum}")
    return value


def _live_parity_non_negative_int_env(
    env_name: str,
    default: str,
    *,
    label: str,
) -> int:
    raw_value = os.environ.get(env_name, default)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{label} must be a non-negative integer") from exc
    if value < 0:
        raise RuntimeError(f"{label} must be a non-negative integer")
    return value


def _provider_proof_char_ratio_limit() -> float:
    return _live_parity_float_env(
        "OPENSQUILLA_AGENT_CORE_PROOF_CHAR_RATIO",
        "1.35",
        label="provider proof char ratio",
        minimum=1.0,
    )


def _provider_proof_char_slack_limit() -> int:
    return _live_parity_non_negative_int_env(
        "OPENSQUILLA_AGENT_CORE_PROOF_CHAR_SLACK",
        "2048",
        label="provider proof char slack",
    )



def _compare_provider_proofs(
    *,
    baseline: tuple[dict[str, Any], ...],
    candidate: tuple[dict[str, Any], ...],
    candidate_name: str,
) -> list[str]:
    if not baseline:
        return []

    violations: list[str] = []
    if len(candidate) < len(baseline):
        violations.append(
            f"{candidate_name} provider proof count regressed: "
            f"{len(candidate)} < {len(baseline)}"
        )
        return violations
    if len(candidate) > len(baseline):
        violations.append(
            f"{candidate_name} provider proof count regressed: "
            f"{len(candidate)} > {len(baseline)}"
        )

    max_char_ratio = _provider_proof_char_ratio_limit()
    char_slack = _provider_proof_char_slack_limit()

    def _proof_int(
        proof: dict[str, Any],
        *,
        key: str,
        proof_label: str,
        index: int,
    ) -> int | None:
        if key not in proof:
            return 0
        value = proof[key]
        if not isinstance(value, int) or isinstance(value, bool):
            violations.append(
                f"{proof_label} provider proof {index} {key} malformed: "
                f"{value!r}"
            )
            return None
        if value < 0:
            violations.append(
                f"{proof_label} provider proof {index} {key} malformed: "
                f"{value!r}"
            )
            return None
        return value

    def _validate_fits(
        proof: dict[str, Any],
        *,
        proof_label: str,
        index: int,
    ) -> None:
        if "fits" in proof and not isinstance(proof["fits"], bool):
            violations.append(
                f"{proof_label} provider proof {index} fits malformed: "
                f"{proof['fits']!r}"
            )

    def _validate_bool_metadata(
        proof: dict[str, Any],
        *,
        key: str,
        proof_label: str,
        index: int,
    ) -> None:
        if key in proof and not isinstance(proof[key], bool):
            violations.append(
                f"{proof_label} provider proof {index} {key} malformed: "
                f"{proof[key]!r}"
            )

    def _validate_string_metadata(
        proof: dict[str, Any],
        *,
        key: str,
        proof_label: str,
        index: int,
    ) -> None:
        if key in proof and not isinstance(proof[key], str):
            violations.append(
                f"{proof_label} provider proof {index} {key} malformed: "
                f"{proof[key]!r}"
            )

    for index, baseline_proof in enumerate(baseline):
        candidate_proof = candidate[index]
        _validate_fits(baseline_proof, proof_label="baseline", index=index)
        _validate_fits(candidate_proof, proof_label=candidate_name, index=index)
        for key in _PROVIDER_PROOF_INTEGER_METADATA_KEYS:
            _proof_int(
                baseline_proof,
                key=key,
                proof_label="baseline",
                index=index,
            )
            _proof_int(
                candidate_proof,
                key=key,
                proof_label=candidate_name,
                index=index,
            )
        for key in _PROVIDER_PROOF_BOOLEAN_METADATA_KEYS:
            _validate_bool_metadata(
                baseline_proof,
                key=key,
                proof_label="baseline",
                index=index,
            )
            _validate_bool_metadata(
                candidate_proof,
                key=key,
                proof_label=candidate_name,
                index=index,
            )
        for key in _PROVIDER_PROOF_STRING_METADATA_KEYS:
            _validate_string_metadata(
                baseline_proof,
                key=key,
                proof_label="baseline",
                index=index,
            )
            _validate_string_metadata(
                candidate_proof,
                key=key,
                proof_label=candidate_name,
                index=index,
            )
        if baseline_proof.get("fits") is True and candidate_proof.get("fits") is not True:
            violations.append(f"{candidate_name} provider proof {index} no longer fits")
        if (
            baseline_proof.get("retry_count") is not None
                and candidate_proof.get("retry_count") is None
        ):
            violations.append(f"{candidate_name} provider proof {index} lost retry metadata")
        baseline_retry_count = _proof_int(
            baseline_proof,
            key="retry_count",
            proof_label="baseline",
            index=index,
        )
        candidate_retry_count = _proof_int(
            candidate_proof,
            key="retry_count",
            proof_label=candidate_name,
            index=index,
        )
        if (
            baseline_proof.get("retry_count") is not None
            and baseline_retry_count is not None
            and candidate_retry_count is not None
            and candidate_retry_count > baseline_retry_count
        ):
            violations.append(
                f"{candidate_name} provider proof {index} retry count regressed: "
                f"{candidate_retry_count} > {baseline_retry_count}"
            )
        for key in _PROVIDER_PROOF_IDENTITY_KEYS:
            if key in baseline_proof and candidate_proof.get(key) != baseline_proof[key]:
                violations.append(
                    f"{candidate_name} provider proof {index} metadata regressed: "
                    f"{key}={candidate_proof.get(key)!r} != {baseline_proof[key]!r}"
                )

        baseline_chars = _proof_int(
            baseline_proof,
            key="estimated_chars",
            proof_label="baseline",
            index=index,
        )
        candidate_chars = _proof_int(
            candidate_proof,
            key="estimated_chars",
            proof_label=candidate_name,
            index=index,
        )
        if baseline_chars is None or candidate_chars is None:
            continue
        if "estimated_chars" in baseline_proof and "estimated_chars" not in candidate_proof:
            violations.append(
                f"{candidate_name} provider proof {index} lost estimated_chars"
            )
            continue
        if baseline_chars > 0 and candidate_chars <= 0:
            violations.append(
                f"{candidate_name} provider proof {index} lost estimated_chars"
            )
        allowed_chars = int(baseline_chars * max_char_ratio) + char_slack
        if candidate_chars > allowed_chars:
            violations.append(
                f"{candidate_name} provider proof {index} chars regressed: "
                f"{candidate_chars} > allowed {allowed_chars} "
                f"(baseline {baseline_chars})"
            )

    return violations


def _compare_session_writes(
    *,
    baseline_write_count: int,
    candidate_write_count: int,
    candidate_name: str,
    baseline_write_fingerprints: tuple[str, ...] = (),
    candidate_write_fingerprints: tuple[str, ...] = (),
) -> list[str]:
    violations: list[str] = []
    if candidate_write_count != baseline_write_count:
        operator = "<" if candidate_write_count < baseline_write_count else ">"
        violations.append(
            f"{candidate_name} session write count regressed: "
            f"{candidate_write_count} {operator} {baseline_write_count}"
        )
    if (
        candidate_write_count == baseline_write_count
        and baseline_write_count > 0
        and not baseline_write_fingerprints
    ):
        violations.append(
            "baseline session write fingerprints missing; live parity cannot "
            "validate session write content"
        )
    if (
        baseline_write_fingerprints
        and candidate_write_fingerprints != baseline_write_fingerprints
    ):
        violations.append(
            f"{candidate_name} session write content regressed: "
            f"{candidate_write_fingerprints!r} != {baseline_write_fingerprints!r}"
        )
    return violations


def test_provider_proof_comparison_flags_missing_or_larger_candidate() -> None:
    baseline = (
        {
            "fits": True,
            "estimated_chars": 1000,
            "retry_count": 1,
        },
    )

    assert _compare_provider_proofs(
        baseline=baseline,
        candidate=(),
        candidate_name="pi",
    ) == ["pi provider proof count regressed: 0 < 1"]

    violations = _compare_provider_proofs(
        baseline=baseline,
        candidate=(
            {
                "fits": False,
                "estimated_chars": 5000,
            },
        ),
        candidate_name="pi",
    )

    assert any("no longer fits" in violation for violation in violations)
    assert any("lost retry metadata" in violation for violation in violations)
    assert any("chars regressed" in violation for violation in violations)


def test_provider_proof_comparison_flags_extra_provider_requests() -> None:
    baseline = (
        {
            "fits": True,
            "estimated_chars": 1000,
            "retry_count": 0,
        },
    )

    violations = _compare_provider_proofs(
        baseline=baseline,
        candidate=(
            {
                "fits": True,
                "estimated_chars": 1000,
                "retry_count": 0,
            },
            {
                "fits": True,
                "estimated_chars": 1000,
                "retry_count": 0,
            },
        ),
        candidate_name="pi",
    )

    assert violations == ["pi provider proof count regressed: 2 > 1"]


def test_provider_proof_comparison_flags_zero_baseline_char_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_PROOF_CHAR_RATIO", "1.0")
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_PROOF_CHAR_SLACK", "0")

    violations = _compare_provider_proofs(
        baseline=({"fits": True, "estimated_chars": 0},),
        candidate=({"fits": True, "estimated_chars": 1},),
        candidate_name="pi",
    )

    assert violations == [
        "pi provider proof 0 chars regressed: 1 > allowed 0 (baseline 0)"
    ]


def test_provider_proof_comparison_flags_missing_zero_baseline_estimated_chars() -> (
    None
):
    violations = _compare_provider_proofs(
        baseline=({"fits": True, "estimated_chars": 0},),
        candidate=({"fits": True},),
        candidate_name="pi",
    )

    assert violations == ["pi provider proof 0 lost estimated_chars"]


@pytest.mark.parametrize(
    ("env_name", "env_value", "error_match"),
    [
        (
            "OPENSQUILLA_AGENT_CORE_PROOF_CHAR_RATIO",
            "nan",
            "provider proof char ratio",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_PROOF_CHAR_RATIO",
            "0.99",
            "provider proof char ratio",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_PROOF_CHAR_SLACK",
            "-1",
            "provider proof char slack",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_PROOF_CHAR_SLACK",
            "1.5",
            "provider proof char slack",
        ),
    ],
)
def test_provider_proof_comparison_rejects_malformed_char_thresholds(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    env_value: str,
    error_match: str,
) -> None:
    monkeypatch.setenv(env_name, env_value)

    with pytest.raises(RuntimeError, match=error_match):
        _compare_provider_proofs(
            baseline=({"fits": True, "estimated_chars": 1000},),
            candidate=({"fits": True, "estimated_chars": 1000},),
            candidate_name="pi",
        )


@pytest.mark.parametrize(
    ("env_name", "env_value", "error_match"),
    [
        (
            "OPENSQUILLA_AGENT_CORE_TOKEN_RATIO",
            "nan",
            "live parity token ratio",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_TOKEN_RATIO",
            "0.99",
            "live parity token ratio",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_TOKEN_SLACK",
            "-1",
            "live parity token slack",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_TOKEN_SLACK",
            "1.5",
            "live parity token slack",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_CACHE_RATE_DELTA",
            "nan",
            "live parity cache rate delta",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_TOOL_SUCCESS_RATE_DELTA",
            "nan",
            "live parity tool success rate delta",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_TOOL_SUCCESS_RATE_DELTA",
            "-0.01",
            "live parity tool success rate delta",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_COST_RATIO",
            "nan",
            "live parity cost ratio",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_COST_RATIO",
            "0.99",
            "live parity cost ratio",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_COST_SLACK_USD",
            "nan",
            "live parity cost slack",
        ),
        (
            "OPENSQUILLA_AGENT_CORE_COST_SLACK_USD",
            "-0.01",
            "live parity cost slack",
        ),
    ],
)
def test_assert_not_weaker_rejects_malformed_live_threshold_env(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    env_value: str,
    error_match: str,
) -> None:
    monkeypatch.setenv(env_name, env_value)
    baseline = _LiveRunResult(
        events=[DoneEvent(text="ok", input_tokens=1, output_tokens=1)],
        provider_proofs=({"fits": True, "estimated_chars": 1000},),
    )
    candidate = _LiveRunResult(
        events=[DoneEvent(text="ok", input_tokens=1, output_tokens=1)],
        provider_proofs=({"fits": True, "estimated_chars": 1000},),
    )

    with pytest.raises(RuntimeError, match=error_match):
        _assert_not_weaker(
            baseline=baseline,
            candidate=candidate,
            candidate_name="pi",
        )


def test_live_parity_assertion_requires_baseline_provider_proof() -> None:
    result = _LiveRunResult(
        events=[DoneEvent(text="ok", input_tokens=1, output_tokens=1)],
        provider_proofs=(),
    )

    with pytest.raises(AssertionError, match="baseline provider proof missing"):
        _assert_not_weaker(
            baseline=result,
            candidate=result,
            candidate_name="pi",
        )


def test_provider_proof_comparison_flags_extra_retry_count() -> None:
    violations = _compare_provider_proofs(
        baseline=(
            {
                "fits": True,
                "estimated_chars": 1000,
                "retry_count": 0,
            },
        ),
        candidate=(
            {
                "fits": True,
                "estimated_chars": 1000,
                "retry_count": 2,
            },
        ),
        candidate_name="pi",
    )

    assert violations == [
        "pi provider proof 0 retry count regressed: 2 > 0"
    ]


def test_provider_proof_comparison_rejects_null_numeric_fields() -> None:
    violations = _compare_provider_proofs(
        baseline=(
            {
                "fits": True,
                "estimated_chars": None,
                "retry_count": None,
                "proof_budget": None,
            },
        ),
        candidate=(
            {
                "fits": True,
                "estimated_chars": None,
                "retry_count": None,
                "proof_budget": None,
            },
        ),
        candidate_name="pi",
    )

    assert "baseline provider proof 0 estimated_chars malformed: None" in violations
    assert "pi provider proof 0 estimated_chars malformed: None" in violations
    assert "baseline provider proof 0 retry_count malformed: None" in violations
    assert "pi provider proof 0 retry_count malformed: None" in violations
    assert "baseline provider proof 0 proof_budget malformed: None" in violations
    assert "pi provider proof 0 proof_budget malformed: None" in violations


def test_provider_proof_comparison_flags_malformed_numeric_candidate_fields() -> None:
    violations = _compare_provider_proofs(
        baseline=(
            {
                "fits": True,
                "estimated_chars": 1000,
                "retry_count": 0,
            },
        ),
        candidate=(
            {
                "fits": True,
                "estimated_chars": "many",
                "retry_count": "again",
            },
        ),
        candidate_name="pi",
    )

    assert any("provider proof 0 retry_count malformed" in violation for violation in violations)
    assert any(
        "provider proof 0 estimated_chars malformed" in violation
        for violation in violations
    )


def test_provider_proof_comparison_rejects_non_integer_numeric_fields() -> None:
    violations = _compare_provider_proofs(
        baseline=(
            {
                "fits": True,
                "estimated_chars": 1000,
                "retry_count": 0,
            },
        ),
        candidate=(
            {
                "fits": True,
                "estimated_chars": 1000.5,
                "retry_count": True,
            },
        ),
        candidate_name="pi",
    )

    assert any(
        "provider proof 0 retry_count malformed" in violation
        for violation in violations
    )
    assert any(
        "provider proof 0 estimated_chars malformed" in violation
        for violation in violations
    )


def test_provider_proof_comparison_rejects_malformed_budget_metadata() -> None:
    violations = _compare_provider_proofs(
        baseline=(
            {
                "fits": True,
                "estimated_chars": 1000,
                "retry_count": 0,
                "proof_budget": "8000",
                "raw_proof_budget": True,
                "effective_proof_budget": 7200.5,
                "proof_headroom_chars": -1,
            },
        ),
        candidate=(
            {
                "fits": True,
                "estimated_chars": 1000,
                "retry_count": 0,
                "proof_budget": "8000",
                "raw_proof_budget": True,
                "effective_proof_budget": 7200.5,
                "proof_headroom_chars": -1,
            },
        ),
        candidate_name="pi",
    )

    for key in (
        "proof_budget",
        "raw_proof_budget",
        "effective_proof_budget",
        "proof_headroom_chars",
    ):
        assert any(
            f"baseline provider proof 0 {key} malformed" in violation
            for violation in violations
        )
        assert any(
            f"pi provider proof 0 {key} malformed" in violation
            for violation in violations
        )


def test_provider_proof_comparison_rejects_malformed_fit_status() -> None:
    violations = _compare_provider_proofs(
        baseline=(
            {
                "fits": "true",
                "estimated_chars": 1000,
                "retry_count": 0,
            },
        ),
        candidate=(
            {
                "fits": "true",
                "estimated_chars": 1000,
                "retry_count": 0,
            },
        ),
        candidate_name="pi",
    )

    assert any("baseline provider proof 0 fits malformed" in violation for violation in violations)
    assert any("pi provider proof 0 fits malformed" in violation for violation in violations)


def test_provider_proof_comparison_rejects_malformed_boolean_metadata() -> None:
    violations = _compare_provider_proofs(
        baseline=(
            {
                "fits": True,
                "estimated_chars": 1000,
                "compact_needed": "false",
            },
        ),
        candidate=(
            {
                "fits": True,
                "estimated_chars": 1000,
                "tool_argument_projection_scrubbed": 0,
            },
        ),
        candidate_name="pi",
    )

    assert any(
        "baseline provider proof 0 compact_needed malformed" in violation
        for violation in violations
    )
    assert any(
        "pi provider proof 0 tool_argument_projection_scrubbed malformed" in violation
        for violation in violations
    )


def test_provider_proof_comparison_rejects_malformed_string_metadata() -> None:
    violations = _compare_provider_proofs(
        baseline=(
            {
                "fits": True,
                "estimated_chars": 1000,
                "fallback_reason": ["compact"],
            },
        ),
        candidate=(
            {
                "fits": True,
                "estimated_chars": 1000,
                "fallback_reason": {"reason": "compact"},
            },
        ),
        candidate_name="pi",
    )

    assert any(
        "baseline provider proof 0 fallback_reason malformed" in violation
        for violation in violations
    )
    assert any(
        "pi provider proof 0 fallback_reason malformed" in violation
        for violation in violations
    )


def test_provider_proof_comparison_flags_stable_metadata_regressions() -> None:
    baseline = (
        {
            "fits": True,
            "estimated_chars": 1000,
            "proof_budget": 8000,
            "effective_proof_budget": 7200,
            "compact_needed": False,
        },
    )
    candidate = (
        {
            "fits": True,
            "estimated_chars": 1000,
            "proof_budget": 0,
            "effective_proof_budget": 0,
            "compact_needed": True,
        },
    )

    violations = _compare_provider_proofs(
        baseline=baseline,
        candidate=candidate,
        candidate_name="pi",
    )

    assert any("provider proof 0 metadata regressed" in violation for violation in violations)


def test_session_write_comparison_flags_missing_candidate_writes() -> None:
    assert _compare_session_writes(
        baseline_write_count=2,
        candidate_write_count=0,
        candidate_name="pi",
    ) == ["pi session write count regressed: 0 < 2"]


def test_session_write_comparison_flags_extra_candidate_writes() -> None:
    assert _compare_session_writes(
        baseline_write_count=0,
        candidate_write_count=1,
        candidate_name="pi",
    ) == ["pi session write count regressed: 1 > 0"]


def test_session_write_comparison_flags_content_regressions() -> None:
    violations = _compare_session_writes(
        baseline_write_count=1,
        candidate_write_count=1,
        candidate_name="pi",
        baseline_write_fingerprints=(
            'agent:main:test|assistant|{"content":"baseline"}',
        ),
        candidate_write_fingerprints=(
            'agent:main:test|assistant|{"content":"candidate"}',
        ),
    )

    assert any("session write content regressed" in violation for violation in violations)


def test_session_write_comparison_requires_baseline_content_fingerprints() -> None:
    violations = _compare_session_writes(
        baseline_write_count=1,
        candidate_write_count=1,
        candidate_name="pi",
        candidate_write_fingerprints=(
            'agent:main:test|assistant|{"content":"candidate"}',
        ),
    )

    assert any(
        "baseline session write fingerprints missing" in violation
        for violation in violations
    )


def test_session_write_fingerprint_rejects_python_only_payloads() -> None:
    class PythonOnlyValue:
        pass

    with pytest.raises(RuntimeError, match="session write fingerprint.*JSON-compatible"):
        _session_write_fingerprint(
            {
                "session_key": "agent:main:test",
                "role": "assistant",
                "content": "ok",
                "metadata": PythonOnlyValue(),
            }
        )


def test_session_write_fingerprint_rejects_non_string_identity_fields() -> None:
    with pytest.raises(RuntimeError, match="session write fingerprint session_key"):
        _session_write_fingerprint(
            {
                "session_key": {"not": "a string"},
                "role": "assistant",
                "content": "ok",
            }
        )

    with pytest.raises(RuntimeError, match="session write fingerprint role"):
        _session_write_fingerprint(
            {
                "session_key": "agent:main:test",
                "role": ["assistant"],
                "content": "ok",
            }
        )


def test_session_write_fingerprint_rejects_unsupported_roles() -> None:
    with pytest.raises(RuntimeError, match="session write fingerprint role"):
        _session_write_fingerprint(
            {"session_key": "agent:main:test", "role": "system", "content": "ok"}
        )


def test_session_write_fingerprint_rejects_malformed_transcript_content() -> None:
    with pytest.raises(RuntimeError, match="session write fingerprint content"):
        _session_write_fingerprint(
            {"session_key": "agent:main:test", "role": "assistant", "content": 123}
        )

    with pytest.raises(RuntimeError, match="session write fingerprint reasoning_content"):
        _session_write_fingerprint(
            {
                "session_key": "agent:main:test",
                "role": "assistant",
                "content": "ok",
                "reasoning_content": 123,
            }
        )


def test_session_write_fingerprint_rejects_missing_or_blank_identity_fields() -> None:
    with pytest.raises(RuntimeError, match="session write fingerprint session_key"):
        _session_write_fingerprint({"role": "assistant", "content": "ok"})

    with pytest.raises(RuntimeError, match="session write fingerprint session_key"):
        _session_write_fingerprint(
            {"session_key": "   ", "role": "assistant", "content": "ok"}
        )

    with pytest.raises(RuntimeError, match="session write fingerprint role"):
        _session_write_fingerprint({"session_key": "agent:main:test", "content": "ok"})

    with pytest.raises(RuntimeError, match="session write fingerprint role"):
        _session_write_fingerprint(
            {"session_key": "agent:main:test", "role": "", "content": "ok"}
        )


def test_session_write_fingerprints_rejects_non_object_records() -> None:
    recorder = SimpleNamespace(
        writes=[
            {"session_key": "agent:main:test", "role": "assistant", "content": "ok"},
            object(),
        ]
    )

    with pytest.raises(
        RuntimeError,
        match="session write fingerprint record must be an object",
    ):
        _session_write_fingerprints(recorder)


def test_session_write_recorder_rejects_malformed_writes_container() -> None:
    recorder = SimpleNamespace(writes=(
        {"session_key": "agent:main:test", "role": "assistant", "content": "ok"},
    ))

    with pytest.raises(RuntimeError, match="session write recorder writes must be a list"):
        _session_write_count(recorder)

    with pytest.raises(RuntimeError, match="session write recorder writes must be a list"):
        _session_write_fingerprints(recorder)


@pytest.mark.asyncio
async def test_run_live_counts_session_writes_from_recorder() -> None:
    recorder = _SessionWriteRecorder()

    class FakeAgent:
        async def run_turn(self, prompt: str):
            await recorder.append_message(
                "agent:main:test",
                role="assistant",
                content=prompt,
            )
            yield DoneEvent(text="ok")

    result = await _run_live(
        FakeAgent(),
        prompt="write-session",
        session_write_recorder=recorder,
    )

    assert result.session_write_count == 1
    assert result.session_write_fingerprints == (
        'agent:main:test|assistant|{"content":"write-session"}',
    )


@pytest.mark.asyncio
async def test_pi_live_harness_records_sidecar_session_write_intents() -> None:
    from opensquilla.engine.agent_core import AGENT_CORE_PROTOCOL_VERSION

    class FakePiRpcClient:
        async def stream_prompt(self, message: str, **kwargs: Any):
            yield {
                "protocol": AGENT_CORE_PROTOCOL_VERSION,
                "kind": "intent",
                "type": "session.write.enqueue",
                "payload": {
                    "session_key": "agent:main:live-agent-core-pi",
                    "role": "assistant",
                    "content": "host-owned session write",
                },
            }

    recorder = _SessionWriteRecorder()
    agent = build_agent_for_kernel(
        runtime_config=SimpleNamespace(
            agent_kernel="pi",
            pi_agent_rpc_client=FakePiRpcClient(),
            allow_test_pi_rpc_client=True,
        ),
        provider=object(),
        config=AgentConfig(model_id="pi-session-write-recorder"),
        tool_definitions=[],
        tool_handler=None,
        usage_tracker=None,
        session_key="agent:main:live-agent-core-pi",
        turn_call_logger=None,
        memory_sync_manager=None,
        session_flush_service=None,
        tool_registry=None,
        tool_context=None,
        session_manager=recorder,
    )

    result = await _run_live(agent, session_write_recorder=recorder)

    assert result.session_write_count == 1
    assert recorder.writes == [
        {
            "session_key": "agent:main:live-agent-core-pi",
            "role": "assistant",
            "content": "host-owned session write",
            "tool_calls": None,
            "reasoning_content": None,
            "turn_usage": None,
            "token_count": None,
        }
    ]


def test_live_pi_command_requires_full_live_parity_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_PI_LIVE", "1")
    monkeypatch.delenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", raising=False)
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND",
        "python /opt/custom_pi_bridge.py",
    )
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE",
        "thin opensquilla.agent_core.v1 wrapper around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
    )

    with pytest.raises(pytest.fail.Exception, match="OPENSQUILLA_AGENT_CORE_LIVE_PARITY"):
        _live_pi_rpc_command()


def test_live_pi_command_requires_real_command_when_pi_gate_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_PI_LIVE", "1")
    monkeypatch.delenv("OPENSQUILLA_PI_AGENT_RPC_COMMAND", raising=False)
    monkeypatch.delenv("OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE", raising=False)

    with pytest.raises(pytest.fail.Exception, match="OPENSQUILLA_PI_AGENT_RPC_COMMAND"):
        _live_pi_rpc_command()


@pytest.mark.parametrize(
    "command",
    [
        "python /tmp/fake-pi-rpc.py",
        "python /tmp/fake_pi_rpc.py",
        "python /tmp/fake_sidecar.py",
        "python /tmp/fake-sidecar.py",
        "python /tmp/mock_pi_rpc.py",
        "python /tmp/pi_fixture_sidecar.py",
        "python /tmp/test_fixture_pi_rpc.py",
    ],
)
def test_live_pi_command_rejects_fake_or_test_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND",
        command,
    )
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE",
        "thin opensquilla.agent_core.v1 wrapper around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
    )

    with pytest.raises(pytest.fail.Exception, match="real upstream Pi runtime"):
        _live_pi_rpc_command()


@pytest.mark.parametrize(
    "command",
    [
        "python tests/fixtures/pi_sidecar.py",
        "python -m tests.fixtures.pi_sidecar",
    ],
)
def test_live_pi_command_rejects_tests_directory_python_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND",
        command,
    )
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE",
        "thin opensquilla.agent_core.v1 wrapper around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
    )

    with pytest.raises(pytest.fail.Exception, match="real upstream Pi runtime"):
        _live_pi_rpc_command()


def test_live_pi_command_rejects_unprovenanced_custom_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND",
        "python /opt/custom_pi_bridge.py",
    )
    monkeypatch.delenv("OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE", raising=False)

    with pytest.raises(pytest.fail.Exception, match="upstream Pi runtime provenance"):
        _live_pi_rpc_command()


@pytest.mark.parametrize(
    "provenance",
    [
        "thin opensquilla.agent_core.v1 fake test fixture around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
        "thin opensquilla.agent_core.v1 fixture wrapper around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
        "thin opensquilla.agent_core.v1 dummy wrapper around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
        "thin opensquilla.agent_core.v1 stub wrapper around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
    ],
)
def test_live_pi_command_rejects_fake_or_test_provenance(
    monkeypatch: pytest.MonkeyPatch,
    provenance: str,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND",
        "python /opt/opensquilla_pi_bridge.py",
    )
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE",
        provenance,
    )

    with pytest.raises(pytest.fail.Exception, match="real upstream Pi runtime"):
        _live_pi_rpc_command()


@pytest.mark.parametrize(
    "env_name",
    [
        "OPENSQUILLA_AGENT_CORE_ALLOW_TEST_PI_RPC_COMMAND",
        "OPENSQUILLA_AGENT_CORE_ALLOW_TEST_PI_RPC_CLIENT",
        "OPENSQUILLA_ALLOW_TEST_PI_RPC_COMMAND",
        "OPENSQUILLA_ALLOW_TEST_PI_RPC_CLIENT",
    ],
)
def test_live_pi_command_rejects_contract_test_fixture_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    monkeypatch.setenv(env_name, "1")
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND",
        "python /opt/opensquilla_pi_bridge.py",
    )
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE",
        "thin opensquilla.agent_core.v1 wrapper around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
    )

    with pytest.raises(pytest.fail.Exception, match="test-fixture opt-ins"):
        _live_pi_rpc_command()


def test_live_pi_command_accepts_provenanced_custom_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    command = "python /opt/custom_pi_bridge.py"
    monkeypatch.setenv("OPENSQUILLA_PI_AGENT_RPC_COMMAND", command)
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE",
        "thin opensquilla.agent_core.v1 wrapper around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
    )

    assert _live_pi_rpc_command() == command


def test_live_pi_command_rejects_bridge_package_name_as_upstream_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND",
        "python /opt/custom_pi_bridge.py",
    )
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE",
        "thin opensquilla.agent_core.v1 sidecar package "
        "@opensquilla/pi-agent-core-bridge",
    )

    with pytest.raises(pytest.fail.Exception, match="upstream Pi runtime provenance"):
        _live_pi_rpc_command()


def test_live_pi_command_rejects_wrapper_runtime_upstream_source_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND",
        "npx @opensquilla/pi-agent-core-bridge "
        "--runtime /opt/pi/packages/agent/src/index.ts",
    )
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE",
        "thin opensquilla.agent_core.v1 wrapper around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
    )

    with pytest.raises(pytest.fail.Exception, match="real upstream Pi runtime"):
        _live_pi_rpc_command()


def test_live_pi_command_rejects_env_command_native_pi_rpc_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND",
        "env PI_AGENT_RPC_COMMAND='pi --mode rpc' "
        "npx @opensquilla/pi-agent-core-bridge",
    )
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE",
        "thin opensquilla.agent_core.v1 wrapper around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
    )

    with pytest.raises(pytest.fail.Exception, match="real upstream Pi runtime"):
        _live_pi_rpc_command()


def test_live_pi_command_rejects_env_runtime_mode_native_pi_rpc_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND",
        "env PI_AGENT_RUNTIME=@earendil-works/pi-coding-agent "
        "PI_AGENT_MODE=rpc npx @opensquilla/pi-agent-core-bridge",
    )
    monkeypatch.setenv(
        "OPENSQUILLA_PI_AGENT_RPC_COMMAND_PROVENANCE",
        "thin opensquilla.agent_core.v1 wrapper around "
        "github.com/earendil-works/pi @earendil-works/pi-agent-core",
    )

    with pytest.raises(pytest.fail.Exception, match="real upstream Pi runtime"):
        _live_pi_rpc_command()


def test_live_provider_requires_api_key_when_live_parity_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_CORE_LIVE_PARITY", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(pytest.fail.Exception, match="OPENROUTER_API_KEY"):
        try:
            _live_provider()
        except pytest.skip.Exception as exc:
            raise AssertionError(
                "explicit live parity opt-in must fail without OPENROUTER_API_KEY, "
                "not skip"
            ) from exc


def _assert_not_weaker(
    *,
    baseline: _LiveRunResult,
    candidate: _LiveRunResult,
    candidate_name: str,
) -> None:
    violations = compare_agent_core_metrics(
        baseline=collect_agent_core_run_metrics(baseline.events),
        candidate=collect_agent_core_run_metrics(candidate.events),
        candidate_name=candidate_name,
        thresholds=AgentCoreParityThresholds(
            max_total_token_ratio=_live_parity_float_env(
                "OPENSQUILLA_AGENT_CORE_TOKEN_RATIO",
                "1.25",
                label="live parity token ratio",
                minimum=1.0,
            ),
            total_token_slack=_live_parity_non_negative_int_env(
                "OPENSQUILLA_AGENT_CORE_TOKEN_SLACK",
                "64",
                label="live parity token slack",
            ),
            min_kv_cache_hit_rate_delta=_live_parity_float_env(
                "OPENSQUILLA_AGENT_CORE_CACHE_RATE_DELTA",
                "-0.10",
                label="live parity cache rate delta",
            ),
            min_tool_success_rate_delta=_live_parity_float_env(
                "OPENSQUILLA_AGENT_CORE_TOOL_SUCCESS_RATE_DELTA",
                "0.0",
                label="live parity tool success rate delta",
                minimum=0.0,
            ),
            max_cost_ratio=_live_parity_float_env(
                "OPENSQUILLA_AGENT_CORE_COST_RATIO",
                "1.10",
                label="live parity cost ratio",
                minimum=1.0,
            ),
            cost_slack_usd=_live_parity_float_env(
                "OPENSQUILLA_AGENT_CORE_COST_SLACK_USD",
                "0.001",
                label="live parity cost slack",
                minimum=0.0,
            ),
        ),
    )
    if not baseline.provider_proofs:
        violations.append(
            "baseline provider proof missing; live parity cannot validate "
            "provider request proof"
        )
    violations.extend(
        _compare_provider_proofs(
            baseline=baseline.provider_proofs,
            candidate=candidate.provider_proofs,
            candidate_name=candidate_name,
        )
    )
    violations.extend(
        _compare_session_writes(
            baseline_write_count=baseline.session_write_count,
            candidate_write_count=candidate.session_write_count,
            baseline_write_fingerprints=baseline.session_write_fingerprints,
            candidate_write_fingerprints=candidate.session_write_fingerprints,
            candidate_name=candidate_name,
        )
    )
    assert violations == []


def _assert_orchestration_gate_exercised(result: _LiveRunResult) -> None:
    metrics = collect_agent_core_run_metrics(result.events)
    assert metrics.yield_result_count >= 1
    assert any(
        fingerprint.startswith("sessions_spawn|")
        for fingerprint in metrics.orchestration_result_fingerprints
    )
    assert any(
        fingerprint.startswith("sessions_yield|")
        for fingerprint in metrics.orchestration_result_fingerprints
    )
    assert any(
        fingerprint.startswith("sessions_send|")
        for fingerprint in metrics.orchestration_result_fingerprints
    )


@pytest.mark.llm
@pytest.mark.llm_gateway
@pytest.mark.llm_tools
@pytest.mark.asyncio
async def test_live_opensquilla_kernel_not_weaker_than_direct_python_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("OPENSQUILLA_AGENT_CORE_LIVE_PARITY") != "1":
        pytest.skip("set OPENSQUILLA_AGENT_CORE_LIVE_PARITY=1 to run live agent-core parity")
    _freeze_live_runtime_context(monkeypatch)

    baseline_config = _live_agent_config(max_iterations=2, max_tokens=128)
    candidate_config = _live_agent_config(max_iterations=2, max_tokens=128)
    tool_definitions = _tool_definitions()
    session_key = "agent:main:live-agent-core-opensquilla"
    baseline = Agent(
        provider=_live_provider(),
        config=baseline_config,
        tool_definitions=tool_definitions,
        tool_handler=_tool_handler,
        session_key=session_key,
    )
    candidate = build_agent_for_kernel(
        runtime_config=SimpleNamespace(agent_kernel="opensquilla"),
        provider=_live_provider(),
        config=candidate_config,
        tool_definitions=tool_definitions,
        tool_handler=_tool_handler,
        usage_tracker=None,
        session_key=session_key,
        turn_call_logger=None,
        memory_sync_manager=None,
        session_flush_service=None,
        tool_registry=None,
        tool_context=None,
    )

    _assert_not_weaker(
        baseline=await _run_live(baseline),
        candidate=await _run_live(candidate),
        candidate_name="opensquilla",
    )


@pytest.mark.llm
@pytest.mark.llm_gateway
@pytest.mark.llm_tools
@pytest.mark.asyncio
async def test_live_opensquilla_kernel_preserves_orchestration_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("OPENSQUILLA_AGENT_CORE_LIVE_PARITY") != "1":
        pytest.skip("set OPENSQUILLA_AGENT_CORE_LIVE_PARITY=1 to run live agent-core parity")
    _freeze_live_runtime_context(monkeypatch)

    system_prompt = (
        "When asked to call tools, call every requested tool before final answer."
    )
    baseline_config = _live_agent_config(
        max_iterations=4,
        max_tokens=256,
        system_prompt=system_prompt,
    )
    candidate_config = _live_agent_config(
        max_iterations=4,
        max_tokens=256,
        system_prompt=system_prompt,
    )
    tool_definitions = _orchestration_tool_definitions()
    session_key = "agent:main:live-agent-core-orchestration"
    baseline = Agent(
        provider=_live_provider(),
        config=baseline_config,
        tool_definitions=tool_definitions,
        tool_handler=_orchestration_tool_handler,
        session_key=session_key,
    )
    candidate = build_agent_for_kernel(
        runtime_config=SimpleNamespace(agent_kernel="opensquilla"),
        provider=_live_provider(),
        config=candidate_config,
        tool_definitions=tool_definitions,
        tool_handler=_orchestration_tool_handler,
        usage_tracker=None,
        session_key=session_key,
        turn_call_logger=None,
        memory_sync_manager=None,
        session_flush_service=None,
        tool_registry=None,
        tool_context=None,
    )

    baseline_result = await _run_live(baseline, prompt=_ORCHESTRATION_PROMPT)
    candidate_result = await _run_live(candidate, prompt=_ORCHESTRATION_PROMPT)

    _assert_orchestration_gate_exercised(baseline_result)
    _assert_not_weaker(
        baseline=baseline_result,
        candidate=candidate_result,
        candidate_name="opensquilla",
    )


@pytest.mark.llm
@pytest.mark.llm_gateway
@pytest.mark.llm_tools
@pytest.mark.asyncio
async def test_live_pi_kernel_not_weaker_than_direct_python_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("OPENSQUILLA_AGENT_CORE_PI_LIVE") != "1":
        pytest.skip("set OPENSQUILLA_AGENT_CORE_PI_LIVE=1 to run live Pi adapter parity")
    _freeze_live_runtime_context(monkeypatch)
    command = _live_pi_rpc_command()

    baseline_config = _live_agent_config(max_iterations=2, max_tokens=128)
    candidate_config = _live_agent_config(max_iterations=2, max_tokens=128)
    session_key = "agent:main:live-agent-core-pi"
    baseline = Agent(
        provider=_live_provider(),
        config=baseline_config,
        tool_definitions=_tool_definitions(),
        tool_handler=_tool_handler,
        session_key=session_key,
    )
    session_write_recorder = _SessionWriteRecorder()
    candidate = build_agent_for_kernel(
        runtime_config=SimpleNamespace(
            agent_kernel="pi",
            pi_agent_rpc_command=command,
            pi_agent_rpc_command_provenance=_live_pi_rpc_command_provenance(),
        ),
        provider=_live_provider(),
        config=candidate_config,
        tool_definitions=_tool_definitions(),
        tool_handler=_tool_handler,
        usage_tracker=None,
        session_key=session_key,
        turn_call_logger=None,
        memory_sync_manager=None,
        session_flush_service=None,
        tool_registry=None,
        tool_context=None,
        session_manager=session_write_recorder,
    )

    _assert_not_weaker(
        baseline=await _run_live(baseline),
        candidate=await _run_live(
            candidate,
            session_write_recorder=session_write_recorder,
        ),
        candidate_name="pi",
    )


@pytest.mark.llm
@pytest.mark.llm_gateway
@pytest.mark.llm_tools
@pytest.mark.asyncio
async def test_live_pi_kernel_preserves_orchestration_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("OPENSQUILLA_AGENT_CORE_PI_LIVE") != "1":
        pytest.skip("set OPENSQUILLA_AGENT_CORE_PI_LIVE=1 to run live Pi adapter parity")
    _freeze_live_runtime_context(monkeypatch)
    command = _live_pi_rpc_command()

    system_prompt = (
        "When asked to call tools, call every requested tool before final answer."
    )
    baseline_config = _live_agent_config(
        max_iterations=4,
        max_tokens=256,
        system_prompt=system_prompt,
    )
    candidate_config = _live_agent_config(
        max_iterations=4,
        max_tokens=256,
        system_prompt=system_prompt,
    )
    session_key = "agent:main:live-agent-core-pi-orchestration"
    baseline = Agent(
        provider=_live_provider(),
        config=baseline_config,
        tool_definitions=_orchestration_tool_definitions(),
        tool_handler=_orchestration_tool_handler,
        session_key=session_key,
    )
    session_write_recorder = _SessionWriteRecorder()
    candidate = build_agent_for_kernel(
        runtime_config=SimpleNamespace(
            agent_kernel="pi",
            pi_agent_rpc_command=command,
            pi_agent_rpc_command_provenance=_live_pi_rpc_command_provenance(),
        ),
        provider=_live_provider(),
        config=candidate_config,
        tool_definitions=_orchestration_tool_definitions(),
        tool_handler=_orchestration_tool_handler,
        usage_tracker=None,
        session_key=session_key,
        turn_call_logger=None,
        memory_sync_manager=None,
        session_flush_service=None,
        tool_registry=None,
        tool_context=None,
        session_manager=session_write_recorder,
    )

    baseline_result = await _run_live(baseline, prompt=_ORCHESTRATION_PROMPT)
    candidate_result = await _run_live(
        candidate,
        prompt=_ORCHESTRATION_PROMPT,
        session_write_recorder=session_write_recorder,
    )

    _assert_orchestration_gate_exercised(baseline_result)
    _assert_not_weaker(
        baseline=baseline_result,
        candidate=candidate_result,
        candidate_name="pi",
    )
