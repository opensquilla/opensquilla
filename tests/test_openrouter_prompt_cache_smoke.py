from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_smoke_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "live_openrouter_prompt_cache_smoke.py"
    )
    spec = importlib.util.spec_from_file_location("live_openrouter_prompt_cache_smoke", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke_module()


def test_cache_smoke_defaults_to_zai_glm_5_1() -> None:
    assert smoke.DEFAULT_MODEL == "z-ai/glm-5.1"


def test_cached_prompt_tokens_reads_openai_prompt_details() -> None:
    payload = {"usage": {"prompt_tokens_details": {"cached_tokens": 42}}}

    assert smoke._cached_prompt_tokens(payload) == 42


def test_cached_prompt_tokens_reads_openrouter_cache_fields() -> None:
    payload = {"usage": {"prompt_cache_hit_tokens": 13}}

    assert smoke._cached_prompt_tokens(payload) == 13


def test_cache_request_payload_marks_only_system_text_as_ephemeral() -> None:
    payload = smoke._cache_request_payload("z-ai/glm-5.1", "stable text")

    assert payload["model"] == "z-ai/glm-5.1"
    system = payload["messages"][0]
    assert system["role"] == "system"
    assert system["content"] == [
        {
            "type": "text",
            "text": "stable text",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert payload["messages"][1]["role"] == "user"
