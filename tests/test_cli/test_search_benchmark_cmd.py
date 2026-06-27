"""CLI tests for `opensquilla search benchmark`."""

from __future__ import annotations

import json
from typing import cast

from typer.testing import CliRunner

import opensquilla.cli.search_cmd as search_cmd  # type: ignore[import-untyped]
from opensquilla.cli.main import app  # type: ignore[import-untyped]
from opensquilla.search.types import DEFAULT_SEARCH_MAX_RESULTS

runner = CliRunner()


def _benchmark_payload() -> dict[str, object]:
    return {
        "profile": "smoke",
        "measurement_kind": "synthetic_smoke",
        "live": False,
        "v1": {
            "p50_latency_ms": 10,
            "p95_latency_ms": 20,
            "success_at_k": 0.7,
            "external_tool_calls_per_question": 2,
            "avg_returned_chars": 500,
            "duplicate_url_rate": 0.2,
            "fetch_success_rate": 0.8,
            "provider_fallback_count": 1,
        },
        "v2": {
            "p50_latency_ms": 12,
            "p95_latency_ms": 24,
            "success_at_k": 0.9,
            "external_tool_calls_per_question": 1,
            "avg_returned_chars": 300,
            "duplicate_url_rate": 0.0,
            "fetch_success_rate": 1.0,
            "provider_fallback_count": 0,
        },
        "delta": {
            "success_at_k": 0.2,
            "external_tool_calls_per_question": -1,
            "avg_returned_chars": -200,
        },
        "cases": [
            {"id": "official_docs", "query": "python release", "kind": "technical_docs"}
        ],
    }


def _numeric_metric(metrics: dict[str, object], key: str) -> int | float:
    value = metrics[key]
    assert isinstance(value, int | float)
    return value


def _assert_benchmark_metrics(payload: dict[str, object]) -> None:
    assert set(payload) >= {"v1", "v2", "delta"}
    for arm in ("v1", "v2"):
        assert isinstance(payload[arm], dict)
        metrics = cast(dict[str, object], payload[arm])
        assert set(metrics) >= {
            "p50_latency_ms",
            "p95_latency_ms",
            "success_at_k",
            "external_tool_calls_per_question",
            "avg_returned_chars",
            "duplicate_url_rate",
            "fetch_success_rate",
            "provider_fallback_count",
        }
    assert isinstance(payload["delta"], dict)
    delta = cast(dict[str, object], payload["delta"])
    assert set(delta) >= {
        "external_tool_calls_per_question",
        "avg_returned_chars",
        "success_at_k",
    }
    assert isinstance(payload.get("cases"), list)
    assert payload["cases"]
    for row in cast(list[dict[str, object]], payload["cases"]):
        assert set(row) >= {"id", "query", "kind"}
    v1 = cast(dict[str, object], payload["v1"])
    v2 = cast(dict[str, object], payload["v2"])
    assert _numeric_metric(v2, "external_tool_calls_per_question") < _numeric_metric(
        v1, "external_tool_calls_per_question"
    )
    assert _numeric_metric(v2, "avg_returned_chars") < _numeric_metric(v1, "avg_returned_chars")


def test_search_benchmark_smoke_json_uses_real_synthetic_output():
    result = runner.invoke(app, ["search", "benchmark", "--profile", "smoke", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["profile"] == "smoke"
    assert payload["measurement_kind"] == "synthetic_smoke"
    assert payload["live"] is False
    _assert_benchmark_metrics(payload)
    assert payload["query_count"] == len(payload["cases"])


def test_search_benchmark_passes_options_to_helper(monkeypatch):
    seen: list[tuple[str, int, int, bool]] = []

    def fake_run_search_benchmark(
        profile: str,
        fetch_top_k: int,
        max_results: int,
        live: bool = False,
    ) -> dict[str, object]:
        seen.append((profile, fetch_top_k, max_results, live))
        return _benchmark_payload()

    monkeypatch.setattr(search_cmd, "_run_search_benchmark", fake_run_search_benchmark)

    result = runner.invoke(app, ["search", "benchmark", "--profile", "smoke", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["profile"] == "smoke"
    assert payload["measurement_kind"] == "synthetic_smoke"
    assert payload["live"] is False
    _assert_benchmark_metrics(payload)
    assert payload["delta"]["external_tool_calls_per_question"] == -1
    assert payload["delta"]["avg_returned_chars"] == -200
    assert seen == [("smoke", 3, DEFAULT_SEARCH_MAX_RESULTS, False)]


def test_search_benchmark_live_json_rejects_without_env(monkeypatch):
    monkeypatch.delenv("OPENSQUILLA_LIVE_SEARCH", raising=False)

    result = runner.invoke(
        app,
        ["search", "benchmark", "--profile", "smoke", "--live", "--json"],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error_kind"] == "invalid_request"
    assert "live benchmark" in payload["error"]


def test_search_benchmark_live_json_rejects_even_with_env(monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_LIVE_SEARCH", "1")

    result = runner.invoke(
        app,
        ["search", "benchmark", "--profile", "smoke", "--live", "--json"],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error_kind"] == "invalid_request"
    assert "live gate test suite" in payload["error"]
    assert "measurement_kind" not in payload
    assert "v1" not in payload
    assert "v2" not in payload


def test_search_benchmark_rejects_zero_max_results_json():
    result = runner.invoke(
        app,
        ["search", "benchmark", "--profile", "smoke", "--max-results", "0", "--json"],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error_kind"] == "invalid_request"
    assert "max_results" in payload["error"]


def test_search_benchmark_rejects_negative_fetch_top_k_json():
    result = runner.invoke(
        app,
        ["search", "benchmark", "--profile", "smoke", "--fetch-top-k", "-1", "--json"],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error_kind"] == "invalid_request"
    assert "fetch_top_k" in payload["error"]


def test_search_benchmark_rejects_unknown_profile_json():
    result = runner.invoke(
        app,
        ["search", "benchmark", "--profile", "unknown", "--json"],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error_kind"] == "invalid_request"
