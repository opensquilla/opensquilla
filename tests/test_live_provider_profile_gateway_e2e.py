from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path


def _load_e2e_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "live_provider_profile_gateway_e2e.py"
    )
    spec = importlib.util.spec_from_file_location("live_provider_profile_gateway_e2e", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


e2e = _load_e2e_module()


def test_gateway_e2e_defaults_cover_all_router_profiles() -> None:
    assert e2e.DEFAULT_PROVIDERS == [
        "openrouter",
        "dashscope",
        "deepseek",
        "gemini",
        "volcengine",
        "openai",
        "zhipu",
        "moonshot",
    ]


def test_natural_router_cases_are_text_only_marker_checks() -> None:
    for case in e2e.TIER_CASES:
        message = case["message"]
        assert "不要调用工具" in message, case["id"]
        assert "{marker}" in message, case["id"]


def test_structured_compare_case_is_bounded_to_keep_marker_in_smoke_budget() -> None:
    case = next(case for case in e2e.TIER_CASES if case["id"] == "r1_structured_compare")

    assert "不超过" in case["message"]


def test_debugging_case_is_bounded_to_keep_marker_in_smoke_budget() -> None:
    case = next(case for case in e2e.TIER_CASES if case["id"] == "r2_debugging")

    assert "不超过" in case["message"]


def test_case_markers_are_stable_text_not_millisecond_numbers() -> None:
    marker = e2e._case_marker("openrouter", "c2", "coverage_t2")

    assert marker == "E2E_OPENROUTER_C2_COVERAGE_T2"
    assert not marker.rsplit("_", 1)[-1].isdigit()


def test_live_gateway_profile_config_bounds_agent_runtime(tmp_path: Path) -> None:
    config_path = tmp_path / "gateway.toml"

    e2e._write_config(
        config_path,
        "openrouter",
        "https://openrouter.ai/api/v1",
        "deepseek/deepseek-v4-flash",
        max_tokens=384,
    )

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data["agent_max_iterations"] <= 8
    assert data["agent_runtime_timeout_seconds"] < data["llm_request_timeout_seconds"]
    assert data["task_runtime"]["turn_hard_deadline_s"] < 120.0


def test_profile_slot_targets_cover_slots_not_unique_models() -> None:
    tiers = {
        "c0": {"provider": "deepseek", "model": "deepseek-v4-flash"},
        "c1": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "thinking_level": "low",
        },
        "c2": {"provider": "deepseek", "model": "deepseek-v4-pro"},
        "c3": {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "thinking_level": "high",
        },
        "image_model": {"provider": "openrouter", "model": "vision", "image_only": True},
    }

    targets = e2e._profile_slot_targets(tiers)

    assert list(targets) == ["c0", "c1", "c2", "c3"]
    assert targets["c0"]["model"] == targets["c1"]["model"]
    assert targets["c1"]["thinking_level"] == "low"


def test_forced_tier_overrides_make_only_target_slot_text_routable() -> None:
    tiers = {
        "c0": {"provider": "deepseek", "model": "deepseek-v4-flash"},
        "c1": {"provider": "deepseek", "model": "deepseek-v4-flash"},
        "c2": {"provider": "deepseek", "model": "deepseek-v4-pro"},
        "c3": {"provider": "deepseek", "model": "deepseek-v4-pro"},
    }

    overrides = e2e._forced_tier_overrides_for_slot(tiers, "c2")

    assert overrides["c2"]["image_only"] is False
    assert overrides["c2"]["model"] == "deepseek-v4-pro"
    assert overrides["c0"]["image_only"] is True
    assert overrides["c1"]["image_only"] is True
    assert overrides["c3"]["image_only"] is True


def test_missing_profile_slots_are_computed_by_slot() -> None:
    tiers = {
        "c0": {"provider": "deepseek", "model": "deepseek-v4-flash"},
        "c1": {"provider": "deepseek", "model": "deepseek-v4-flash"},
        "c2": {"provider": "deepseek", "model": "deepseek-v4-pro"},
        "c3": {"provider": "deepseek", "model": "deepseek-v4-pro"},
    }
    rows = [
        {
            "ok": True,
            "expected_slot": "c0",
            "actual_slot_covered": "c0",
            "expected_model": "deepseek-v4-flash",
            "actual_request_model": "deepseek-v4-flash",
        },
        {
            "ok": True,
            "expected_slot": "c2",
            "actual_slot_covered": "c2",
            "expected_model": "deepseek-v4-pro",
            "actual_request_model": "deepseek-v4-pro",
        },
    ]

    assert e2e._missing_profile_slots(tiers, rows) == ["c1", "c3"]


def test_cost_summary_never_promotes_gateway_placeholder_to_provider_bill() -> None:
    cost = e2e._estimate_cost(
        "glm-5.1",
        {"input_tokens": 1000, "output_tokens": 2000, "billed_cost": 0.0},
    )

    assert cost["provider_billed_cost_usd"] is None
    assert cost["raw_gateway_usage_billed_cost_usd"] == 0.0
    assert cost["cost_source"] == "opensquilla_static_estimate"
    assert cost["opensquilla_estimated_cost_usd"] > 0


def test_openrouter_nonzero_billed_cost_is_recorded_as_provider_bill() -> None:
    cost = e2e._estimate_cost(
        "z-ai/glm-5.1",
        {"input_tokens": 1000, "output_tokens": 2000, "billed_cost": 0.0123},
        provider="openrouter",
    )

    assert cost["provider_billed_cost_usd"] == 0.0123
    assert cost["raw_gateway_usage_billed_cost_usd"] == 0.0123
    assert cost["cost_source"] == "provider_billed"
    assert cost["billing_scope"] == "provider_response"
    assert cost["opensquilla_estimated_cost_usd"] > 0


def test_router_step_is_extracted_from_decision_log() -> None:
    decision = {
        "pipeline_steps": [
            {"step_name": "resolve_model", "routed_tier": None},
            {
                "step_name": "apply_squilla_router",
                "routed_tier": "c2",
                "routing_source": "v4_phase3",
                "confidence": 0.91,
            },
        ]
    }

    step = e2e._router_step_from_decision(decision)

    assert step["routed_tier"] == "c2"
    assert step["routing_source"] == "v4_phase3"
    assert step["confidence"] == 0.91
