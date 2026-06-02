#!/usr/bin/env python3
"""Run live gateway E2E checks for direct provider tier profiles.

The check starts a temporary OpenSquilla gateway per provider, enables the
matching ``squilla_router.tier_profile``, sends one turn for each text tier,
and records routed model, response usage, and local cost estimates. Secrets are
kept in environment variables and are not written to the output artifact.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from opensquilla.engine.pricing import lookup_price  # noqa: E402
from opensquilla.gateway.config import GatewayConfig  # noqa: E402
from opensquilla.provider.registry import get_provider_spec  # noqa: E402
from scripts.smoke_v4_phase3_router import (  # noqa: E402
    _free_port,
    _post_json,
    _read_turn_call_records,
    _stop_gateway,
    _usage_from_llm_responses,
    _wait_for_assistant_reply,
    _wait_for_gateway_health,
)

DEFAULT_PROVIDERS = [
    "openrouter",
    "dashscope",
    "deepseek",
    "gemini",
    "volcengine",
    "openai",
    "zhipu",
    "moonshot",
]
BASE_ENV = {
    "openrouter": "OPENROUTER_BASE_URL",
    "openai": "OPENAI_BASE_URL",
    "dashscope": "DASHSCOPE_BASE_URL",
    "deepseek": "DEEPSEEK_BASE_URL",
    "gemini": "GEMINI_BASE_URL",
    "volcengine": "VOLCENGINE_BASE_URL",
    "moonshot": "MOONSHOT_BASE_URL",
    "zhipu": "ZAI_BASE_URL",
}
TEXT_PROFILE_SLOTS = ("c0", "c1", "c2", "c3")
LIVE_AGENT_MAX_ITERATIONS = 6
LIVE_AGENT_RUNTIME_TIMEOUT_SECONDS = 75.0
LIVE_TURN_HARD_DEADLINE_SECONDS = 90.0

TIER_CASES = [
    {
        "tier": "c0",
        "id": "r0_short_ack",
        "message": "谢谢。不要调用工具，请只回复一个短句，包含 {marker}。",
    },
    {
        "tier": "c1",
        "id": "r1_structured_compare",
        "message": (
            "不要调用工具，只输出 Markdown 表格和 marker。用不超过 4 行的表格比较 "
            "PostgreSQL 和 MySQL 在事务、索引、复制方面的差异，每格不超过 12 个字。"
            "最后一行单独写 {marker}。"
        ),
    },
    {
        "tier": "c2",
        "id": "r2_debugging",
        "message": (
            "下面是异步服务偶发超时的日志片段：连接池耗尽、慢查询、重试风暴、队列积压。"
            "不要调用工具，请用不超过三条短句定位可能原因并给出排查动作。"
            "最后一行单独写 {marker}。"
        ),
    },
    {
        "tier": "c3",
        "id": "r3_architecture",
        "message": (
            "请设计跨机房分布式任务调度系统，解释一致性、故障恢复和容量评估。"
            "不要调用工具，回答不超过五句，并包含 {marker}。"
        ),
    },
]


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _marker_component(value: str) -> str:
    raw = "".join(ch if ch.isalnum() else "_" for ch in value.upper())
    return "_".join(part for part in raw.split("_") if part)


def _case_marker(provider: str, slot: str, case_id: str) -> str:
    return (
        f"E2E_{_marker_component(provider)}_"
        f"{_marker_component(slot)}_{_marker_component(case_id)}"
    )


def _load_env_quietly(path: Path = REPO_ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _profile_tiers(provider: str) -> dict[str, dict[str, Any]]:
    cfg = GatewayConfig.model_validate(
        {
            "llm": {"provider": provider},
            "squilla_router": {"tier_profile": provider},
        }
    )
    return {
        name: dict(tier)
        for name, tier in cfg.squilla_router.tiers.items()
        if isinstance(tier, dict) and not tier.get("image_only")
    }


def _profile_slot_targets(tiers: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        slot: dict(tiers[slot])
        for slot in TEXT_PROFILE_SLOTS
        if isinstance(tiers.get(slot), dict) and not tiers[slot].get("image_only")
    }


def _covered_profile_slots(rows: list[dict[str, Any]]) -> list[str]:
    covered: list[str] = []
    for row in rows:
        slot = str(row.get("actual_slot_covered") or "")
        if row.get("ok") is True and slot and slot not in covered:
            covered.append(slot)
    return covered


def _missing_profile_slots(
    tiers: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[str]:
    covered = set(_covered_profile_slots(rows))
    return [slot for slot in _profile_slot_targets(tiers) if slot not in covered]


def _forced_tier_overrides_for_slot(
    tiers: dict[str, dict[str, Any]],
    slot: str,
) -> dict[str, dict[str, Any]]:
    target = dict(tiers[slot])
    overrides: dict[str, dict[str, Any]] = {}
    for text_slot in TEXT_PROFILE_SLOTS:
        if text_slot == slot:
            forced = dict(target)
            forced["image_only"] = False
            overrides[text_slot] = forced
        else:
            hidden = dict(tiers.get(text_slot, target))
            hidden["image_only"] = True
            overrides[text_slot] = hidden
    return overrides


def _render_tier_overrides(tiers: dict[str, dict[str, Any]] | None) -> str:
    if not tiers:
        return ""
    lines: list[str] = []
    for slot in TEXT_PROFILE_SLOTS:
        cfg = tiers.get(slot)
        if not isinstance(cfg, dict):
            continue
        lines.append("")
        lines.append(f"[squilla_router.tiers.{slot}]")
        for key in (
            "provider",
            "model",
            "description",
            "supports_image",
            "image_only",
            "thinking_level",
            "thinking",
            "supports_thinking",
        ):
            if key in cfg and cfg[key] is not None:
                lines.append(f"{key} = {_toml_value(cfg[key])}")
    return "\n".join(lines)


def _write_config(
    path: Path,
    provider: str,
    base_url: str,
    model: str,
    *,
    max_tokens: int,
    default_tier: str = "c1",
    tier_overrides: dict[str, dict[str, Any]] | None = None,
) -> None:
    tier_override_toml = _render_tier_overrides(tier_overrides)
    path.write_text(
        f"""
