#!/usr/bin/env python3
"""Live smoke selected provider profiles without printing secrets."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from opensquilla.engine.pricing import lookup_price
from opensquilla.provider.registry import get_provider_spec
from opensquilla.provider.selector import ProviderConfig, _build_provider
from opensquilla.provider.types import ChatConfig, DoneEvent, ErrorEvent, Message, TextDeltaEvent


@dataclass
class SmokeResult:
    provider: str
    model: str
    base_url: str
    env_key: str
    key_present: bool
    direct_status: str
    stream_status: str
    response_model: str
    content_match: str
    usage: dict[str, Any]
    cost: dict[str, Any]
    error: str
    latency_ms: int


_MODEL_ENV = {
    "openai": "OPENAI_MODEL",
    "dashscope": "DASHSCOPE_MODEL",
    "deepseek": "DEEPSEEK_MODEL",
    "gemini": "GEMINI_MODEL",
    "volcengine": "VOLCENGINE_MODEL",
    "byteplus": "BYTEPLUS_MODEL",
    "bailian_coding": "BAILIAN_CODING_MODEL",
    "moonshot": "MOONSHOT_MODEL",
    "zhipu": "ZAI_MODEL",
    "qianfan": "QIANFAN_MODEL",
    "minimax": "MINIMAX_MODEL",
    "minimax_openai": "MINIMAX_MODEL",
    "minimax_cn": "MINIMAX_CN_MODEL",
    "minimax_global": "MINIMAX_GLOBAL_MODEL",
    "tencent_tokenhub": "TENCENT_TOKENHUB_MODEL",
    "tencent_tokenhub_anthropic": "TENCENT_TOKENHUB_MODEL",
    "tencent_tokenhub_intl": "TENCENT_TOKENHUB_INTL_MODEL",
    "tencent_token_plan": "TENCENT_TOKEN_PLAN_MODEL",
    "tencent_token_plan_anthropic": "TENCENT_TOKEN_PLAN_MODEL",
}

_BASE_ENV = {
    "openai": "OPENAI_BASE_URL",
    "dashscope": "DASHSCOPE_BASE_URL",
    "deepseek": "DEEPSEEK_BASE_URL",
    "gemini": "GEMINI_BASE_URL",
    "volcengine": "VOLCENGINE_BASE_URL",
    "byteplus": "BYTEPLUS_BASE_URL",
    "bailian_coding": "BAILIAN_CODING_BASE_URL",
    "moonshot": "MOONSHOT_BASE_URL",
    "zhipu": "ZAI_BASE_URL",
    "qianfan": "QIANFAN_BASE_URL",
    "minimax": "MINIMAX_BASE_URL",
    "minimax_openai": "MINIMAX_OPENAI_BASE_URL",
    "minimax_cn": "MINIMAX_CN_BASE_URL",
    "minimax_global": "MINIMAX_GLOBAL_BASE_URL",
    "tencent_tokenhub": "TENCENT_TOKENHUB_BASE_URL",
    "tencent_tokenhub_anthropic": "TENCENT_TOKENHUB_ANTHROPIC_BASE_URL",
    "tencent_tokenhub_intl": "TENCENT_TOKENHUB_INTL_BASE_URL",
    "tencent_token_plan": "TENCENT_TOKEN_PLAN_BASE_URL",
    "tencent_token_plan_anthropic": "TENCENT_TOKEN_PLAN_ANTHROPIC_BASE_URL",
}

_DEFAULT_MODELS = {
    "openai": "gpt-4.1",
    "dashscope": "qwen3.6-plus",
    "deepseek": "deepseek-v4-flash",
    "gemini": "gemini-2.5-flash",
    "volcengine": "doubao-seed-1-6-251015",
    "byteplus": "seed-2-0-lite-260228",
    "bailian_coding": "kimi-k2.5",
    "moonshot": "kimi-k2.6",
    "zhipu": "glm-4.5",
    "qianfan": "ernie-4.0-turbo-8k",
    "minimax": "MiniMax-M2.7",
    "minimax_openai": "MiniMax-M2.7",
    "minimax_cn": "MiniMax-M2.7",
    "minimax_global": "MiniMax-M2.7",
    "tencent_tokenhub": "hy3",
    "tencent_tokenhub_anthropic": "hy3",
    "tencent_tokenhub_intl": "deepseek-v3.2",
    "tencent_token_plan": "hy3",
    "tencent_token_plan_anthropic": "hy3",
}


def _csv_values(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _load_env_quietly(path: Path = Path(".env")) -> None:
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


def _headers_for_openai(api_key: str) -> dict[str, str]:
    # Keyless local providers must not send an empty Bearer value (httpx
    # rejects it as an illegal header).
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _headers_for_anthropic(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }


def _versioned_chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith(("/v1", "/v2", "/v3", "/v4")):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _direct_openai_temperature(provider: str, model: str) -> int:
    if provider == "moonshot" and model.lower().startswith("kimi-k2."):
        return 1
    return 0


async def _direct_openai(
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    expected: str,
    max_tokens: int,
) -> tuple[str, str, str, dict[str, Any], int]:
    start = time.perf_counter()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": f"Reply exactly with: {expected}",
            }
        ],
        "temperature": _direct_openai_temperature(provider, model),
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            resp = await client.post(
                _versioned_chat_url(base_url),
                headers=_headers_for_openai(api_key),
                json=payload,
            )
        latency = int((time.perf_counter() - start) * 1000)
        if resp.status_code >= 400:
            return "failed", "", _error_summary(resp), {}, latency
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        response_model = str(data.get("model") or "")
        status = "passed" if expected in content else "content_mismatch"
        return status, response_model, content, _usage_summary(data.get("usage")), latency
    except Exception as exc:  # noqa: BLE001 - smoke reports compact diagnostic
        latency = int((time.perf_counter() - start) * 1000)
        return "failed", "", f"{type(exc).__name__}: {exc}", {}, latency


async def _direct_anthropic(
    model: str,
    api_key: str,
    base_url: str,
    expected: str,
    max_tokens: int,
) -> tuple[str, str, str, dict[str, Any], int]:
    start = time.perf_counter()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": expected}],
        "max_tokens": max_tokens,
        "temperature": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/v1/messages",
                headers=_headers_for_anthropic(api_key),
                json=payload,
            )
        latency = int((time.perf_counter() - start) * 1000)
        if resp.status_code >= 400:
            return "failed", "", _error_summary(resp), {}, latency
        data = resp.json()
        text_parts = [
            block.get("text", "")
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "".join(text_parts)
        response_model = str(data.get("model") or "")
        status = "passed" if expected in content else "content_mismatch"
        return status, response_model, content, _usage_summary(data.get("usage")), latency
    except Exception as exc:  # noqa: BLE001 - smoke reports compact diagnostic
        latency = int((time.perf_counter() - start) * 1000)
        return "failed", "", f"{type(exc).__name__}: {exc}", {}, latency


async def _stream_opensquilla(
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    expected: str,
    max_tokens: int,
) -> tuple[str, str, dict[str, Any], int]:
    start = time.perf_counter()
    try:
        built = _build_provider(
            ProviderConfig(provider=provider, model=model, api_key=api_key, base_url=base_url)
        )
        chunks: list[str] = []
        done: DoneEvent | None = None
        async for event in built.chat(
            [Message(role="user", content=f"Reply exactly with: {expected}")],
            config=ChatConfig(max_tokens=max_tokens, temperature=1, timeout=30.0),
        ):
            if isinstance(event, TextDeltaEvent):
                chunks.append(event.text)
            elif isinstance(event, DoneEvent):
                done = event
            elif isinstance(event, ErrorEvent):
                latency = int((time.perf_counter() - start) * 1000)
                return "failed", event.message or event.code, {}, latency
        latency = int((time.perf_counter() - start) * 1000)
        content = "".join(chunks)
        if done is None:
            return "failed", "missing DoneEvent", {}, latency
        usage = {
            "input_tokens": done.input_tokens,
            "output_tokens": done.output_tokens,
            "cached_tokens": done.cached_tokens,
            "cache_write_tokens": done.cache_write_tokens,
            "reasoning_tokens": done.reasoning_tokens,
            "model": done.model,
            "billed_cost": done.billed_cost,
            "cost_source": done.cost_source,
        }
        status = "passed" if expected in content else "content_mismatch"
        return status, content, usage, latency
    except Exception as exc:  # noqa: BLE001 - smoke reports compact diagnostic
        latency = int((time.perf_counter() - start) * 1000)
        return "failed", f"{type(exc).__name__}: {exc}", {}, latency


def _usage_summary(usage: Any) -> dict[str, Any]:
    if not isinstance(usage, dict):
        return {}
    keys = (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    return {key: usage[key] for key in keys if key in usage}


def _cost_estimate(model: str, usage: dict[str, Any]) -> dict[str, Any]:
    direct_usage = usage.get("direct") if isinstance(usage.get("direct"), dict) else {}
    stream_usage = usage.get("stream") if isinstance(usage.get("stream"), dict) else {}
    prompt_tokens = direct_usage.get("prompt_tokens") or stream_usage.get("input_tokens") or 0
    completion_tokens = (
        direct_usage.get("completion_tokens") or stream_usage.get("output_tokens") or 0
    )
    price = lookup_price(model)
    estimate = (
        prompt_tokens * price.input_per_m + completion_tokens * price.output_per_m
    ) / 1_000_000
    # The stream DoneEvent carries the provider-billed cost when the upstream
    # reports one (OpenRouter usage.cost); surface it instead of pretending
    # only static estimates exist.
    billed = stream_usage.get("billed_cost") or 0.0
    billed_source = str(stream_usage.get("cost_source") or "")
    provider_billed = billed if billed > 0 and billed_source == "provider_billed" else None
    cost_source = billed_source if provider_billed is not None else "opensquilla_static_estimate"
    return {
        "provider_billed_cost_usd": provider_billed,
        "opensquilla_estimated_cost_usd": estimate,
        "cost_source": cost_source,
        "billing_scope": "provider_billed" if provider_billed is not None else "static_estimate",
        "provider_billed": provider_billed,
        "opensquilla_estimate": estimate,
        "input_per_m": price.input_per_m,
        "output_per_m": price.output_per_m,
        "source": cost_source,
    }


def _error_summary(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        body = resp.text[:300]
    return f"HTTP {resp.status_code}: {body}"


async def smoke_provider(
    provider: str,
    *,
    include_stream: bool = True,
    model_override: str | None = None,
    base_url_override: str | None = None,
    max_tokens: int = 64,
) -> SmokeResult:
    spec = get_provider_spec(provider)
    env_key = spec.env_key
    api_key = os.environ.get(env_key, "").strip()
    model = (
        model_override
        or os.environ.get(_MODEL_ENV.get(provider, ""), "").strip()
        or _DEFAULT_MODELS.get(provider, "")
    )
    if not model:
        raise SystemExit(
            f"no model configured for provider {provider!r}: pass --model or set "
            f"{_MODEL_ENV.get(provider) or 'a model env override'}"
        )
    base_url = (
        base_url_override
        or os.environ.get(_BASE_ENV.get(provider, ""), "").strip()
        or spec.default_base_url
    )
    expected = f"opensquilla {provider} smoke ok"

    # Local providers (ollama, lm_studio, ovms) declare their key optional in
    # the registry; only skip when the spec actually requires one.
    if not api_key and spec.requires_api_key():
        return SmokeResult(
            provider=provider,
            model=model,
            base_url=base_url,
            env_key=env_key,
            key_present=False,
            direct_status="skipped",
            stream_status="skipped",
            response_model="",
            content_match="not_run",
            usage={},
            cost={
                "provider_billed_cost_usd": None,
                "opensquilla_estimated_cost_usd": None,
                "cost_source": "unavailable",
                "billing_scope": "none",
                "provider_billed": None,
                "opensquilla_estimate": None,
                "source": "unavailable",
            },
            error=f"{env_key} is empty",
            latency_ms=0,
        )

    if spec.backend == "anthropic":
        (
            direct_status,
            response_model,
            direct_content,
            usage,
            direct_latency,
        ) = await _direct_anthropic(model, api_key, base_url, expected, max_tokens)
    else:
        direct_status, response_model, direct_content, usage, direct_latency = await _direct_openai(
            provider, model, api_key, base_url, expected, max_tokens
        )
    if include_stream:
        stream_status, stream_content, stream_usage, stream_latency = await _stream_opensquilla(
            provider, model, api_key, base_url, expected, max_tokens
        )
    else:
        stream_status = "skipped"
        stream_content = ""
        stream_usage = {}
        stream_latency = 0

    errors = []
    if direct_status == "failed":
        errors.append(f"direct={direct_content}")
    if stream_status == "failed":
        errors.append(f"stream={stream_content}")
    content_match = (
        "exact" if direct_status == "passed" and stream_status == "passed" else "not_validated"
    )
    if direct_status == "passed" and stream_status == "skipped":
        content_match = "direct_exact"
    merged_usage = {"direct": usage, "stream": stream_usage}

    return SmokeResult(
        provider=provider,
        model=model,
        base_url=base_url,
        env_key=env_key,
        key_present=bool(api_key),
        direct_status=direct_status,
        stream_status=stream_status,
        response_model=response_model,
        content_match=content_match,
        usage=merged_usage,
        cost=_cost_estimate(response_model or model, merged_usage),
        error="; ".join(errors),
        latency_ms=direct_latency + stream_latency,
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider")
    parser.add_argument(
        "--providers",
        nargs="+",
        default=["dashscope", "deepseek", "gemini", "volcengine", "byteplus"],
    )
    parser.add_argument("--models")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--skip-stream", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    _load_env_quietly()
    providers = [args.provider] if args.provider else list(args.providers)
    models = _csv_values(args.models)
    if args.model and models:
        parser.error("--model and --models are mutually exclusive")
    if models and len(providers) != 1:
        parser.error("--models requires exactly one provider")

    jobs: list[tuple[str, str | None]] = []
    if models:
        jobs = [(providers[0], model) for model in models]
    else:
        jobs = [(provider, args.model) for provider in providers]

    results = [
        await smoke_provider(
            provider,
            include_stream=not args.skip_stream,
            model_override=model,
            base_url_override=args.base_url,
            max_tokens=args.max_tokens,
        )
        for provider, model in jobs
    ]
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "results": [asdict(result) for result in results],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
