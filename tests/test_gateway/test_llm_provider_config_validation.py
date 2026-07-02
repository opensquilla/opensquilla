"""A misconfigured llm.provider degrades boot gracefully instead of crashing.

Unset/unknown provider ids are first-class readiness states (MISSING/UNKNOWN
in section status) — the gateway must still boot so the control UI can be
used to fix the config. resolve_llm_runtime_config therefore skips
spec-derived resolution rather than raising UnknownProviderError.
"""

from __future__ import annotations

from opensquilla.gateway.config import GatewayConfig, LlmProviderConfig
from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config


def test_unknown_provider_resolves_degraded_instead_of_raising() -> None:
    cfg = GatewayConfig()
    cfg.llm = LlmProviderConfig(
        provider="openrouterr",  # typo'd id — previously crashed boot here
        model="m",
        api_key="k",
        base_url="",
    )
    runtime = resolve_llm_runtime_config(cfg)
    assert runtime.provider == "openrouterr"
    assert runtime.api_key == "k"
    assert runtime.base_url == ""  # no spec default to fall back to


def test_unset_provider_resolves_degraded_instead_of_raising(monkeypatch) -> None:
    monkeypatch.delenv("OPENSQUILLA_LLM_PROXY", raising=False)
    cfg = GatewayConfig()
    cfg.llm = LlmProviderConfig(provider="", model="", api_key="", base_url="")
    runtime = resolve_llm_runtime_config(cfg)
    assert runtime.provider == ""
    assert runtime.api_key == ""


def test_known_provider_still_resolves_spec_defaults(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    cfg = GatewayConfig()
    cfg.llm = LlmProviderConfig(provider="deepseek", model="deepseek-chat", api_key="", base_url="")
    runtime = resolve_llm_runtime_config(cfg)
    assert runtime.api_key == "env-key"
    assert runtime.base_url == "https://api.deepseek.com"
