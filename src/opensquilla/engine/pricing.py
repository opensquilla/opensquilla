"""Model pricing lookup for cost estimation + OpenRouter live cache."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, cast

import httpx
import structlog

from opensquilla.env import trust_env as _trust_env
from opensquilla.provider.openrouter_attribution import openrouter_app_headers
from opensquilla.secrets import clean_header_secret

log = structlog.get_logger(__name__)

_CACHE_TTL = 3600  # 1 hour
_HTTP_TIMEOUT = 3.0
_OPENROUTER_PRICING_BASE_URL = "https://openrouter.ai/api/v1"
_LIVE_PRICE_MISS_TTL = 300


@dataclass
class ModelPrice:
    """Per-token cost for a model (USD)."""

    input_per_token: float
    output_per_token: float


class PricingCache:
    """Fetches and caches model pricing from OpenRouter /api/v1/models."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        ttl_seconds: int = _CACHE_TTL,
    ) -> None:
        self._api_key = clean_header_secret(api_key, label="OpenRouter API key")
        self._base_url = base_url.rstrip("/")
        self._ttl = ttl_seconds
        self._cache: dict[str, ModelPrice] = {}
        self._fetched_at: float = 0

    @property
    def is_stale(self) -> bool:
        return time.monotonic() - self._fetched_at > self._ttl

    def get_price_sync(self, model_id: str) -> ModelPrice | None:
        """Get cached price without refreshing."""
        override = _lookup_price_override(model_id)
        if override is not None:
            return _model_price_from_entry(override)
        return self._cache.get(model_id)

    async def get_price(self, model_id: str) -> ModelPrice | None:
        """Get price, refreshing cache if stale."""
        override = _lookup_price_override(model_id)
        if override is not None:
            return _model_price_from_entry(override)
        if self.is_stale:
            await self.refresh()
        return self._cache.get(model_id)

    async def refresh(self) -> None:
        """Fetch model list from OpenRouter and update cache."""
        url = f"{self._base_url}/models"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        headers.update(openrouter_app_headers(self._base_url))
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, trust_env=_trust_env()) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            new_cache: dict[str, ModelPrice] = {}
            for model in data.get("data", []):
                model_id = model.get("id", "")
                pricing = model.get("pricing", {})
                override = _lookup_price_override(model_id)
                if override is not None:
                    new_cache[model_id] = _model_price_from_entry(override)
                    continue
                prompt_cost = pricing.get("prompt")
                completion_cost = pricing.get("completion")
                if prompt_cost is not None and completion_cost is not None:
                    try:
                        new_cache[model_id] = ModelPrice(
                            input_per_token=float(prompt_cost),
                            output_per_token=float(completion_cost),
                        )
                    except (ValueError, TypeError):
                        continue

            self._cache = new_cache
            self._fetched_at = time.monotonic()
            log.info("pricing.refreshed", models=len(new_cache))
        except Exception as exc:
            log.warning("pricing.refresh_failed", error=str(exc))


@dataclass
class PriceEntry:
    """Pricing per 1M tokens in USD."""

    input_per_m: float
    output_per_m: float


# Canonical non-discount prices that must override OpenRouter's promotional or routed
# discounted prices. Values are USD per 1M tokens from official provider pricing.
_PRICE_OVERRIDES: list[tuple[str, PriceEntry]] = [
    ("deepseek/deepseek-v4-pro", PriceEntry(1.74, 3.48)),
]


_PRICE_LOCK = threading.RLock()
_LIVE_PRICE_CACHE: dict[str, PriceEntry] = {}
_LIVE_PRICE_FETCHED_AT: dict[str, float] = {}
_LIVE_PRICE_MISS_AT: dict[str, float] = {}


def _lookup_price_override(model_id: str) -> PriceEntry | None:
    model_lower = str(model_id or "").strip().lower()
    for prefix, entry in _PRICE_OVERRIDES:
        if model_lower.startswith(prefix):
            return entry
    return None


def _model_price_from_entry(entry: PriceEntry) -> ModelPrice:
    return ModelPrice(
        input_per_token=entry.input_per_m / 1_000_000,
        output_per_token=entry.output_per_m / 1_000_000,
    )


