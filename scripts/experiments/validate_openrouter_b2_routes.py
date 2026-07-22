#!/usr/bin/env python3
"""Fail-closed, read-only OpenRouter endpoint preflight for formal DRACO runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

API_ORIGIN = "https://openrouter.ai"
B2_EXPECTED_ROUTES = {
    "deepseek/deepseek-v4-pro": "deepseek",
    "z-ai/glm-5.2": "z-ai",
    "moonshotai/kimi-k2.7-code": "moonshotai",
    "qwen/qwen3.7-max": "alibaba",
    "google/gemini-3.1-pro-preview": "google-ai-studio",
}
FORMAL_EXPECTED_ROUTES = {
    **B2_EXPECTED_ROUTES,
    "anthropic/claude-opus-4.8": "anthropic",
    "anthropic/claude-sonnet-5": "anthropic",
    "deepseek/deepseek-v4-flash": "deepseek",
    "google/gemini-3-flash-preview": "google-ai-studio",
    "kwaipilot/kat-coder-air-v2.5": "streamlake",
    "kwaipilot/kat-coder-pro-v2.5": "streamlake",
    "meta-llama/llama-4-scout": "groq",
    "minimax/minimax-m3": "minimax",
    "mistralai/mistral-medium-3-5": "mistral",
    "openai/gpt-5.5": "openai",
    "openai/gpt-5.6-luna": "openai",
    "poolside/laguna-xs-2.1": "poolside",
    "qwen/qwen3.7-plus": "alibaba",
    "tencent/hy3": "tencent",
    "x-ai/grok-4.5": "xai",
}
EXPECTED_PROVIDER_NAMES = {
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "z-ai": "Z.AI",
    "moonshotai": "Moonshot AI",
    "alibaba": "Alibaba",
    "google-ai-studio": "Google AI Studio",
    "openai": "OpenAI",
    "xai": "xAI",
    "streamlake": "StreamLake",
    "groq": "Groq",
    "minimax": "Minimax",
    "mistral": "Mistral",
    "poolside": "Poolside",
    "tencent": "Tencent",
}
# Match the actual frozen request surface.  B2 proposers do not receive tool
# definitions; only the GLM aggregator can call the local tool surface.  The
# Gemini Judge is also text-only.  Over-requiring tool support on every
# proposer would reject an otherwise valid formal route before the canary.
B2_REQUIRED_PARAMETERS = {
    model: {"max_tokens", "reasoning"} for model in B2_EXPECTED_ROUTES
}
B2_REQUIRED_PARAMETERS["deepseek/deepseek-v4-pro"].add("temperature")
B2_REQUIRED_PARAMETERS["z-ai/glm-5.2"] |= {
    "temperature",
    "tools",
}
B2_REQUIRED_PARAMETERS["qwen/qwen3.7-max"].add("temperature")
B2_REQUIRED_PARAMETERS["google/gemini-3.1-pro-preview"].add("temperature")
FORMAL_REASONING_INELIGIBLE_MODELS = frozenset(
    {
        "kwaipilot/kat-coder-air-v2.5",
        "kwaipilot/kat-coder-pro-v2.5",
        "meta-llama/llama-4-scout",
    }
)
FORMAL_UNSUPPORTED_TEMPERATURE_MODELS = frozenset(
    {
        "anthropic/claude-opus-4.8",
        "anthropic/claude-sonnet-5",
        "moonshotai/kimi-k2.7-code",
        "openai/gpt-5.5",
        "openai/gpt-5.6-luna",
    }
)
FORMAL_REQUIRED_PARAMETERS = {
    model: {"max_tokens", "tools"} for model in FORMAL_EXPECTED_ROUTES
}
for model in set(FORMAL_EXPECTED_ROUTES) - FORMAL_REASONING_INELIGIBLE_MODELS:
    FORMAL_REQUIRED_PARAMETERS[model].add("reasoning")
for model in set(FORMAL_EXPECTED_ROUTES) - FORMAL_UNSUPPORTED_TEMPERATURE_MODELS:
    FORMAL_REQUIRED_PARAMETERS[model].add("temperature")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def get_json(client: httpx.Client, path: str) -> tuple[Any, str]:
    url = f"{API_ORIGIN}{path}"
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = client.get(url)
            if response.is_redirect:
                raise RuntimeError(f"redirect refused for {path}")
            response.raise_for_status()
            payload = response.json()
            return payload, canonical_sha256(payload)
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(float(attempt))
    raise RuntimeError(f"OpenRouter metadata request failed for {path}: {last_error}")


def tag_matches(tag: str, expected: str) -> bool:
    return tag == expected or tag.startswith(f"{expected}/")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--scope", choices=("b2", "formal"), default="formal")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"refusing to overwrite route preflight evidence: {args.output}")
    return args


def main() -> int:
    args = parse_args()

    expected_routes = (
        FORMAL_EXPECTED_ROUTES if args.scope == "formal" else B2_EXPECTED_ROUTES
    )
    required_parameters = (
        FORMAL_REQUIRED_PARAMETERS
        if args.scope == "formal"
        else B2_REQUIRED_PARAMETERS
    )

    with httpx.Client(
        timeout=httpx.Timeout(20.0),
        trust_env=False,
        follow_redirects=False,
        headers={"Accept": "application/json"},
    ) as client:
        providers_payload, providers_sha256 = get_json(client, "/api/v1/providers")
        provider_rows = (
            providers_payload.get("data") if isinstance(providers_payload, dict) else None
        )
        if not isinstance(provider_rows, list):
            raise SystemExit("OpenRouter providers response has an invalid schema")
        provider_slugs = {
            str(row.get("slug"))
            for row in provider_rows
            if isinstance(row, dict) and row.get("slug")
        }
        missing_slugs = sorted(set(expected_routes.values()) - provider_slugs)
        if missing_slugs:
            raise SystemExit(f"OpenRouter provider slug(s) unavailable: {missing_slugs}")

        model_evidence: dict[str, Any] = {}
        for model, expected_provider in expected_routes.items():
            encoded_model = "/".join(quote(part, safe="") for part in model.split("/"))
            payload, response_sha256 = get_json(
                client,
                f"/api/v1/models/{encoded_model}/endpoints",
            )
            data = payload.get("data") if isinstance(payload, dict) else None
            endpoints = data.get("endpoints") if isinstance(data, dict) else None
            if not isinstance(endpoints, list):
                raise SystemExit(f"OpenRouter endpoint schema invalid for {model}")
            if data.get("id") != model:
                raise SystemExit(f"OpenRouter endpoint response model differs for {model}")
            matches = [
                row
                for row in endpoints
                if isinstance(row, dict)
                and tag_matches(str(row.get("tag") or ""), expected_provider)
            ]
            operational = [row for row in matches if row.get("status") == 0]
            compatible = [
                row
                for row in operational
                if required_parameters[model]
                <= {str(item) for item in (row.get("supported_parameters") or [])}
                and row.get("provider_name")
                == EXPECTED_PROVIDER_NAMES[expected_provider]
                and row.get("model_id") == model
            ]
            if not matches:
                raise SystemExit(
                    f"No OpenRouter endpoint matches {model} -> {expected_provider}"
                )
            if not operational:
                raise SystemExit(
                    f"No operational OpenRouter endpoint for {model} -> {expected_provider}"
                )
            if not compatible:
                raise SystemExit(
                    f"No operational endpoint supports the frozen request surface for {model}"
                )
            model_evidence[model] = {
                "expected_provider": expected_provider,
                "response_sha256": response_sha256,
                "matching_endpoints": [
                    {
                        "tag": row.get("tag"),
                        "provider_name": row.get("provider_name"),
                        "model_id": row.get("model_id"),
                        "status": row.get("status"),
                        "supported_parameters": sorted(
                            str(item) for item in (row.get("supported_parameters") or [])
                        ),
                        "pricing": row.get("pricing"),
                        "max_completion_tokens": row.get("max_completion_tokens"),
                    }
                    for row in matches
                ],
                "operational_match_count": len(operational),
                "compatible_operational_match_count": len(compatible),
                "required_parameters": sorted(required_parameters[model]),
            }

    evidence = {
        "schema": "opensquilla.openrouter-route-preflight/v2",
        "captured_at": datetime.now(UTC).isoformat(),
        "api_origin": API_ORIGIN,
        "scope": args.scope,
        "trust_env": False,
        "providers_response_sha256": providers_sha256,
        "expected_routes": expected_routes,
        "expected_routes_sha256": canonical_sha256(expected_routes),
        "required_parameters_sha256": canonical_sha256(
            {model: sorted(parameters) for model, parameters in required_parameters.items()}
        ),
        "models": model_evidence,
        "route_metadata_pass": True,
        "non_byok_verified": None,
        "billing_verified": None,
        "reasoning_ineligible_models": (
            sorted(FORMAL_REASONING_INELIGIBLE_MODELS)
            if args.scope == "formal"
            else []
        ),
        "scope_note": (
            "Public metadata availability only; per-request router metadata, non-BYOK "
            "usage evidence, canary, and account reconciliation remain mandatory."
        ),
    }
    atomic_write_json(args.output, evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
