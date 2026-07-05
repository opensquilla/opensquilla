"""ModelCatalog — in-memory cache of model metadata fetched from provider API."""

from __future__ import annotations

import fnmatch
import tomllib
from collections.abc import Mapping
from functools import cache
from importlib import resources
from typing import Any

import httpx
import structlog

from opensquilla.env import trust_env as _trust_env
from opensquilla.secrets import clean_header_secret

from .catalog_types import CatalogSource, ModelCatalogEntry, coerce_entry_field
from .models_dev import lookup_limits as _models_dev_limits
from .models_dev import lookup_model as _models_dev_model
from .ollama import _OLLAMA_DEFAULT_NUM_CTX
from .openrouter_attribution import openrouter_app_headers
from .registry import UnknownProviderError, get_provider_spec
from .types import ModelCapabilities, ModelInfo

log = structlog.get_logger(__name__)

DEFAULT_MAX_TOKENS = 16384
SAFE_OPENROUTER_DEFAULT_MAX_TOKENS = 8192
DEFAULT_CONTEXT_WINDOW = 200_000

# Local runtimes (Ollama, …) have unqualified model ids that miss the catalog
# and the static table, so the 200k cloud default would make the turn budget
# over-estimate and skip trimming while the runtime silently truncates. Report
# the runtime's own default window so budgeting matches what it actually allows.
_LOCAL_CONTEXT_WINDOW = _OLLAMA_DEFAULT_NUM_CTX
_LOCAL_PROVIDERS = frozenset({"ollama", "lm_studio", "ovms", "vllm", "local"})

# Static fallback for squilla-router tier models + default model.
# Used when the OpenRouter API is unreachable at boot.
# Format: model_id → (max_output_tokens, context_window)
#
# Keys are provider-agnostic basenames (no "vendor/" prefix); a model that
# was previously listed under both spellings is merged to ONE conservative
# (per-dimension min) tuple. Conservative because over-estimating the
# context window causes silent server-side truncation, while
# under-estimating only triggers compaction earlier. Lookups normalize the
# requested id via ``_static_fallback_entry`` so either spelling resolves
# to the same entry. When offline, the live catalog still overrides this.
_STATIC_FALLBACK: dict[str, tuple[int, int]] = {
    "claude-opus-4.8": (128_000, 1_000_000),
    "claude-sonnet-4.6": (128_000, 1_000_000),
    "gemini-3.5-flash": (65_536, 1_048_576),
    "gpt-5.4-nano": (128_000, 400_000),
    "gpt-5.4-mini": (128_000, 400_000),
    "gpt-5.5": (128_000, 1_000_000),
    "qwen3-coder-plus": (65_536, 1_000_000),
    "grok-4.3": (DEFAULT_MAX_TOKENS, 1_000_000),
    "glm-4.5-air": (98_304, 131_072),
    "glm-4.6": (131_072, 202_752),
    "glm-4.7-flashx": (128_000, 200_000),
    "glm-5": (80_000, 80_000),
    "glm-5.1": (128_000, 200_000),
    "glm-5.2": (262_144, 1_048_576),
    "minimax-m2.5": (65_536, 196_608),
    "minimax-m2.7": (8192, 196_608),
    "step-3.5-flash": (16_384, 256_000),
    "deepseek-v4-flash": (16_384, 1_048_576),
    "deepseek-v4-pro": (16_384, 1_048_576),
    "deepseek-v3.2": (16_384, 163_840),
    "moonshot-v1-8k": (8192, 8192),
    "moonshot-v1-32k": (32_768, 32_768),
    "moonshot-v1-128k": (131_072, 131_072),
    "kimi-k2.5": (32_768, 262_144),
    "kimi-k2.6": (32_768, 262_144),
}


