#!/usr/bin/env python3
"""Opt-in OpenRouter explicit prompt-cache smoke for one model.

The smoke sends the same large system prompt twice and reports whether the
second response exposes non-zero cached prompt tokens. It is intentionally not
part of default CI; run it only with live OpenRouter credentials.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import httpx

DEFAULT_MODEL = "z-ai/glm-5.1"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def _cached_prompt_tokens(payload: dict[str, Any]) -> int:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return 0

    prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        value = prompt_details.get("cached_tokens")
        if isinstance(value, int):
            return max(0, value)

    for key in (
        "cached_tokens",
        "prompt_cache_hit_tokens",
        "cache_read_input_tokens",
        "cached_input_tokens",
    ):
        value = usage.get(key)
        if isinstance(value, int):
            return max(0, value)
    return 0


def _cache_request_payload(model: str, system_text: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {"role": "user", "content": "Reply with exactly: cache-smoke-ok"},
        ],
        "max_tokens": 16,
        "temperature": 0,
    }


def _large_system_prompt() -> str:
    stable_line = (
        "OpenSquilla explicit cache smoke stable prefix. "
        "This text is synthetic public test material. "
    )
    return stable_line * 260


def _post_once(
    client: httpx.Client,
    *,
    url: str,
    api_key: str,
    model: str,
    system_text: str,
) -> dict[str, Any]:
    response = client.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://opensquilla.ai",
            "X-OpenRouter-Title": "OpenSquilla cache smoke",
        },
        json=_cache_request_payload(model, system_text),
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("OpenRouter returned a non-object JSON payload")
    return data


def run_smoke(*, api_key: str, model: str, base_url: str, timeout: float) -> dict[str, Any]:
    system_text = _large_system_prompt()
    url = base_url.rstrip("/") + "/chat/completions"
    with httpx.Client(timeout=timeout, trust_env=True) as client:
        first = _post_once(client, url=url, api_key=api_key, model=model, system_text=system_text)
        second = _post_once(client, url=url, api_key=api_key, model=model, system_text=system_text)

    first_cached = _cached_prompt_tokens(first)
    second_cached = _cached_prompt_tokens(second)
    return {
        "model": model,
        "base_url": base_url,
        "explicit_cache_supported": second_cached > 0,
        "first_cached_tokens": first_cached,
        "second_cached_tokens": second_cached,
        "usage_fields_present": {
            "first": sorted((first.get("usage") or {}).keys())
            if isinstance(first.get("usage"), dict)
            else [],
            "second": sorted((second.get("usage") or {}).keys())
            if isinstance(second.get("usage"), dict)
            else [],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default=os.environ.get("OPENROUTER_CACHE_SMOKE_MODEL", DEFAULT_MODEL)
    )
    parser.add_argument(
        "--base-url", default=os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL)
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("OPENROUTER_CACHE_SMOKE_TIMEOUT", "90")),
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print(
            json.dumps({"ok": False, "error": "OPENROUTER_API_KEY is required"}, ensure_ascii=False)
        )
        return 2

    try:
        result = run_smoke(
            api_key=api_key,
            model=args.model,
            base_url=args.base_url,
            timeout=args.timeout,
        )
    except Exception as exc:  # pragma: no cover - live diagnostic path
        print(json.dumps({"ok": False, "error": str(exc), "model": args.model}, ensure_ascii=False))
        return 1

    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