def _live_pricing_enabled() -> bool:
    raw = os.environ.get("OPENSQUILLA_OPENROUTER_LIVE_PRICING", "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _normalize_openrouter_base_url(base_url: str | None = None) -> str:
    base = (base_url or os.environ.get("OPENROUTER_BASE_URL") or _OPENROUTER_PRICING_BASE_URL)
    base = base.rstrip("/")
    if base.endswith("/v1"):
        return base
    if base.endswith("/api"):
        return f"{base}/v1"
    return base


def _openrouter_endpoint_url(model_id: str, base_url: str | None = None) -> str:
    base = _normalize_openrouter_base_url(base_url)
    return f"{base}/models/{model_id}/endpoints"


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _apply_discount_inverse(price_per_token: float, discount: float) -> float:
    """Return the non-discounted token price when OpenRouter reports a discount.

    OpenRouter endpoint pricing also includes cache-read rates. Those are not
    used here: Squilla Router savings and OpenSquilla estimates must use the normal
    prompt/completion price, then remove any explicit endpoint discount.
    """
    if discount <= 0:
        return price_per_token
    rate = discount / 100 if discount > 1 else discount
    if rate <= 0 or rate >= 1:
        return price_per_token
    return price_per_token / (1 - rate)


def _endpoint_price(entry: dict) -> PriceEntry | None:
    pricing = entry.get("pricing") or {}
    prompt = _float_or_none(pricing.get("prompt"))
    completion = _float_or_none(pricing.get("completion"))
    if prompt is None or completion is None:
        return None
    discount = _float_or_none(pricing.get("discount")) or 0.0
    return PriceEntry(
        input_per_m=_apply_discount_inverse(prompt, discount) * 1_000_000,
        output_per_m=_apply_discount_inverse(completion, discount) * 1_000_000,
    )


def _normalize_provider_token(value: object) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _official_provider_tokens(model_id: str) -> set[str]:
    namespace = model_id.split("/", 1)[0]
    normalized = _normalize_provider_token(namespace)
    aliases = {
        "zai": {"zai"},
        "moonshotai": {"moonshotai", "moonshot"},
    }
    return aliases.get(normalized, {normalized})


def _is_official_endpoint(model_id: str, endpoint: dict) -> bool:
    official = _official_provider_tokens(model_id)
    provider_name = _normalize_provider_token(endpoint.get("provider_name"))
    tag_root = str(endpoint.get("tag") or "").split("/", 1)[0]
    tag = _normalize_provider_token(tag_root)
    return provider_name in official or tag in official


def _select_official_endpoint_price(data: dict, model_id: str) -> PriceEntry | None:
    """Select a live OpenRouter price from model endpoint metadata.

    The public ``/models`` list can expose a cheap routed/top-provider price.
    For savings display we need the official provider's non-cache,
    non-discount prompt/completion price. Prefer the endpoint whose
    ``provider_name`` or tag matches the model namespace, then fall back to the
    first priced endpoint if OpenRouter has no owner endpoint for that model.
    """
    model = data.get("data") or data
    endpoints = model.get("endpoints") or []
    if not endpoints:
        return _endpoint_price(model)

    for endpoint in endpoints:
        if _is_official_endpoint(model_id, endpoint):
            price = _endpoint_price(endpoint)
            if price is not None:
                return price
    for endpoint in endpoints:
        price = _endpoint_price(endpoint)
        if price is not None:
            return price
    return None


def _fetch_openrouter_json_sync(url: str) -> dict:
    with httpx.Client(timeout=_HTTP_TIMEOUT, trust_env=_trust_env()) as client:
        resp = client.get(url, headers=openrouter_app_headers(url))
        resp.raise_for_status()
        return cast(dict[Any, Any], resp.json())


def _fetch_live_openrouter_price(model_id: str, base_url: str | None = None) -> PriceEntry | None:
    override = _lookup_price_override(model_id)
    if override is not None:
        return override
    try:
        data = _fetch_openrouter_json_sync(_openrouter_endpoint_url(model_id, base_url))
    except Exception as exc:
        log.debug("pricing.live_lookup_failed", model=model_id, error=str(exc))
        return None
    price = _select_official_endpoint_price(data, model_id)
    if price is not None:
        log.debug(
            "pricing.live_lookup_ready",
            model=model_id,
            input_per_m=price.input_per_m,
            output_per_m=price.output_per_m,
        )
    return price


def refresh_live_prices(
    model_ids: list[str] | tuple[str, ...] | set[str],
    base_url: str | None = None,
) -> None:
    """Preload live OpenRouter endpoint prices for known model IDs."""
    for model_id in sorted({str(mid).strip() for mid in model_ids if str(mid).strip()}):
        override = _lookup_price_override(model_id)
        if override is not None:
            now = time.monotonic()
            key = model_id.lower()
            with _PRICE_LOCK:
                _LIVE_PRICE_CACHE[key] = override
                _LIVE_PRICE_FETCHED_AT[key] = now
                _LIVE_PRICE_MISS_AT.pop(key, None)
            continue
        if not _should_fetch_live_price(model_id):
            continue
        price = _fetch_live_openrouter_price(model_id, base_url)
        now = time.monotonic()
        key = model_id.lower()
        with _PRICE_LOCK:
            if price is None:
                _LIVE_PRICE_MISS_AT[key] = now
                continue
            _LIVE_PRICE_CACHE[key] = price
            _LIVE_PRICE_FETCHED_AT[key] = now
            _LIVE_PRICE_MISS_AT.pop(key, None)


def reset_live_price_cache_for_tests() -> None:
    with _PRICE_LOCK:
        _LIVE_PRICE_CACHE.clear()
        _LIVE_PRICE_FETCHED_AT.clear()
        _LIVE_PRICE_MISS_AT.clear()


def seed_live_price_cache_for_tests(model_id: str, price: PriceEntry) -> None:
    with _PRICE_LOCK:
        key = model_id.lower()
        _LIVE_PRICE_CACHE[key] = price
        _LIVE_PRICE_FETCHED_AT[key] = time.monotonic()
        _LIVE_PRICE_MISS_AT.pop(key, None)


# Built-in pricing table: model_prefix → (input_per_M, output_per_M)
_PRICING_TABLE: list[tuple[str, PriceEntry]] = [
    # Offline fallback for Squilla Router tier models.
    ("anthropic/claude-opus-4.8", PriceEntry(5.0, 25.0)),
    ("anthropic/claude-sonnet-4.6", PriceEntry(3.0, 15.0)),
    ("google/gemini-3.5-flash", PriceEntry(1.5, 9.0)),
    ("openai/gpt-5.4-mini", PriceEntry(0.75, 4.5)),
    ("openai/gpt-5.5", PriceEntry(5.0, 30.0)),
    ("qwen/qwen3-coder-plus", PriceEntry(0.65, 3.25)),
    ("x-ai/grok-4.3", PriceEntry(1.25, 2.5)),
    ("z-ai/glm-4.6", PriceEntry(0.43, 1.74)),
    ("stepfun/step-3.5-flash", PriceEntry(0.10, 0.30)),
    ("z-ai/glm-4.5-air", PriceEntry(0.13, 0.85)),
    ("minimax/minimax-m2.5", PriceEntry(0.118, 0.99)),
    ("deepseek/deepseek-v4-flash", PriceEntry(0.14, 0.28)),
    ("deepseek/deepseek-v4-pro", PriceEntry(1.74, 3.48)),
    ("deepseek/deepseek-v3.2", PriceEntry(0.26, 0.38)),
    ("z-ai/glm-5.2", PriceEntry(1.40, 4.40)),
    ("z-ai/glm-5.1", PriceEntry(1.40, 4.40)),
    ("z-ai/glm-5", PriceEntry(0.72, 2.30)),
    ("moonshotai/kimi-k2.6", PriceEntry(0.95, 4.0)),
    ("moonshotai/kimi-k2.5", PriceEntry(0.3827, 1.72)),
    # Direct provider smoke estimates.
    ("gpt-4.1", PriceEntry(2.0, 8.0)),
    # Zhipu docs quote GLM-4.5 series API prices in CNY; converted to USD at
    # roughly 6.975 CNY/USD for OpenSquilla estimates only.
    ("glm-4.5", PriceEntry(0.115, 0.287)),
    ("kimi-k2.6", PriceEntry(0.95, 4.0)),
    ("minimax-m2.7", PriceEntry(0.118, 0.99)),
    # Direct provider profile estimates.
    # OpenAI-compatible Chat Completions returns token usage, not billed cost.
    # These values prevent profile defaults from falling through to generic
    # fallback pricing and must be reported as OpenSquilla estimates.
    ("gpt-5.4-nano", PriceEntry(0.20, 1.25)),
    ("gpt-5.4-mini", PriceEntry(0.75, 4.50)),
    ("gpt-5.5", PriceEntry(5.0, 30.0)),
    ("glm-5.1", PriceEntry(1.40, 4.40)),
    ("glm-5", PriceEntry(0.72, 2.30)),
    ("kimi-k2.5", PriceEntry(0.3827, 1.72)),
    ("deepseek-v4-flash", PriceEntry(0.14, 0.28)),
    ("deepseek-v4-pro", PriceEntry(1.74, 3.48)),
    ("gemini-2.5-flash-lite", PriceEntry(0.10, 0.40)),
    ("gemini-2.5-flash", PriceEntry(0.15, 0.60)),
    ("gemini-2.5-pro", PriceEntry(1.25, 10.0)),
    ("qwen3.6-flash", PriceEntry(0.029, 0.287)),
    ("qwen3.6-plus", PriceEntry(0.115, 0.688)),
    ("qwen3-max", PriceEntry(0.359, 1.434)),
    ("doubao-seed-1-6-flash", PriceEntry(0.15, 0.60)),
    ("doubao-seed-1-6-thinking", PriceEntry(0.60, 2.40)),
    ("doubao-seed-1-6", PriceEntry(0.30, 1.20)),
    # Volcengine Ark online inference Seed 2.0 estimates for <=32k input tier,
    # converted from CNY per 1M tokens to USD at roughly 6.975 CNY/USD.
    ("doubao-seed-2-0-mini-260215", PriceEntry(0.029, 0.287)),
    ("doubao-seed-2-0-lite-260215", PriceEntry(0.086, 0.516)),
    ("doubao-seed-2-0-pro-260215", PriceEntry(0.459, 2.294)),
    ("doubao-seed-2-0-code-preview-260215", PriceEntry(0.459, 2.294)),
    # DeepSeek.
    ("deepseek/deepseek-r1", PriceEntry(0.70, 2.50)),
    ("deepseek/deepseek-v3", PriceEntry(0.26, 0.38)),
    ("deepseek/deepseek-chat", PriceEntry(0.14, 0.28)),
    # OpenAI (OpenRouter prices).
    ("openai/gpt-4.1-mini", PriceEntry(0.40, 1.60)),
    ("openai/gpt-4.1", PriceEntry(2.0, 8.0)),
    ("openai/gpt-4o-mini", PriceEntry(0.15, 0.60)),
    ("openai/gpt-4o", PriceEntry(2.50, 10.0)),
    ("openai/text-embedding-3-small", PriceEntry(0.02, 0.0)),
    ("openai/text-embedding-3-large", PriceEntry(0.13, 0.0)),
    ("gpt-4o-mini", PriceEntry(0.15, 0.60)),
    ("gpt-4o", PriceEntry(2.50, 10.0)),
    ("text-embedding-3-small", PriceEntry(0.02, 0.0)),
    ("text-embedding-3-large", PriceEntry(0.13, 0.0)),
    ("gpt-4-turbo", PriceEntry(10.0, 30.0)),
    ("gpt-4-", PriceEntry(30.0, 60.0)),
    ("o3-mini", PriceEntry(1.10, 4.40)),
    ("o1-mini", PriceEntry(3.0, 12.0)),
    ("o1", PriceEntry(15.0, 60.0)),
    # Anthropic Claude.
    ("anthropic/claude-opus-4.8", PriceEntry(5.0, 25.0)),
    ("anthropic/claude-opus-4.5", PriceEntry(5.0, 25.0)),
    ("anthropic/claude-opus-4", PriceEntry(15.0, 75.0)),
    ("anthropic/claude-sonnet-4", PriceEntry(3.0, 15.0)),
    ("anthropic/claude-3-5-sonnet", PriceEntry(3.0, 15.0)),
    ("anthropic/claude-3-5-haiku", PriceEntry(0.80, 4.0)),
    ("anthropic/claude-3-opus", PriceEntry(15.0, 75.0)),
    ("anthropic/claude-3-sonnet", PriceEntry(3.0, 15.0)),
    ("anthropic/claude-3-haiku", PriceEntry(0.25, 1.25)),
    ("claude-opus-4", PriceEntry(15.0, 75.0)),
    ("claude-sonnet-4", PriceEntry(3.0, 15.0)),
    ("claude-3-5-sonnet", PriceEntry(3.0, 15.0)),
    ("claude-3-5-haiku", PriceEntry(0.80, 4.0)),
    ("claude-3-opus", PriceEntry(15.0, 75.0)),
    ("claude-3-sonnet", PriceEntry(3.0, 15.0)),
    ("claude-3-haiku", PriceEntry(0.25, 1.25)),
    # Google Gemini.
    ("google/gemini-2.5-flash", PriceEntry(0.15, 0.60)),
    ("google/gemini-2.5-pro", PriceEntry(1.25, 10.0)),
    ("google/gemini-2.0-flash", PriceEntry(0.10, 0.40)),
    # Alibaba Cloud Model Studio / DashScope, Chinese Mainland (Beijing).
    # OpenAI-compatible Chat Completions returns token usage, not billed cost.
    # These prices are used only for OpenSquilla estimates and must not be
    # reported as provider-billed amounts. Source: Alibaba Cloud Model Studio
    # model pricing, checked 2026-05-03. Prices are USD per 1M tokens.
    ("qwen-plus", PriceEntry(0.115, 0.287)),
    ("qwen-flash", PriceEntry(0.022, 0.216)),
    ("qwen-turbo", PriceEntry(0.044, 0.087)),
    ("qwen-max", PriceEntry(0.345, 1.377)),
    # MiniMax.
    ("minimax/minimax-m2.7", PriceEntry(0.118, 0.99)),
    # Ollama / local (free).
    ("baai/", PriceEntry(0.0, 0.0)),
    ("sentence-transformers/", PriceEntry(0.0, 0.0)),
    ("ollama/", PriceEntry(0.0, 0.0)),
    ("local/", PriceEntry(0.0, 0.0)),
]

_DEFAULT_PRICING = PriceEntry(3.0, 15.0)


def _lookup_static_price(model_id: str) -> PriceEntry:
    override = _lookup_price_override(model_id)
    if override is not None:
        return override
    model_lower = model_id.lower()
    for prefix, entry in _PRICING_TABLE:
        if model_lower.startswith(prefix):
            return entry
    return _DEFAULT_PRICING


def _should_fetch_live_price(model_id: str) -> bool:
    model_lower = model_id.lower().strip()
    if not _live_pricing_enabled():
        return False
    if "/" not in model_lower:
        return False
    if model_lower.startswith(("baai/", "sentence-transformers/", "ollama/", "local/")):
        return False
    return True


def lookup_price(model_id: str) -> PriceEntry:
    """Look up pricing, preferring live OpenRouter endpoint prices.

    Live lookup uses ``prompt``/``completion`` endpoint prices, explicitly not
    cache-read prices. If OpenRouter is unreachable, the static table is only a
    fail-open fallback so cost estimation keeps working offline.
    """
    model_id = str(model_id or "").strip()
    override = _lookup_price_override(model_id)
    if override is not None:
        return override
    if not _should_fetch_live_price(model_id):
        return _lookup_static_price(model_id)

    now = time.monotonic()
    key = model_id.lower()
    with _PRICE_LOCK:
        cached = _LIVE_PRICE_CACHE.get(key)
        fetched_at = _LIVE_PRICE_FETCHED_AT.get(key, 0.0)
        if cached is not None and now - fetched_at <= _CACHE_TTL:
            return cached
        miss_at = _LIVE_PRICE_MISS_AT.get(key, 0.0)
        if miss_at and now - miss_at <= _LIVE_PRICE_MISS_TTL:
            return _lookup_static_price(model_id)

    price = _fetch_live_openrouter_price(model_id)
    with _PRICE_LOCK:
        if price is None:
            _LIVE_PRICE_MISS_AT[key] = time.monotonic()
            return _lookup_static_price(model_id)
        _LIVE_PRICE_CACHE[key] = price
        _LIVE_PRICE_FETCHED_AT[key] = time.monotonic()
        _LIVE_PRICE_MISS_AT.pop(key, None)
        return price
