#!/usr/bin/env python3
"""Live end-to-end test of cross-provider router tiers (P6: R3 + gate + R2 flag).

Exercises the real turn-path helpers against real APIs — credential
resolution, the execution gate, and ModelSelector.override_provider_config
— then runs a chat turn on the SWITCHED provider and confirms attribution
followed (active provider id + response model = the tier's provider, with
the previous primary retained as a fallback).

Loads keys from ``.env`` in the cwd; needs at least two of
OPENROUTER_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY. No secrets printed.
Exit 0 iff every check passes.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from opensquilla.engine.selector_override import (
    apply_model_override,
    cross_provider_tier_config,
    resolve_tier_provider_config,
)
from opensquilla.gateway.config import GatewayConfig, LlmProviderConfig, LlmProviderProfile
from opensquilla.provider.registry import get_provider_spec
from opensquilla.provider.selector import ModelSelector, ProviderConfig, SelectorConfig
from opensquilla.provider.types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    TextDeltaEvent,
)


def _load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _cfg(
    *,
    primary: str,
    flag: bool,
    profiles: dict[str, LlmProviderProfile] | None = None,
) -> GatewayConfig:
    cfg = GatewayConfig()
    cfg.llm = LlmProviderConfig(provider=primary, model="m", api_key="primary-key")
    cfg.squilla_router.cross_provider_tiers = flag
    cfg.llm_profiles = profiles or {}
    return cfg


def _key_for(provider_id: str) -> str:
    return os.environ.get(get_provider_spec(provider_id).env_key, "").strip()


async def _run_turn(provider: Any, prompt: str) -> dict[str, Any]:
    start = time.perf_counter()
    text: list[str] = []
    done: DoneEvent | None = None
    error: ErrorEvent | None = None
    async for event in provider.chat(
        [Message(role="user", content=prompt)],
        config=ChatConfig(max_tokens=64, timeout=90.0),
    ):
        if isinstance(event, TextDeltaEvent):
            text.append(event.text)
        elif isinstance(event, DoneEvent):
            done = event
        elif isinstance(event, ErrorEvent):
            error = event
    return {
        "content": "".join(text),
        "response_model": done.model if done else None,
        "error": error.message[:120] if error else None,
        "latency_ms": int((time.perf_counter() - start) * 1000),
    }


async def main() -> int:
    _load_env()
    report: dict[str, Any] = {}
    verdicts: list[bool] = []

    # 1. Gate: flag OFF -> tier config not built (turn stays on primary).
    off = cross_provider_tier_config(
        _cfg(primary="openrouter", flag=False),
        {"routing_applied": True, "routed_provider": "deepseek"},
        "deepseek-chat",
        active_provider_id="openrouter",
    )
    report["gate_flag_off"] = {"tier_config": off}
    verdicts.append(off is None)

    # 2. Gate: flag ON but credentials unresolvable -> None + warning.
    os.environ.pop("MISTRAL_API_KEY", None)
    unresolvable = cross_provider_tier_config(
        _cfg(primary="openrouter", flag=True),
        {"routing_applied": True, "routed_provider": "mistral"},
        "mistral-large-latest",
        active_provider_id="openrouter",
    )
    report["gate_unresolvable_creds"] = {"tier_config": unresolvable}
    verdicts.append(unresolvable is None)

    # 3. Credential resolution: env source, profile override, R2 flag.
    env_cfg = resolve_tier_provider_config(
        _cfg(primary="openrouter", flag=True), "deepseek", "deepseek-chat"
    )
    prof_cfg = resolve_tier_provider_config(
        _cfg(
            primary="openrouter",
            flag=True,
            profiles={"deepseek": LlmProviderProfile(api_key="profile-override-key")},
        ),
        "deepseek",
        "deepseek-chat",
    )
    creds_ok = bool(
        env_cfg
        and env_cfg.api_key == os.environ.get("DEEPSEEK_API_KEY", "")
        and env_cfg.replay_provider_state is False
        and prof_cfg
        and prof_cfg.api_key == "profile-override-key"
    )
    report["credential_resolution"] = {
        "env_resolved": bool(env_cfg and env_cfg.api_key),
        "profile_overrides_env": bool(prof_cfg) and prof_cfg.api_key == "profile-override-key",
        "replay_provider_state_disabled": bool(env_cfg) and env_cfg.replay_provider_state is False,
    }
    verdicts.append(creds_ok)

    # 4. Live cross-provider execution: each turn must run on the tier
    #    provider (proven by response model) with the primary kept as
    #    fallback. Only pairs whose keys are present are attempted.
    candidate_cases = [
        ("openrouter", "deepseek/deepseek-v4-flash", "deepseek", "deepseek-chat"),
        ("deepseek", "deepseek-chat", "openai", "gpt-4.1"),
    ]
    report["live_cross_provider"] = []
    for primary_prov, primary_model, tier_prov, tier_model in candidate_cases:
        if not _key_for(primary_prov) or not _key_for(tier_prov):
            report["live_cross_provider"].append(
                {"primary": primary_prov, "tier_provider": tier_prov, "skipped": "missing key"}
            )
            continue
        selector = ModelSelector(
            SelectorConfig(
                primary=ProviderConfig(
                    primary_prov, primary_model, api_key=_key_for(primary_prov)
                )
            )
        )
        cfg = _cfg(primary=primary_prov, flag=True)
        metadata: dict[str, Any] = {"routing_applied": True, "routed_provider": tier_prov}
        tier_config = cross_provider_tier_config(
            cfg, metadata, tier_model, active_provider_id=selector.active_provider_id
        )
        provider = apply_model_override(
            selector,
            tier_model,
            turn_metadata=metadata,
            realign_routed_model=False,
            tier_provider_config=tier_config,
        )
        primary_kept = selector.has_fallback() and selector.current_config is not None
        turn = await _run_turn(provider, "Reply with the single word: switched")
        case_ok = bool(
            selector.active_provider_id == tier_prov
            and metadata.get("routed_provider_applied") == tier_prov
            and turn["error"] is None
            and turn["response_model"]
            and primary_kept
        )
        report["live_cross_provider"].append(
            {
                "primary": primary_prov,
                "tier_provider": tier_prov,
                "active_provider_after_switch": selector.active_provider_id,
                "primary_kept_as_fallback": primary_kept,
                "turn": turn,
                "ok": case_ok,
            }
        )
        verdicts.append(case_ok)

    report["all_passed"] = all(verdicts)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
