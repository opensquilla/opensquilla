"""Factory helpers for constructing Dream runners from gateway config."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from opensquilla.agents.scope import resolve_agent_workspace_dir
from opensquilla.memory.dream import Dream


def _router_model_routing_enabled(router_cfg: Any | None) -> bool:
    if router_cfg is None or not getattr(router_cfg, "enabled", False):
        return False
    return str(getattr(router_cfg, "rollout_phase", "full") or "full") != "observe"


def _dream_provider_target(config: Any) -> tuple[str, str]:
    llm_cfg = getattr(config, "llm", None)
    if llm_cfg is None:
        return "", ""

    router_cfg = getattr(config, "squilla_router", None)
    if _router_model_routing_enabled(router_cfg):
        tiers = getattr(router_cfg, "tiers", {}) or {}
        t1 = tiers.get("t1") if isinstance(tiers, dict) else None
        if not isinstance(t1, dict) or not str(t1.get("model") or "").strip():
            raise RuntimeError("squilla_router.tiers.t1 model is required for Dream")
        provider = str(t1.get("provider") or getattr(llm_cfg, "provider", "openrouter"))
        model = str(t1["model"])
        return provider, model

    return str(getattr(llm_cfg, "provider", "openrouter")), str(getattr(llm_cfg, "model", ""))


def build_dream_provider_selector(config: Any) -> Any | None:
    """Build Dream's own selector from config-derived model policy."""
    llm_cfg = getattr(config, "llm", None)
    if llm_cfg is None:
        return None

    api_key = os.environ.get("OPENROUTER_API_KEY", "") or getattr(llm_cfg, "api_key", "")
    if not api_key:
        return None

    from opensquilla.provider.selector import ModelSelector, ProviderConfig, SelectorConfig

    provider, model = _dream_provider_target(config)
    base_url = os.environ.get("OPENROUTER_BASE_URL", "") or getattr(llm_cfg, "base_url", "")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    proxy = os.environ.get("OPENSQUILLA_LLM_PROXY", "") or getattr(llm_cfg, "proxy", "")

    return ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                proxy=proxy,
                provider_routing=getattr(llm_cfg, "provider_routing", {}),
            )
        )
    )


def _resolve_provider(
    *,
    config: Any,
    need_provider: bool,
) -> Any | None:
    if not need_provider:
        return None

    selector = build_dream_provider_selector(config)
    if selector is None:
        raise RuntimeError("no provider configured for Dream")

    resolve = getattr(selector, "resolve", None)
    if not callable(resolve):
        raise RuntimeError("provider selector cannot resolve a provider")
    return resolve()


def _session_lock_for(turn_runner: Any | None, agent_id: str) -> Any | None:
    if turn_runner is None:
        return None
    get_lock = getattr(turn_runner, "get_session_lock", None)
    if not callable(get_lock):
        get_lock = getattr(turn_runner, "_get_session_lock", None)
    if not callable(get_lock):
        return None
    return get_lock(f"memory_dream:{agent_id}")


def build_dream_factory(
    *,
    config: Any,
    turn_runner: Any | None = None,
    workspace_for_agent: Callable[[str], Path] | None = None,
    need_provider: bool = True,
) -> Callable[[str], Dream]:
    """Return ``build_dream(agent_id)`` wired to gateway/CLI dependencies."""
    dream_cfg = getattr(getattr(config, "memory", None), "dream", None)
    if dream_cfg is None:
        raise RuntimeError("memory.dream config is missing")

    def build_dream(agent_id: str) -> Dream:
        workspace = (
            workspace_for_agent(agent_id)
            if workspace_for_agent is not None
            else resolve_agent_workspace_dir(agent_id, config)
        )
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "memory").mkdir(parents=True, exist_ok=True)
        provider = _resolve_provider(
            config=config,
            need_provider=need_provider,
        )
        return Dream(
            workspace=workspace,
            provider=provider,
            session_lock=_session_lock_for(turn_runner, agent_id),
            config=dream_cfg,
            agent_id=agent_id,
        )

    return build_dream