def _static_fallback_entry(model_id: str) -> tuple[int, int] | None:
    """Return the static ``(max_output, context_window)`` for a model.

    Tries the id verbatim, then the basename after the final ``/`` so the
    same physical model resolves identically whether referenced as a bare
    id (``glm-5``) or a provider-qualified id (``z-ai/glm-5``).
    """
    entry = _STATIC_FALLBACK.get(model_id)
    if entry is not None:
        return entry
    if "/" in model_id:
        return _STATIC_FALLBACK.get(model_id.rsplit("/", 1)[-1])
    return None


def _price_per_1k(value: object) -> float:
    """Convert an OpenRouter per-token price string to a per-1k-token float.

    OpenRouter reports prices as per-token USD strings; downstream cost
    accounting expects per-1k-token floats. Missing or non-numeric values
    fall back to 0.0 (free / unknown).
    """
    try:
        return float(value) * 1000.0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Layered resolution (resolve_entry) — user > live > corrections > snapshot >
# synthesized. Each layer adapter returns a dict of only the fields it
# GENUINELY KNOWS for a model; merging is per field, so a lower layer fills
# only fields every higher layer left unset (see catalog_types.py for the
# per-type "unset" sentinels). The legacy get_capabilities /
# resolve_max_tokens / resolve_context_window paths are intentionally NOT
# routed through this yet.
# ---------------------------------------------------------------------------

# Synthesized floor applied after all layers: conservative budgets for
# models nothing knows, so resolution never fails.
_SYNTHESIZED_DEFAULTS: dict[str, Any] = {
    "context_window": 32_768,
    "max_output_tokens": 8_192,
    "supports_tools": True,
    "supports_reasoning": False,
}


