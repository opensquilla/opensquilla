"""Unit tests for OpenAI-compatible provider usage extraction.

Covers cache_write_tokens detection across the variants we encounter
in the wild:
- DeepSeek: ``prompt_cache_miss_tokens`` is fresh input already counted in
  ``prompt_tokens`` — not a cache write — so it must be excluded.
- Anthropic-via-OpenRouter passthrough: ``cache_creation_input_tokens``.
- Nested under ``prompt_tokens_details`` (some chat-completion providers).
- Absent: returns 0 cleanly.
"""

from opensquilla.provider.openai import _provider_billed_cost, _usage_fields


def test_usage_fields_returns_zero_when_usage_missing() -> None:
    assert _usage_fields(None) == (0, 0, 0, 0, 0, 0.0)
    assert _usage_fields({}) == (0, 0, 0, 0, 0, 0.0)


def test_deepseek_prompt_cache_miss_tokens_are_not_cache_writes() -> None:
    """DeepSeek's prompt_cache_miss_tokens is fresh input already billed inside
    prompt_tokens at the standard rate — it carries no write premium and must
    not be counted as a cache write."""
    usage = {
        "prompt_tokens": 1500,
        "completion_tokens": 200,
        "prompt_cache_hit_tokens": 1100,
        "prompt_cache_miss_tokens": 400,
    }

    input_t, output_t, reasoning_t, cached_t, cache_write_t, billed_cost = _usage_fields(usage)

    assert input_t == 1500
    assert output_t == 200
    assert reasoning_t == 0
    assert cached_t == 1100
    assert cache_write_t == 0
    assert billed_cost == 0.0


def test_usage_fields_extracts_anthropic_cache_creation_via_openrouter() -> None:
    usage = {
        "prompt_tokens": 2000,
        "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 1500},
        "cache_creation_input_tokens": 456,
        "cost": 0.012,
    }

    _, _, _, cached_t, cache_write_t, billed_cost = _usage_fields(usage)

    assert cached_t == 1500
    assert cache_write_t == 456
    assert billed_cost == 0.012


def test_usage_cost_is_trusted_as_provider_bill_only_for_openrouter() -> None:
    assert _provider_billed_cost("openrouter", 0.012) == (0.012, "provider_billed")
    assert _provider_billed_cost("deepseek", 0.012) == (0.0, "none")
    assert _provider_billed_cost("volcengine", 0.012) == (0.0, "none")


def test_usage_fields_falls_back_to_prompt_details_cache_creation() -> None:
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 10,
        "prompt_tokens_details": {
            "cached_tokens": 50,
            "cache_creation_tokens": 30,
        },
    }

    *_, cache_write_t, _ = _usage_fields(usage)
    assert cache_write_t == 30


def test_usage_fields_cache_creation_takes_precedence_over_miss() -> None:
    """If both keys are present, cache_creation_input_tokens wins.

    This matches OpenRouter's documented behaviour when proxying Anthropic
    models — the cache_creation count is the canonical write number.
    """
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "cache_creation_input_tokens": 200,
        "prompt_cache_miss_tokens": 9999,
    }

    *_, cache_write_t, _ = _usage_fields(usage)
    assert cache_write_t == 200


def test_usage_fields_handles_only_cached_tokens_no_writes() -> None:
    """OpenAI native: only cached_tokens, no write/miss count → cache_write_tokens=0."""
    usage = {
        "prompt_tokens": 500,
        "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 200},
    }

    *_, cached_t, cache_write_t, _ = _usage_fields(usage)
    assert cached_t == 200
    assert cache_write_t == 0


# ---------------------------------------------------------------------------
# Documented OpenRouter / DeepSeek shapes and zero-precedence safety.
# ---------------------------------------------------------------------------


def test_usage_fields_extracts_deepseek_prompt_cache_hit_tokens_for_reads() -> None:
    """DeepSeek native shape exposes reads at top-level prompt_cache_hit_tokens.

    Without this fallback, sessions using DeepSeek directly (not via OpenRouter,
    which already maps them into prompt_tokens_details.cached_tokens) would
    show 0 cache reads even when a hit happened.
    """
    usage = {
        "prompt_tokens": 1500,
        "completion_tokens": 200,
        "prompt_cache_hit_tokens": 1100,
        "prompt_cache_miss_tokens": 400,
    }

    *_, cached_t, cache_write_t, _ = _usage_fields(usage)
    assert cached_t == 1100
    assert cache_write_t == 0


def test_usage_fields_prompt_tokens_details_cached_takes_precedence_over_top_level_hit() -> None:
    """If both shapes are present, the prompt_tokens_details path is canonical."""
    usage = {
        "prompt_tokens": 1500,
        "completion_tokens": 200,
        "prompt_tokens_details": {"cached_tokens": 900},
        "prompt_cache_hit_tokens": 1100,
    }

    *_, cached_t, _, _ = _usage_fields(usage)
    assert cached_t == 900


def test_usage_fields_extracts_openrouter_cache_write_tokens() -> None:
    """OpenRouter usage docs expose prompt_tokens_details.cache_write_tokens."""
    usage = {
        "prompt_tokens": 2000,
        "completion_tokens": 100,
        "prompt_tokens_details": {
            "cached_tokens": 1500,
            "cache_write_tokens": 350,
        },
    }

    *_, cache_write_t, _ = _usage_fields(usage)
    assert cache_write_t == 350


def test_usage_fields_extracts_top_level_cache_write_tokens_alias() -> None:
    """Some proxies expose cache_write_tokens at the top level of usage."""
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 10,
        "cache_write_tokens": 42,
    }

    *_, cache_write_t, _ = _usage_fields(usage)
    assert cache_write_t == 42


def test_usage_fields_canonical_zero_beats_fallback_nonzero() -> None:
    """Zero from a more-canonical key must NOT be replaced by a non-zero fallback.

    Regression for the truthiness-fallback bug: when the upstream explicitly
    says "cache writes = 0 this turn" and a less-canonical legacy field happens
    to carry a stale value, the canonical zero must win.
    """
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "cache_creation_input_tokens": 0,  # canonical, explicit zero
        "prompt_tokens_details": {"cache_write_tokens": 9999},  # fallback — must NOT win here
    }

    *_, cache_write_t, _ = _usage_fields(usage)
    assert cache_write_t == 0


def test_usage_fields_write_priority_orders_prompt_details_over_top_level_alias() -> None:
    """When both OpenRouter's documented prompt_tokens_details.cache_write_tokens
    field and the top-level cache_write_tokens alias are present, the
    prompt_tokens_details field (documented as canonical) wins."""
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "prompt_tokens_details": {
            "cached_tokens": 800,
            "cache_write_tokens": 100,
        },
        "cache_write_tokens": 9999,
    }

    *_, cache_write_t, _ = _usage_fields(usage)
    assert cache_write_t == 100
