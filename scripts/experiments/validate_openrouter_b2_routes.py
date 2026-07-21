#!/usr/bin/env python3
"""Fail-closed, read-only OpenRouter endpoint preflight for formal DRACO B2."""

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
EXPECTED_ROUTES = {
    "deepseek/deepseek-v4-pro": "deepseek",
    "z-ai/glm-5.2": "z-ai",
    "moonshotai/kimi-k2.7-code": "moonshotai",
    "qwen/qwen3.7-max": "alibaba",
    "google/gemini-3.1-pro-preview": "google-ai-studio",
}
EXPECTED_PROVIDER_NAMES = {
    "deepseek": "DeepSeek",
    "z-ai": "Z.AI",
    "moonshotai": "Moonshot AI",
    "alibaba": "Alibaba",
    "google-ai-studio": "Google AI Studio",
}
# Match the actual frozen request surface.  B2 proposers do not receive tool
# definitions; only the GLM aggregator can call the local tool surface.  The
# Gemini Judge is also text-only.  Over-requiring tool support on every
# proposer would reject an otherwise valid formal route before the canary.
REQUIRED_PARAMETERS = {
    model: {"max_tokens", "reasoning"} for model in EXPECTED_ROUTES
}
REQUIRED_PARAMETERS["z-ai/glm-5.2"] |= {"tools", "tool_choice"}


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite route preflight evidence: {args.output}")

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
        missing_slugs = sorted(set(EXPECTED_ROUTES.values()) - provider_slugs)
        if missing_slugs:
            raise SystemExit(f"OpenRouter provider slug(s) unavailable: {missing_slugs}")

        model_evidence: dict[str, Any] = {}
        for model, expected_provider in EXPECTED_ROUTES.items():
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
                if REQUIRED_PARAMETERS[model]
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
                "required_parameters": sorted(REQUIRED_PARAMETERS[model]),
            }

    evidence = {
        "schema": "opensquilla.openrouter-route-preflight/v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "api_origin": API_ORIGIN,
        "trust_env": False,
        "providers_response_sha256": providers_sha256,
        "expected_routes": EXPECTED_ROUTES,
        "models": model_evidence,
        "pass": True,
        "scope_note": (
            "Public metadata availability only; per-request router metadata, non-BYOK "
            "usage evidence, canary, and account reconciliation remain mandatory."
        ),
    }
    atomic_write_json(args.output, evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
