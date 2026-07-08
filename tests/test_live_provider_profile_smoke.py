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
    assert smoke._DEFAULT_MODELS["openai"] == "gpt-4.1"

    assert smoke._MODEL_ENV["zhipu"] == "ZAI_MODEL"
    assert smoke._BASE_ENV["zhipu"] == "ZAI_BASE_URL"
    assert smoke._DEFAULT_MODELS["zhipu"] == "glm-4.5"

    assert smoke._MODEL_ENV["moonshot"] == "MOONSHOT_MODEL"
    assert smoke._BASE_ENV["moonshot"] == "MOONSHOT_BASE_URL"
    assert smoke._DEFAULT_MODELS["moonshot"] == "kimi-k2.6"

    assert smoke._MODEL_ENV["byteplus"] == "BYTEPLUS_MODEL"
    assert smoke._BASE_ENV["byteplus"] == "BYTEPLUS_BASE_URL"
    assert smoke._DEFAULT_MODELS["byteplus"] == "seed-2-0-lite-260228"

    assert smoke._MODEL_ENV["minimax"] == "MINIMAX_MODEL"
    assert smoke._BASE_ENV["minimax"] == "MINIMAX_BASE_URL"
    assert smoke._DEFAULT_MODELS["minimax"] == "MiniMax-M2.7"

    assert smoke._MODEL_ENV["minimax_openai"] == "MINIMAX_MODEL"
    assert smoke._BASE_ENV["minimax_openai"] == "MINIMAX_OPENAI_BASE_URL"
    assert smoke._DEFAULT_MODELS["minimax_openai"] == "MiniMax-M2.7"

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


def test_live_smoke_uses_moonshot_temperature_required_by_kimi_k2_6() -> None:
    assert smoke._direct_openai_temperature("moonshot", "kimi-k2.6") == 1
    assert smoke._direct_openai_temperature("moonshot", "moonshot-v1-8k") == 0
    assert smoke._direct_openai_temperature("openai", "gpt-4.1") == 0


def test_live_smoke_parses_csv_model_lists() -> None:
    assert smoke._csv_values("glm-5, glm-5.1,, kimi-k2.6 ") == [
        "glm-5",
        "glm-5.1",
        "kimi-k2.6",
    ]
    assert smoke._csv_values(None) == []