host = "127.0.0.1"
debug = false
llm_request_timeout_seconds = 90
agent_runtime_timeout_seconds = {LIVE_AGENT_RUNTIME_TIMEOUT_SECONDS}
agent_max_iterations = {LIVE_AGENT_MAX_ITERATIONS}

[auth]
mode = "none"

[control_ui]
enabled = false

[rate_limit]
enabled = false

[task_runtime]
turn_hard_deadline_s = {LIVE_TURN_HARD_DEADLINE_SECONDS}

[memory]
source = "state"

[llm]
provider = "{provider}"
model = "{model}"
base_url = "{base_url}"
max_tokens = {max_tokens}

[squilla_router]
enabled = true
auto_thinking = true
rollout_phase = "full"
strategy = "v4_phase3"
tier_profile = "{provider}"
default_tier = "{default_tier}"
confidence_threshold = 0.5
kv_cache_anti_downgrade_enabled = true
kv_cache_anti_downgrade_window_seconds = 600
complaint_upgrade_enabled = true
complaint_upgrade_steps = 1
require_router_runtime = true
{tier_override_toml}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _first_record(records: list[dict[str, Any]], *, session_key: str, kind: str) -> dict[str, Any]:
    for record in records:
        if record.get("session_key") == session_key and record.get("kind") == kind:
            return record
    return {}


