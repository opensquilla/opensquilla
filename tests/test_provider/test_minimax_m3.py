"""Tests for the MiniMax provider model catalog additions."""

from __future__ import annotations

from opensquilla.provider.model_catalog import ModelCatalog, _STATIC_FALLBACK


def test_MiniMax_M3_in_static_fallback():
    """The MiniMax M3 model is present in the static fallback table so the
    catalog can resolve max_tokens and context_window when the
    OpenRouter /models endpoint is unreachable at boot."""
    assert "minimax/MiniMax-M3" in _STATIC_FALLBACK
    max_tokens, context_window = _STATIC_FALLBACK["minimax/MiniMax-M3"]
    assert max_tokens > 0
    assert context_window > 0
    assert context_window >= max_tokens, (
        "context_window should be at least as large as max_output_tokens"
    )


def test_MiniMax_M3_resolves_max_tokens_via_catalog():
    cat = ModelCatalog()
    max_tokens = cat.resolve_max_tokens("minimax/MiniMax-M3")
    context_window = cat.resolve_context_window("minimax/MiniMax-M3")
    # Should be clamped to <= context_window.
    assert max_tokens <= context_window
    assert max_tokens > 0
    assert context_window > 0


def test_MiniMax_M3_minimax_provider_reasoning_enabled():
    cat = ModelCatalog()
    # The anthropic-compat provider has reasoning_shape=anthropic but
    # we explicitly opt M-series models into reasoning on the
    # minimax / minimax_openai / minimax_cn / minimax_global providers.
    for provider_id in ("minimax", "minimax_openai", "minimax_cn", "minimax_global"):
        caps = cat.get_capabilities(
            "minimax/MiniMax-M3",
            provider_name=provider_id,
            base_url="https://api.minimaxi.com/anthropic",
        )
        assert caps.supports_reasoning, f"expected reasoning for {provider_id}"
        assert caps.supports_tools


def test_MiniMax_M2_5_still_works_alongside_M3():
    """Adding M3 to the catalog must not regress M2.5 / M2.7 lookups."""
    cat = ModelCatalog()
    for model_id in ("minimax/minimax-m2.5", "minimax/minimax-m2.7", "minimax/MiniMax-M3"):
        info = cat.get(model_id)
        # The static fallback path doesn't populate the catalog dict,
        # but resolve_max_tokens / context_window both work.
        max_tokens = cat.resolve_max_tokens(model_id)
        ctx = cat.resolve_context_window(model_id)
        assert max_tokens > 0
        assert ctx > 0
