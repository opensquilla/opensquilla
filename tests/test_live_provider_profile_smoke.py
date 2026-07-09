from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_smoke_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "live_provider_profile_smoke.py"
    spec = importlib.util.spec_from_file_location("live_provider_profile_smoke", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke_module()


def test_live_smoke_env_maps_cover_openai_zhipu_kimi_and_minimax() -> None:
    assert smoke._MODEL_ENV["openai"] == "OPENAI_MODEL"
    assert smoke._BASE_ENV["openai"] == "OPENAI_BASE_URL"
    assert smoke._DEFAULT_MODELS["openai"] == "gpt-5.4-mini"

    assert smoke._MODEL_ENV["dashscope"] == "DASHSCOPE_MODEL"
    assert smoke._BASE_ENV["dashscope"] == "DASHSCOPE_BASE_URL"
    assert smoke._DEFAULT_MODELS["dashscope"] == "qwen3.7-plus"

    assert smoke._MODEL_ENV["gemini"] == "GEMINI_MODEL"
    assert smoke._BASE_ENV["gemini"] == "GEMINI_BASE_URL"
    assert smoke._DEFAULT_MODELS["gemini"] == "gemini-3.5-flash"

    assert smoke._MODEL_ENV["volcengine"] == "VOLCENGINE_MODEL"
    assert smoke._BASE_ENV["volcengine"] == "VOLCENGINE_BASE_URL"
    assert smoke._DEFAULT_MODELS["volcengine"] == "doubao-seed-2-0-lite-260215"

    assert smoke._MODEL_ENV["volcengine_coding_plan"] == "VOLCENGINE_CODING_MODEL"
    assert smoke._BASE_ENV["volcengine_coding_plan"] == "VOLCENGINE_CODING_BASE_URL"
    assert smoke._DEFAULT_MODELS["volcengine_coding_plan"] == "doubao-seed-2.0-pro"

    assert smoke._MODEL_ENV["zhipu"] == "ZAI_MODEL"
    assert smoke._BASE_ENV["zhipu"] == "ZAI_BASE_URL"
    assert smoke._DEFAULT_MODELS["zhipu"] == "glm-5"

    assert smoke._MODEL_ENV["moonshot"] == "MOONSHOT_MODEL"
    assert smoke._BASE_ENV["moonshot"] == "MOONSHOT_BASE_URL"
    assert smoke._DEFAULT_MODELS["moonshot"] == "kimi-k2.6"

    assert smoke._MODEL_ENV["kimi_coding_openai"] == "KIMI_CODING_MODEL"
    assert smoke._BASE_ENV["kimi_coding_openai"] == "KIMI_CODING_OPENAI_BASE_URL"
    assert smoke._DEFAULT_MODELS["kimi_coding_openai"] == "kimi-for-coding"

    assert smoke._MODEL_ENV["kimi_coding_anthropic"] == "KIMI_CODING_MODEL"
    assert smoke._BASE_ENV["kimi_coding_anthropic"] == "KIMI_CODING_ANTHROPIC_BASE_URL"
    assert smoke._DEFAULT_MODELS["kimi_coding_anthropic"] == "kimi-for-coding"

    assert smoke._MODEL_ENV["byteplus"] == "BYTEPLUS_MODEL"
    assert smoke._BASE_ENV["byteplus"] == "BYTEPLUS_BASE_URL"
    assert smoke._DEFAULT_MODELS["byteplus"] == "seed-2-0-lite-260228"

    assert smoke._MODEL_ENV["minimax"] == "MINIMAX_MODEL"
    assert smoke._BASE_ENV["minimax"] == "MINIMAX_BASE_URL"
    assert smoke._DEFAULT_MODELS["minimax"] == "MiniMax-M2.7"

    assert smoke._MODEL_ENV["minimax_openai"] == "MINIMAX_MODEL"
    assert smoke._BASE_ENV["minimax_openai"] == "MINIMAX_OPENAI_BASE_URL"
    assert smoke._DEFAULT_MODELS["minimax_openai"] == "MiniMax-M2.7"

    assert smoke._MODEL_ENV["minimax_coding_openai"] == "MINIMAX_CODING_MODEL"
    assert smoke._BASE_ENV["minimax_coding_openai"] == "MINIMAX_CODING_OPENAI_BASE_URL"
    assert smoke._DEFAULT_MODELS["minimax_coding_openai"] == "MiniMax-M2.7"

    assert smoke._MODEL_ENV["minimax_coding_anthropic"] == "MINIMAX_CODING_MODEL"
    assert smoke._BASE_ENV["minimax_coding_anthropic"] == "MINIMAX_CODING_ANTHROPIC_BASE_URL"
    assert smoke._DEFAULT_MODELS["minimax_coding_anthropic"] == "MiniMax-M2.7"

    assert smoke._MODEL_ENV["mimo_openai"] == "MIMO_MODEL"
    assert smoke._BASE_ENV["mimo_openai"] == "MIMO_OPENAI_BASE_URL"
    assert smoke._DEFAULT_MODELS["mimo_openai"] == "mimo-v2.5"

    assert smoke._MODEL_ENV["mimo_anthropic"] == "MIMO_MODEL"
    assert smoke._BASE_ENV["mimo_anthropic"] == "MIMO_ANTHROPIC_BASE_URL"
    assert smoke._DEFAULT_MODELS["mimo_anthropic"] == "mimo-v2.5-pro"

    assert smoke._MODEL_ENV["tencent_tokenhub"] == "TENCENT_TOKENHUB_MODEL"
    assert smoke._BASE_ENV["tencent_tokenhub"] == "TENCENT_TOKENHUB_BASE_URL"
    assert smoke._DEFAULT_MODELS["tencent_tokenhub"] == "hy3"

    assert smoke._MODEL_ENV["tencent_tokenhub_anthropic"] == "TENCENT_TOKENHUB_MODEL"
    assert smoke._BASE_ENV["tencent_tokenhub_anthropic"] == "TENCENT_TOKENHUB_ANTHROPIC_BASE_URL"
    assert smoke._DEFAULT_MODELS["tencent_tokenhub_anthropic"] == "hy3"

    assert smoke._MODEL_ENV["tencent_tokenhub_intl"] == "TENCENT_TOKENHUB_INTL_MODEL"
    assert smoke._BASE_ENV["tencent_tokenhub_intl"] == "TENCENT_TOKENHUB_INTL_BASE_URL"
    assert smoke._DEFAULT_MODELS["tencent_tokenhub_intl"] == "deepseek-v3.2"

    assert smoke._MODEL_ENV["tencent_token_plan"] == "TENCENT_TOKEN_PLAN_MODEL"
    assert smoke._BASE_ENV["tencent_token_plan"] == "TENCENT_TOKEN_PLAN_BASE_URL"
    assert smoke._DEFAULT_MODELS["tencent_token_plan"] == "hy3"

    assert smoke._MODEL_ENV["tokenrhythm"] == "TOKENRHYTHM_MODEL"
    assert smoke._BASE_ENV["tokenrhythm"] == "TOKENRHYTHM_BASE_URL"
    assert smoke._DEFAULT_MODELS["tokenrhythm"] == "deepseek-v4-flash"
    # Reasoning tokens bill against max_tokens: the default 64 budget would
    # return empty content with finish_reason "length".
    assert smoke._MIN_MAX_TOKENS["tokenrhythm"] >= 512


def test_live_smoke_uses_moonshot_temperature_required_by_kimi_k2_6() -> None:
    assert smoke._direct_openai_temperature("moonshot", "kimi-k2.6") == 1
    assert smoke._direct_openai_temperature("kimi_coding_openai", "kimi-for-coding") == 1
    assert smoke._direct_openai_temperature("moonshot", "moonshot-v1-8k") == 0
    assert smoke._direct_openai_temperature("openai", "gpt-5.4-mini") == 0
    assert (
        smoke._direct_openai_token_limit_field("openai", "gpt-5.4-mini")
        == "max_completion_tokens"
    )
    assert smoke._direct_openai_token_limit_field("openai", "gpt-4.1") == "max_tokens"


def test_live_smoke_parses_csv_model_lists() -> None:
    assert smoke._csv_values("glm-5, glm-5.1,, kimi-k2.6 ") == [
        "glm-5",
        "glm-5.1",
        "kimi-k2.6",
    ]
    assert smoke._csv_values(None) == []