def _read_decision_records(state_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((state_root / "logs").glob("decisions-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _decision_for_session(
    records: list[dict[str, Any]],
    *,
    session_key: str,
) -> dict[str, Any]:
    for record in records:
        if record.get("session_key") == session_key:
            return record
    return {}


def _router_step_from_decision(decision: dict[str, Any]) -> dict[str, Any]:
    for step in decision.get("pipeline_steps") or []:
        if step.get("step_name") == "apply_squilla_router":
            return step
    return {}


def _estimate_cost(
    model: str,
    usage: dict[str, Any],
    *,
    provider: str | None = None,
) -> dict[str, Any]:
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    price = lookup_price(model)
    estimate = (
        input_tokens * price.input_per_m + output_tokens * price.output_per_m
    ) / 1_000_000
    raw_billed_cost = usage.get("billed_cost")
    provider_billed_cost = None
    cost_source = "opensquilla_static_estimate"
    billing_scope = "static_estimate"
    if (
        provider == "openrouter"
        and isinstance(raw_billed_cost, int | float)
        and raw_billed_cost > 0
    ):
        provider_billed_cost = float(raw_billed_cost)
        cost_source = "provider_billed"
        billing_scope = "provider_response"
    return {
        "provider_billed_cost_usd": provider_billed_cost,
        "opensquilla_estimated_cost_usd": estimate,
        "cost_source": cost_source,
        "billing_scope": billing_scope,
        "raw_gateway_usage_billed_cost_usd": usage.get("billed_cost"),
        "provider_billed": provider_billed_cost,
        "opensquilla_estimate": estimate,
        "input_per_m": price.input_per_m,
        "output_per_m": price.output_per_m,
        "source": cost_source,
    }


def _failure_kind(
    row: dict[str, Any],
    actual_model: str,
    actual_routed_tier: str | None,
) -> str | None:
    error = str(row.get("turn_error") or "")
    if error:
        lowered = error.lower()
        if "401" in lowered or "authentication" in lowered or "unauthorized" in lowered:
            return "auth_failed"
        if "429" in lowered or "quota" in lowered or "billing" in lowered:
            return "quota_or_billing_blocked"
        if "timeout" in lowered:
            return "gateway_turn_timeout"
        if "model" in lowered and ("not" in lowered or "invalid" in lowered):
            return "model_unavailable"
        return "unknown_provider_error"
    if not row.get("assistant_excerpt"):
        return "gateway_turn_timeout"
    if not row.get("assistant_marker_present"):
        return "content_marker_missing"
    if actual_routed_tier != row.get("expected_slot"):
        return "router_selected_unexpected_tier"
    if actual_model != row.get("expected_model"):
        return "model_unavailable"
    return None


def _actual_model_from_records(
    request: dict[str, Any],
    response: dict[str, Any],
) -> str:
    request_payload = request.get("payload") or {}
    response_payload = response.get("payload") or {}
    request_config = request_payload.get("config") or {}
    usage = response_payload.get("usage") or {}
    return str(
        request_payload.get("model")
        or request_config.get("model")
        or request.get("model")
        or usage.get("model")
        or response.get("model")
        or ""
    )


def _run_gateway_case_batch(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    tiers: dict[str, dict[str, Any]],
    cases: list[dict[str, Any]],
    max_tokens: int,
    timeout_seconds: float,
    case_mode: str,
    default_tier: str = "c1",
    tier_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    active_tiers = tier_overrides or tiers
    default_model = str(
        active_tiers.get(default_tier, {}).get("model")
        or tiers.get(default_tier, {}).get("model")
        or next(iter(_profile_slot_targets(tiers).values())).get("model")
        or ""
    )
    port = _free_port()
    tmp_path = Path(tempfile.mkdtemp(prefix=f"opensquilla-{provider}-profile-e2e-"))
    config_path = tmp_path / "gateway.toml"
    turn_log_dir = tmp_path / "turn-calls"
    _write_config(
        config_path,
        provider,
        base_url,
        default_model,
        max_tokens=max_tokens,
        default_tier=default_tier,
        tier_overrides=tier_overrides,
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["OPENSQUILLA_GATEWAY_CONFIG_PATH"] = str(config_path)
    env["OPENSQUILLA_STATE_DIR"] = str(tmp_path / "state")
    env["OPENSQUILLA_MEMORY_DREAM_DISABLED"] = "1"
    env["OPENSQUILLA_TOOL_PROFILE"] = "channel_default"
    env["OPENSQUILLA_TURN_CALL_LOG"] = "1"
    env["OPENSQUILLA_TURN_CALL_LOG_DIR"] = str(turn_log_dir)
    env["OPENSQUILLA_LLM_PROVIDER"] = provider
    env["OPENSQUILLA_LLM_MODEL"] = default_model
    env["OPENSQUILLA_LLM_API_KEY"] = api_key
    env["OPENSQUILLA_LLM_BASE_URL"] = base_url
    if provider != "openrouter":
        # build_services still gives OPENROUTER_API_KEY special precedence for
        # legacy paths. Keep it empty for direct-provider profiles so dotenv
        # loading cannot override the selected provider key.
        env["OPENROUTER_API_KEY"] = ""
        env["OPENROUTER_BASE_URL"] = ""

    stdout_path = tmp_path / "gateway.stdout.log"
    stderr_path = tmp_path / "gateway.stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_file:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "opensquilla.cli.main",
                "gateway",
                "run",
                "--port",
                str(port),
                "--bind",
                "127.0.0.1",
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )

        health: dict[str, Any] | None = None
        error: str | None = None
        rows: list[dict[str, Any]] = []
        try:
            health, error = _wait_for_gateway_health(proc, port)
            if error is None:
                for case in cases:
                    slot = str(case.get("slot") or case.get("tier") or default_tier)
                    marker = _case_marker(provider, slot, str(case["id"]))
                    session_key = (
                        f"profile-e2e:{provider}:{case['id']}:{int(time.time() * 1000)}"
                    )
                    message = case["message"].format(marker=marker)
                    try:
                        accepted = _post_json(
                            f"http://127.0.0.1:{port}/api/chat",
                            {
                                "sessionKey": session_key,
                                "message": message,
                                "intent": "new_chat",
                            },
                            timeout=10.0,
                        )
                        assistant, history, turn_error = _wait_for_assistant_reply(
                            port=port,
                            session_key=session_key,
                            previous_assistant_count=0,
                            timeout_seconds=timeout_seconds,
                        )
                    except Exception as exc:  # noqa: BLE001 - compact E2E diagnostic
                        accepted = {}
                        assistant = None
                        history = None
                        turn_error = f"{type(exc).__name__}: {exc}"
                    assistant_text = str((assistant or {}).get("text", "")).strip()
                    rows.append(
                        {
                            "case_id": case["id"],
                            "case_mode": case_mode,
                            "expected_slot": slot,
                            "expected_tier": slot,
                            "expected_model": str(tiers.get(slot, {}).get("model") or ""),
                            "marker": marker,
                            "session_key": session_key,
                            "accepted": accepted,
                            "assistant_excerpt": assistant_text[:240],
                            "assistant_marker_present": marker in assistant_text,
                            "history_message_count": len((history or {}).get("messages", [])),
                            "turn_error": turn_error,
                        }
                    )
        finally:
            _stop_gateway(proc)
            stdout_file.flush()
            stderr_file.flush()
            records = _read_turn_call_records(turn_log_dir)
            decisions = _read_decision_records(tmp_path / "state")
    stdout_tail = stdout_path.read_text(encoding="utf-8", errors="replace")[-2000:]
    stderr_tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]

    enriched: list[dict[str, Any]] = []
    for row in rows:
        request = _first_record(records, session_key=row["session_key"], kind="llm_request")
        response = _first_record(records, session_key=row["session_key"], kind="llm_response")
        decision = _decision_for_session(decisions, session_key=row["session_key"])
        router_step = _router_step_from_decision(decision)
        request_payload = request.get("payload") or {}
        response_payload = response.get("payload") or {}
        request_config = request_payload.get("config") or {}
        usage = response_payload.get("usage") or {}
        actual_model = _actual_model_from_records(request, response)
        actual_routed_tier = (
            router_step.get("routed_tier")
            or request_payload.get("routed_tier")
            or request_payload.get("squilla_router_tier")
            or request_config.get("routed_tier")
        )
        if actual_routed_tier is not None:
            actual_routed_tier = str(actual_routed_tier)
        failure_kind = _failure_kind(row, actual_model, actual_routed_tier)
        row_ok = (
            failure_kind is None
            and bool(row.get("assistant_excerpt"))
            and actual_model == row["expected_model"]
            and actual_routed_tier == row["expected_slot"]
        )
        enriched.append(
            {
                **row,
                "ok": row_ok,
                "failure_kind": failure_kind,
                "error": row.get("turn_error"),
                "actual_routed_tier": actual_routed_tier,
                "routing_source": router_step.get("routing_source"),
                "routing_confidence": router_step.get("confidence"),
                "actual_slot_covered": row["expected_slot"] if row_ok else None,
                "actual_request_model": actual_model or request.get("model"),
                "actual_response_model": usage.get("model"),
                "request_thinking": request_config.get("thinking"),
                "request_thinking_level": request_config.get("thinking_level"),
                "usage": {
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "reasoning_tokens": usage.get("reasoning_tokens"),
                    "cached_tokens": usage.get("cached_tokens"),
                    "billed_cost": usage.get("billed_cost"),
                },
                "cost": _estimate_cost(
                    actual_model or row["expected_model"],
                    usage,
                    provider=provider,
                ),
            }
        )

    llm_responses = [record for record in records if record.get("kind") == "llm_response"]
    batch_ok = error is None and bool(enriched) and all(row["ok"] for row in enriched)
    return {
        "case_mode": case_mode,
        "ok": batch_ok,
        "health": health or {},
        "cases": enriched,
        "usage_from_turn_logs": _usage_from_llm_responses(llm_responses),
        "error": error,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }


def _run_provider(provider: str, *, max_tokens: int, timeout_seconds: float) -> dict[str, Any]:
    spec = get_provider_spec(provider)
    api_key = os.environ.get(spec.env_key, "").strip()
    base_url = os.environ.get(BASE_ENV.get(provider, ""), "").strip() or spec.default_base_url
    tiers = _profile_tiers(provider)
    slot_targets = _profile_slot_targets(tiers)
    if not api_key:
        return {
            "provider": provider,
            "ok": False,
            "provider_ok": False,
            "skipped": True,
            "failure_kind": "skipped_missing_key",
            "env_key": spec.env_key,
            "base_url": base_url,
            "key_present": False,
            "tier_profile": provider,
            "tier_models": {slot: cfg.get("model") for slot, cfg in slot_targets.items()},
            "profile_slots_covered": [],
            "profile_slots_missing": list(slot_targets),
            "models_covered": [],
            "error": f"{spec.env_key} is empty",
        }

    natural = _run_gateway_case_batch(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        tiers=tiers,
        cases=TIER_CASES,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        case_mode="natural_router",
    )
    all_cases = list(natural.get("cases") or [])
    coverage_batches: list[dict[str, Any]] = []
    for missing_slot in _missing_profile_slots(tiers, all_cases):
        target_case = {
            "slot": missing_slot,
            "id": f"coverage_{missing_slot}",
            "message": (
                "不要调用工具，请只回复一句中文短句并包含 {marker}。"
            ),
        }
        batch = _run_gateway_case_batch(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            tiers=tiers,
            cases=[target_case],
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            case_mode="coverage_compensation",
            default_tier=missing_slot,
            tier_overrides=_forced_tier_overrides_for_slot(tiers, missing_slot),
        )
        coverage_batches.append(batch)
        all_cases.extend(batch.get("cases") or [])

    covered_slots = _covered_profile_slots(all_cases)
    missing_slots = _missing_profile_slots(tiers, all_cases)
    models_covered = sorted(
        {
            str(row.get("actual_request_model") or row.get("expected_model") or "")
            for row in all_cases
            if row.get("ok") is True
        }
        - {""}
    )
    natural_cases = [row for row in all_cases if row.get("case_mode") == "natural_router"]
    coverage_cases = [
        row for row in all_cases if row.get("case_mode") == "coverage_compensation"
    ]
    provider_ok = not missing_slots and any(
        row.get("case_mode") == "natural_router" and row.get("assistant_excerpt")
        for row in all_cases
    )
    failure_kinds = sorted(
        {str(row.get("failure_kind")) for row in all_cases if row.get("failure_kind")}
    )
    return {
        "provider": provider,
        "ok": provider_ok,
        "provider_ok": provider_ok,
        "env_key": spec.env_key,
        "base_url": base_url,
        "key_present": bool(api_key),
        "tier_profile": provider,
        "tier_models": {slot: cfg.get("model") for slot, cfg in slot_targets.items()},
        "profile_slots_covered": covered_slots,
        "profile_slots_missing": missing_slots,
        "models_covered": models_covered,
        "natural_cases_ok": bool(natural_cases)
        and all(
            row.get("failure_kind") in (None, "router_selected_unexpected_tier")
            for row in natural_cases
        ),
        "coverage_cases_ok": bool(coverage_cases) and all(row.get("ok") for row in coverage_cases)
        if coverage_cases
        else True,
        "health": natural.get("health") or {},
        "cases": all_cases,
        "batches": [natural, *coverage_batches],
        "usage_from_turn_logs": natural.get("usage_from_turn_logs"),
        "failure_kinds": failure_kinds,
        "error": "; ".join(failure_kinds) or natural.get("error"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", nargs="+", default=DEFAULT_PROVIDERS)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args()

    _load_env_quietly()
    results = [
        _run_provider(
            provider,
            max_tokens=args.max_tokens,
            timeout_seconds=args.timeout_seconds,
        )
        for provider in args.providers
    ]
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "ok": all(result.get("ok") is True for result in results),
        "note": (
            "provider_billed_cost_usd is unavailable here; "
            "opensquilla_estimated_cost_usd is a static local estimate computed "
            "from returned token usage."
        ),
        "results": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
