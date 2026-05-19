"""Provider-owned SquillaRouter tier profile policy."""

from __future__ import annotations

from collections.abc import Mapping

TierConfig = dict[str, object]
RouterTiers = dict[str, TierConfig]

def default_router_tiers() -> RouterTiers:
    """Default model routing config."""
    return {
        "t0": {
            "provider": "openrouter",
            "model": "deepseek/deepseek-v4-flash",
            "description": (
                "S tier: fast DeepSeek V4 Flash route for trivial chat, short rewrites, "
                "extraction, and low-risk simple Q&A"
            ),
            "supports_image": False,
            "thinking_level": "high",
        },
        "t1": {
            "provider": "openrouter",
            "model": "deepseek/deepseek-v4-flash",
            "description": (
                "M tier: default balanced text model for normal agent work, coding assistance, "
                "debugging, and moderate analysis"
            ),
            "supports_image": False,
            "thinking_level": "high",
        },
        "t2": {
            "provider": "openrouter",
            "model": "z-ai/glm-5.1",
            "description": (
                "L tier: stronger text model for multi-step coding, structured reasoning, "
                "larger context synthesis, and harder analysis"
            ),
            "supports_image": False,
            "thinking_level": "high",
        },
        "t3": {
            "provider": "openrouter",
            "model": "anthropic/claude-opus-4.7",
            "description": (
                "XL tier: highest-quality text reasoning model for difficult planning, "
                "deep review, complex debugging, and high-stakes synthesis"
            ),
            "supports_image": False,
            "thinking_level": "high",
        },
        "image_model": {
            "provider": "openrouter",
            "model": "moonshotai/kimi-k2.6",
            "description": (
                "Image model: vision-capable route for user-supplied image attachments, "
                "screenshots, diagrams, and visual question answering"
            ),
            "supports_image": True,
            "image_only": True,
            "thinking_level": "medium",
        },
    }


ROUTER_TIER_PROFILE_IDS: frozenset[str] = frozenset(
    {
        "openrouter",
        "dashscope",
        "deepseek",
        "gemini",
        "volcengine",
        "openai",
        "zhipu",
        "moonshot",
    }
)


def merge_router_tier_dicts(
    defaults: Mapping[str, object],
    overrides: object,
) -> dict[str, object]:
    merged: dict[str, object] = {
        name: dict(value) if isinstance(value, Mapping) else value
        for name, value in defaults.items()
    }
    if not overrides:
        return merged
    if not isinstance(overrides, dict):
        return merged
    for tier_name, override in overrides.items():
        existing = merged.get(tier_name)
        if isinstance(override, Mapping) and isinstance(existing, Mapping):
            tier = dict(existing)
            tier.update(override)
            merged[tier_name] = tier
        else:
            merged[tier_name] = override
    return merged