def _normalize_corrections(payload: Mapping[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Normalize a parsed catalog_overrides.toml payload.

    Provider and model keys are lowercased; field values are validated and
    coerced via ``coerce_entry_field``. Bad rows or fields are logged and
    dropped — packaged corrections degrade, they never crash resolution.
    """
    tables: dict[str, dict[str, dict[str, Any]]] = {}
    for provider_key, models in payload.items():
        if not isinstance(models, Mapping):
            log.warning("model_catalog.corrections_bad_provider", provider=str(provider_key))
            continue
        table: dict[str, dict[str, Any]] = {}
        for model_key, fields in models.items():
            if not isinstance(fields, Mapping):
                log.warning(
                    "model_catalog.corrections_bad_entry",
                    provider=str(provider_key),
                    model=str(model_key),
                )
                continue
            entry: dict[str, Any] = {}
            for name, value in fields.items():
                try:
                    entry[str(name)] = coerce_entry_field(str(name), value)
                except ValueError as exc:
                    log.warning(
                        "model_catalog.corrections_bad_field",
                        provider=str(provider_key),
                        model=str(model_key),
                        error=str(exc),
                    )
            if entry:
                table[str(model_key).strip().lower()] = entry
        if table:
            tables[str(provider_key).strip().lower()] = table
    return tables


@cache
def _corrections_tables() -> dict[str, dict[str, dict[str, Any]]]:
    """Lazily load the packaged corrections file (catalog_overrides.toml)."""
    try:
        path = resources.files("opensquilla.provider").joinpath("catalog_overrides.toml")
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a missing/corrupt file degrades, never crashes
        log.warning("model_catalog.corrections_unavailable")
        return {}
    return _normalize_corrections(payload)


def _live_layer_fields(info: ModelInfo | None) -> dict[str, Any]:
    """Fields the live provider catalog knows, adapted per-1k → per-Mtok.

    Capability booleans are computed deterministically from the provider
    response at populate time, so they are emitted as known whenever the
    model is in the cache. A 0.0 per-1k price is the live cache's "free or
    unknown" sentinel, so costs are emitted only when positive — this layer
    never claims a known $0 price.
    """
    if info is None:
        return {}
    fields: dict[str, Any] = {
        "supports_reasoning": info.supports_reasoning,
        "supports_tools": info.supports_tools,
        "supports_vision": info.supports_vision,
    }
    if info.display_name:
        fields["display_name"] = info.display_name
    if info.context_window > 0:
        fields["context_window"] = info.context_window
    if info.max_output_tokens > 0:
        fields["max_output_tokens"] = info.max_output_tokens
    if info.supports_reasoning:
        # The live cache is the OpenRouter catalog; its reasoning models
        # stream through the OpenRouter dialect (matches get_capabilities).
        fields["reasoning_format"] = "openrouter"
    if info.input_cost_per_1k > 0:
        fields["input_cost_per_mtok"] = info.input_cost_per_1k * 1000.0
    if info.output_cost_per_1k > 0:
        fields["output_cost_per_mtok"] = info.output_cost_per_1k * 1000.0
    return fields


def _corrections_layer_fields(provider_id: str, model_id: str) -> dict[str, Any]:
    """Fields from the packaged corrections table for ``(provider, model)``.

    The exact (lowercased) model key is consulted first; every other key in
    the provider table is then tried as an fnmatch glob against the
    lowercased model id, in file order, each filling only fields still
    unset within this layer. No provider → no corrections.
    """
    if not provider_id:
        return {}
    table = _corrections_tables().get(provider_id)
    if not table:
        return {}
    model_l = model_id.strip().lower()
    fields: dict[str, Any] = {}
    exact = table.get(model_l)
    if exact:
        fields.update(exact)
    for pattern, entry in table.items():
        if pattern == model_l:
            continue
        if fnmatch.fnmatchcase(model_l, pattern):
            for name, value in entry.items():
                fields.setdefault(name, value)
    return fields


def _snapshot_layer_fields(provider_id: str, model_id: str) -> dict[str, Any]:
    """Fields from the vendored models.dev snapshot.

    The snapshot carries ``supports_reasoning`` as data but never a
    ``reasoning_format`` — the streaming dialect is provider knowledge the
    snapshot does not have.
    """
    entry = _models_dev_model(provider_id, model_id)
    if entry is None:
        return {}
    fields: dict[str, Any] = {}
    context_window = int(entry.get("ctx") or 0)
    max_output = int(entry.get("out") or 0)
    if context_window > 0:
        fields["context_window"] = context_window
    if max_output > 0:
        fields["max_output_tokens"] = max_output
    for snapshot_key, field_name in (
        ("reasoning", "supports_reasoning"),
        ("tools", "supports_tools"),
        ("vision", "supports_vision"),
    ):
        if snapshot_key in entry:
            fields[field_name] = bool(entry[snapshot_key])
    return fields


class ModelCatalog:
    """In-memory cache of model metadata fetched from provider API.

    Priority chain for max_tokens:
      1. User config override (>0)
      2. API-fetched catalog value
      3. Static fallback table
      4. DEFAULT_MAX_TOKENS (16384)
      → then clamp to min(value, context_window)
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelInfo] = {}
        # User-override layer for resolve_entry; keys are lowercased
        # "provider/model" or bare model ids (see set_user_overrides).
        self._user_overrides: dict[str, dict[str, Any]] = {}

    def __len__(self) -> int:
        return len(self._models)

    def _populate_from_data(self, models: list[dict]) -> None:
        """Parse a list of OpenRouter model dicts into ModelInfo entries."""
        for m in models:
            model_id = m.get("id", "")
            if not model_id:
                continue
            top_provider = m.get("top_provider") or {}
            max_completion = top_provider.get("max_completion_tokens") or 0
            supported = set(m.get("supported_parameters", []))
            architecture = m.get("architecture") or {}
            input_modalities = {
                str(item).lower() for item in architecture.get("input_modalities", [])
            }
            pricing = m.get("pricing") or {}
            self._models[model_id] = ModelInfo(
                provider="openrouter",
                model_id=model_id,
                display_name=m.get("name", model_id),
                context_window=m.get("context_length", 0),
                max_output_tokens=max_completion,
                supports_reasoning="reasoning" in supported or "reasoning_effort" in supported,
                supports_tools="tools" in supported or "tool_choice" in supported,
                supports_vision="image" in input_modalities,
                input_cost_per_1k=_price_per_1k(pricing.get("prompt")),
                output_cost_per_1k=_price_per_1k(pricing.get("completion")),
            )

    def get_capabilities(
        self,
        model_id: str,
        provider_name: str = "openrouter",
        base_url: str = "",
    ) -> ModelCapabilities:
        """Resolve ModelCapabilities for a model based on provider and catalog data."""
        if provider_name == "anthropic":
            return ModelCapabilities()
        if provider_name == "ollama":
            return ModelCapabilities()
        provider_id = provider_name.strip().lower()
        try:
            provider_spec = get_provider_spec(provider_id)
        except UnknownProviderError:
            provider_spec = None

        if provider_name == "openai" and "deepseek" in base_url.lower():
            return ModelCapabilities(
                supports_reasoning=True, supports_tools=True, reasoning_format="deepseek"
            )
        info = self._models.get(model_id)
        if info and info.supports_reasoning:
            return ModelCapabilities(
                supports_reasoning=True,
                supports_tools=info.supports_tools,
                supports_vision=info.supports_vision,
                reasoning_format="openrouter",
            )
        model_l = model_id.strip().lower()
        if (
            provider_name == "openai"
            and "api.openai.com" in base_url.lower()
            and model_l.startswith(("gpt-5", "o1", "o3", "o4"))
        ):
            return ModelCapabilities(
                supports_reasoning=True,
                supports_tools=True,
                reasoning_format="openai",
            )
        if provider_spec and provider_spec.reasoning_shape == "deepseek":
            return ModelCapabilities(
                supports_reasoning=True,
                supports_tools=True,
                reasoning_format="deepseek",
            )
        if provider_spec and provider_spec.reasoning_shape == "gemini":
            supports_reasoning = model_l.startswith("gemini-2.5")
            return ModelCapabilities(
                supports_reasoning=supports_reasoning,
                supports_tools=True,
                supports_vision=True,
                reasoning_format="gemini" if supports_reasoning else "none",
            )
        if provider_spec and provider_spec.reasoning_shape == "zai":
            supports_reasoning = model_l.startswith(("glm-4.5", "glm-4.7", "glm-5"))
            return ModelCapabilities(
                supports_reasoning=supports_reasoning,
                supports_tools=True,
                reasoning_format="zai" if supports_reasoning else "none",
            )
        if provider_id == "dashscope":
            supports_reasoning = model_l.startswith(
                (
                    "qwen3",
                    "qwen-plus",
                    "qwen-flash",
                    "qwen-turbo",
                    "qwen-max",
                    "qwq",
                )
            )
            return ModelCapabilities(
                supports_reasoning=supports_reasoning,
                supports_tools=True,
                supports_vision=model_l.startswith(("qwen3.5", "qwen3.6", "qwen-vl")),
                reasoning_format="dashscope" if supports_reasoning else "none",
            )
        if provider_id == "moonshot":
            supports_reasoning = model_l.startswith(
                ("kimi-k2.5", "kimi-k2.6", "kimi-k2-thinking")
            )
            return ModelCapabilities(
                supports_reasoning=supports_reasoning,
                supports_tools=True,
                supports_vision=model_l.startswith(("kimi-k2.5", "kimi-k2.6")),
                reasoning_format="moonshot" if supports_reasoning else "none",
            )
        if provider_id == "volcengine":
            # doubao-seed-1-6 and -1-8 and the seed-2 line are reasoning
            # models; without 1-6 here the stream path emits no thinking
            # toggle, so reasoning leaks into thinking-disabled requests
            # (verified live 2026-07-02 against doubao-seed-1-6-251015).
            supports_reasoning = (
                "thinking" in model_l
                or model_l.startswith("doubao-seed-2")
                or model_l.startswith("doubao-seed-1-8")
                or model_l.startswith("doubao-seed-1-6")
            )
            return ModelCapabilities(
                supports_reasoning=supports_reasoning,
                supports_tools=True,
                supports_vision=model_l.startswith(
                    ("doubao-seed-1-6", "doubao-seed-1-8", "doubao-seed-2")
                ),
                reasoning_format="volcengine" if supports_reasoning else "none",
            )
        if provider_id == "byteplus":
            supports_reasoning = (
                "thinking" in model_l
                or model_l.startswith("seed-2")
                or model_l.startswith("seed-1-8")
                or model_l.startswith("seed-1-6")
                or model_l.startswith(("kimi-k2-", "kimi-k2."))
            )
            return ModelCapabilities(
                supports_reasoning=supports_reasoning,
                supports_tools=True,
                supports_vision=model_l.startswith(
                    ("seed-1-6", "seed-1-8", "seed-2", "kimi-k2-", "kimi-k2.")
                ),
                reasoning_format="volcengine" if supports_reasoning else "none",
            )
        # Unknown to every provider-specific branch: fill tools/vision from
        # the vendored models.dev snapshot when the live catalog has nothing.
        # Reasoning stays off here on purpose — enabling it requires knowing
        # the provider's reasoning *format*, which is dialect knowledge the
        # snapshot does not carry.
        if info is None:
            snapshot_entry = _models_dev_model(provider_id, model_id)
            if snapshot_entry is not None:
                return ModelCapabilities(
                    supports_tools=bool(snapshot_entry.get("tools", True)),
                    supports_vision=bool(snapshot_entry.get("vision", False)),
                )
        return ModelCapabilities(
            supports_tools=info.supports_tools if info else True,
            supports_vision=info.supports_vision if info else False,
        )

    async def fetch_openrouter(self, api_key: str, base_url: str, proxy: str = "") -> None:
        """Fetch model list from OpenRouter /api/v1/models endpoint.

        ``base_url`` MUST NOT end with ``/v1`` — boot.py strips it.
        URL constructed as: ``f"{base_url}/v1/models"``
        """
        url = f"{base_url}/v1/models"
        headers = {
            "Authorization": f"Bearer {clean_header_secret(api_key, label='OpenRouter API key')}"
        }
        headers.update(openrouter_app_headers(base_url))
        async with httpx.AsyncClient(
            timeout=10.0, trust_env=_trust_env(), proxy=proxy or None
        ) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        self._populate_from_data(data.get("data", []))
        log.debug("model_catalog.fetched", count=len(self._models))

    def get(self, model_id: str) -> ModelInfo | None:
        """Look up model metadata by ID."""
        return self._models.get(model_id)

    def set_user_overrides(self, overrides: Mapping[str, Mapping[str, Any]]) -> None:
        """Replace the user-override layer (highest resolution authority).

        Keys are ``"provider/model"`` or a bare model id and are matched
        case-insensitively. At resolve time the provider-qualified key is
        consulted first; the bare-model key then fills only fields the
        qualified key left unset. Values map ``ModelCatalogEntry`` data-field
        names to values. Unknown field names or type-incompatible values are
        REJECTED with ``ValueError`` (fail fast at configuration time); on
        rejection the previously installed overrides remain in effect.
        """
        validated: dict[str, dict[str, Any]] = {}
        for key, fields in overrides.items():
            entry: dict[str, Any] = {}
            for name, value in fields.items():
                try:
                    entry[str(name)] = coerce_entry_field(str(name), value)
                except ValueError as exc:
                    raise ValueError(
                        f"invalid model catalog override for {key!r}: {exc}"
                    ) from exc
            validated[str(key).strip().lower()] = entry
        self._user_overrides = validated

    def _user_override_fields(self, model_id: str, provider_id: str) -> dict[str, Any]:
        """Fields from the user-override layer for ``(provider, model)``."""
        if not self._user_overrides:
            return {}
        model_l = model_id.strip().lower()
        keys = [f"{provider_id}/{model_l}"] if provider_id else []
        keys.append(model_l)
        fields: dict[str, Any] = {}
        for key in keys:
            entry = self._user_overrides.get(key)
            if entry:
                for name, value in entry.items():
                    fields.setdefault(name, value)
        return fields

    def resolve_entry(self, model: str, *, provider: str = "") -> ModelCatalogEntry:
        """Resolve one typed catalog entry through the layered sources.

        Authority order, merged per FIELD — a lower layer fills only fields
        every higher layer left unset:

        1. user overrides (``set_user_overrides``)
        2. live provider catalog (per-1k costs adapted to per-Mtok)
        3. packaged corrections (``catalog_overrides.toml``, exact then glob)
        4. models.dev snapshot
        5. synthesized fallback — never fails: unknown models yield a
           conservative entry (32k context / 8k output, tools on,
           reasoning off) with ``source="synthesized"``.

        ``source`` names the highest-authority layer that contributed at
        least one field. This is a parallel substrate: the legacy
        ``get_capabilities`` / ``resolve_max_tokens`` /
        ``resolve_context_window`` paths do not route through it yet.
        """
        provider_id = (provider or "").strip().lower()
        model_id = (model or "").strip()
        layers: tuple[tuple[CatalogSource, dict[str, Any]], ...] = (
            ("user", self._user_override_fields(model_id, provider_id)),
            ("live", _live_layer_fields(self._models.get(model_id))),
            ("corrections", _corrections_layer_fields(provider_id, model_id)),
            ("snapshot", _snapshot_layer_fields(provider_id, model_id)),
        )
        merged: dict[str, Any] = {}
        source: CatalogSource = "synthesized"
        for layer_source, fields in layers:
            for name, value in fields.items():
                if name not in merged:
                    merged[name] = value
                    if source == "synthesized":
                        source = layer_source
        for name, value in _SYNTHESIZED_DEFAULTS.items():
            merged.setdefault(name, value)
        return ModelCatalogEntry(
            provider_id=provider_id, model_id=model_id, source=source, **merged
        )

    def resolve_max_tokens(
        self, model_id: str, user_override: int = 0, provider: str = ""
    ) -> int:
        """Resolve max_tokens: user > catalog > static fallback > default, then clamp."""
        context_window = self.resolve_context_window(model_id, provider)
        info = self._models.get(model_id)

        using_user_override = user_override > 0
        snapshot_limits = _models_dev_limits(provider, model_id)
        if using_user_override:
            effective = user_override
        elif info and info.max_output_tokens > 0:
            effective = info.max_output_tokens
        elif snapshot_limits is not None and snapshot_limits[0] > 0:
            effective = snapshot_limits[0]
        elif (static := _static_fallback_entry(model_id)) is not None:
            effective = static[0]
        else:
            effective = DEFAULT_MAX_TOKENS

        # Clamp to context window. Some provider catalogs report a model's
        # max_completion_tokens as almost the entire context window; using that
        # value as max_tokens leaves no room for ordinary prompt/tool/image input
        # and causes preventable context-limit failures.
        if context_window > 0:
            effective = min(effective, context_window)
            if (
                not using_user_override
                and context_window > DEFAULT_MAX_TOKENS
                and effective >= context_window - DEFAULT_MAX_TOKENS
            ):
                effective = min(effective, SAFE_OPENROUTER_DEFAULT_MAX_TOKENS)

        return effective

    def resolve_context_window(self, model_id: str, provider: str = "") -> int:
        """Resolve context window: catalog > models.dev > static fallback > local/default."""
        info = self._models.get(model_id)
        if info and info.context_window > 0:
            return info.context_window
        snapshot_limits = _models_dev_limits(provider, model_id)
        if snapshot_limits is not None and snapshot_limits[1] > 0:
            return snapshot_limits[1]
        static = _static_fallback_entry(model_id)
        if static is not None:
            return static[1]
        if provider and provider.strip().lower() in _LOCAL_PROVIDERS:
            return _LOCAL_CONTEXT_WINDOW
        return DEFAULT_CONTEXT_WINDOW
