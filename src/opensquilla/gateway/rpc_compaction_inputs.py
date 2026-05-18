"""Gateway RPC compaction input helpers."""

from __future__ import annotations

from typing import Any

from opensquilla.session.compaction import (
    CompactionConfig,
    build_compaction_config_from_provider,
)


def context_window_tokens(params: dict | None, ctx: Any) -> int:
    raw: Any = None
    if isinstance(params, dict):
        raw = params.get("contextWindowTokens", params.get("context_window_tokens"))
    if raw is None:
        raw = getattr(ctx.config, "context_budget_tokens", 100_000)
    if isinstance(raw, bool):
        raise ValueError("contextWindowTokens must be a positive integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("contextWindowTokens must be a positive integer") from exc
    if value <= 0:
        raise ValueError("contextWindowTokens must be a positive integer")
    return value


def effective_compaction_model(session: object | None) -> str | None:
    if session is None:
        return None
    return getattr(session, "model_override", None) or getattr(session, "model", None)


def resolve_compaction_provider(ctx: Any, session: object | None) -> object | None:
    selector = getattr(ctx, "provider_selector", None)
    if selector is None:
        return None

    resolved_selector = selector
    clone = getattr(selector, "clone", None)
    if callable(clone):
        try:
            resolved_selector = clone()
        except Exception:  # noqa: BLE001
            resolved_selector = selector

    model = effective_compaction_model(session)
    if model and resolved_selector is not selector:
        override = getattr(resolved_selector, "override_model", None)
        if callable(override):
            try:
                override(model)
            except Exception:  # noqa: BLE001
                pass

    resolver = getattr(resolved_selector, "resolve", None)
    if not callable(resolver):
        return None
    try:
        resolved: object | None = resolver()
        return resolved
    except Exception:  # noqa: BLE001
        return None


def build_gateway_compaction_config(ctx: Any, session: object | None) -> CompactionConfig:
    return build_compaction_config_from_provider(
        resolve_compaction_provider(ctx, session),
        model_override=effective_compaction_model(session),
        compaction_config=getattr(getattr(ctx, "config", None), "compaction", None),
    )
