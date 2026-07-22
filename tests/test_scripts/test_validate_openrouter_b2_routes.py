from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from opensquilla.gateway.llm_runtime import OPENROUTER_DEFAULT_PROVIDER_ROUTING

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "experiments" / "validate_openrouter_b2_routes.py"
REGISTRY_PATH = (
    ROOT / "src" / "opensquilla" / "provider" / "router_dynamic_model_profiles.json"
)


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_openrouter_b2_routes_under_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def test_formal_scope_is_default(tmp_path: Path) -> None:
    args = validator.parse_args([str(tmp_path / "evidence.json")])

    assert args.scope == "formal"


def test_formal_routes_cover_exact_router_dynamic_registry() -> None:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    registry_models = {
        str(row["registry_facts"]["model_id"]) for row in payload["models"]
    }

    assert set(validator.FORMAL_EXPECTED_ROUTES) == registry_models
    assert set(validator.B2_EXPECTED_ROUTES) <= registry_models


def test_formal_routes_match_runtime_pins_and_capability_contract() -> None:
    for model, provider in validator.FORMAL_EXPECTED_ROUTES.items():
        assert OPENROUTER_DEFAULT_PROVIDER_ROUTING[model] == provider
        required = validator.FORMAL_REQUIRED_PARAMETERS[model]
        assert {"max_tokens", "tools"} <= required
        assert ("reasoning" in required) is (
            model not in validator.FORMAL_REASONING_INELIGIBLE_MODELS
        )
        assert ("temperature" in required) is (
            model not in validator.FORMAL_UNSUPPORTED_TEMPERATURE_MODELS
        )