def router_tier_profile_defaults(profile: str | None) -> RouterTiers:
    normalized = (profile or "openrouter").strip().lower()
    if normalized not in ROUTER_TIER_PROFILE_IDS:
        allowed = ", ".join(sorted(ROUTER_TIER_PROFILE_IDS))
        raise ValueError(
            f"unknown squilla_router.tier_profile {profile!r}; expected one of {allowed}"
        )
    if normalized == "openrouter":
        return default_router_tiers()
    profiles = {
        "openai": {
            "t0": {
                "provider": "openai",
                "model": "gpt-5.4-nano",
                "description": (
                    "OpenAI fast tier: GPT-5.4 Nano for fast, high-throughput simple work."
                ),
                "supports_image": False,
                "thinking_level": "none",
            },
            "t1": {
                "provider": "openai",
                "model": "gpt-5.4-mini",
                "description": "OpenAI balanced tier: GPT-5.4 Mini for normal agent work.",
                "supports_image": False,
                "thinking_level": "low",
            },
            "t2": {
                "provider": "openai",
                "model": "gpt-5.5",
                "description": "OpenAI strong tier: GPT-5.5 for complex text tasks.",
                "supports_image": False,
                "thinking_level": "medium",
            },
            "t3": {
                "provider": "openai",
                "model": "gpt-5.5",
                "description": (
                    "OpenAI highest tier: GPT-5.5 with high reasoning; GPT-5.5 Pro is "
                    "excluded because it is not streaming-compatible."
                ),
                "supports_image": False,
                "thinking_level": "high",
            },
        },
        "dashscope": {
            "t0": {
                "provider": "dashscope",
                "model": "qwen3.6-flash",
                "description": (
                    "DashScope fast tier: Qwen3.6 Flash for simple text tasks; "
                    "pending live smoke."
                ),
                "supports_image": False,
            },
            "t1": {
                "provider": "dashscope",
                "model": "qwen3.6-plus",
                "description": (
                    "DashScope balanced tier: Qwen3.6 Plus for normal agent and "
                    "coding work; pending live smoke."
                ),
                "supports_image": False,
            },
            "t2": {
                "provider": "dashscope",
                "model": "qwen3-max",
                "description": "DashScope strong tier: Qwen3 Max for complex text tasks.",
                "supports_image": False,
            },
            "t3": {
                "provider": "dashscope",
                "model": "qwen3-max",
                "description": (
                    "DashScope highest tier: Qwen3 Max; higher-thinking behavior "
                    "requires future payload support."
                ),
                "supports_image": False,
            },
        },
        "deepseek": {
            "t0": {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "description": (
                    "DeepSeek fast tier: V4 Flash with no router-requested thinking; "
                    "request ID pending live smoke."
                ),
                "supports_image": False,
                "thinking_level": "off",
            },
            "t1": {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "description": (
                    "DeepSeek balanced tier: V4 Flash with thinking enabled; request "
                    "ID pending live smoke."
                ),
                "supports_image": False,
                "thinking_level": "low",
            },
            "t2": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "description": (
                    "DeepSeek strong tier: V4 Pro with thinking enabled; request ID "
                    "pending live smoke."
                ),
                "supports_image": False,
                "thinking_level": "medium",
            },
            "t3": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "description": (
                    "DeepSeek highest tier: same V4 Pro wire behavior until "
                    "effort-level support is added."
                ),
                "supports_image": False,
                "thinking_level": "high",
            },
        },
        "gemini": {
            "t0": {
                "provider": "gemini",
                "model": "gemini-2.5-flash-lite",
                "description": "Gemini fast tier: 2.5 Flash-Lite for low-latency tasks.",
                "supports_image": False,
            },
            "t1": {
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "description": "Gemini balanced tier: 2.5 Flash for normal agent work.",
                "supports_image": False,
                "thinking_level": "low",
            },
            "t2": {
                "provider": "gemini",
                "model": "gemini-2.5-pro",
                "description": "Gemini strong tier: 2.5 Pro for complex coding and reasoning.",
                "supports_image": False,
                "thinking_level": "medium",
            },
            "t3": {
                "provider": "gemini",
                "model": "gemini-2.5-pro",
                "description": (
                    "Gemini highest tier: 2.5 Pro with high thinking; 3.1 preview "
                    "remains opt-in."
                ),
                "supports_image": False,
                "thinking_level": "high",
            },
        },
        "zhipu": {
            "t0": {
                "provider": "zhipu",
                "model": "glm-4.7-flashx",
                "description": (
                    "Zhipu fast tier: GLM-4.7 FlashX for simple text tasks; live smoke "
                    "may require fallback."
                ),
                "supports_image": False,
            },
            "t1": {
                "provider": "zhipu",
                "model": "glm-5",
                "description": "Zhipu balanced tier: GLM-5 for normal agent work.",
                "supports_image": False,
                "thinking_level": "low",
            },
            "t2": {
                "provider": "zhipu",
                "model": "glm-5.1",
                "description": "Zhipu strong tier: GLM-5.1 for complex text tasks.",
                "supports_image": False,
                "thinking_level": "medium",
            },
            "t3": {
                "provider": "zhipu",
                "model": "glm-5.1",
                "description": "Zhipu highest tier: GLM-5.1 with high reasoning effort.",
                "supports_image": False,
                "thinking_level": "high",
            },
        },
        "moonshot": {
            "t0": {
                "provider": "moonshot",
                "model": "kimi-k2.5",
                "description": (
                    "Moonshot fast tier: Kimi K2.5 for cost-efficient agent work "
                    "with 256K context."
                ),
                "supports_image": True,
                "thinking_level": "low",
            },
            "t1": {
                "provider": "moonshot",
                "model": "kimi-k2.5",
                "description": (
                    "Moonshot balanced tier: Kimi K2.5 for normal multimodal "
                    "agent work."
                ),
                "supports_image": True,
                "thinking_level": "medium",
            },
            "t2": {
                "provider": "moonshot",
                "model": "kimi-k2.6",
                "description": (
                    "Moonshot strong tier: Kimi K2.6 for complex coding, reasoning, "
                    "and multimodal tasks."
                ),
                "supports_image": True,
                "thinking_level": "medium",
            },
            "t3": {
                "provider": "moonshot",
                "model": "kimi-k2.6",
                "description": (
                    "Moonshot highest tier: Kimi K2.6 for the hardest long-horizon "
                    "agent work."
                ),
                "supports_image": True,
                "thinking_level": "high",
            },
        },
        "volcengine": {
            "t0": {
                "provider": "volcengine",
                "model": "doubao-seed-2-0-mini-260215",
                "description": (
                    "Volcengine fast tier: Doubao Seed 2.0 Mini for low-latency, "
                    "low-cost simple text tasks."
                ),
                "supports_image": False,
                "thinking_level": "off",
            },
            "t1": {
                "provider": "volcengine",
                "model": "doubao-seed-2-0-lite-260215",
                "description": (
                    "Volcengine balanced tier: Doubao Seed 2.0 Lite for daily agent "
                    "work with lower cost than Pro."
                ),
                "supports_image": False,
                "thinking_level": "low",
            },
            "t2": {
                "provider": "volcengine",
                "model": "doubao-seed-2-0-pro-260215",
                "description": (
                    "Volcengine strong tier: Doubao Seed 2.0 Pro for complex "
                    "reasoning and multimodal-capable text work."
                ),
                "supports_image": False,
                "thinking_level": "medium",
            },
            "t3": {
                "provider": "volcengine",
                "model": "doubao-seed-2-0-code-preview-260215",
                "description": (
                    "Volcengine highest tier: Doubao Seed 2.0 Code Preview for the "
                    "hardest coding and code-review routes."
                ),
                "supports_image": False,
                "thinking_level": "high",
            },
        },
    }
    return {name: dict(value) for name, value in profiles[normalized].items()}



def router_profile_ids() -> frozenset[str]:
    """Return supported router tier profile IDs."""

    return ROUTER_TIER_PROFILE_IDS
