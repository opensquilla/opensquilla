"""Gateway→engine plumb for ``provider_request_proof_max_chars``.

The explicit provider-request proof budget travels config.toml ``[llm]`` →
``LlmProviderConfig`` → ``_TurnRunnerModelCatalogAdapter.lookup`` →
``_ResolvedCatalog`` → ``AgentConfig`` → ``ContextBudgetGovernor.from_config``.
These tests pin the gateway-side delivery and the adapter seam; the governor
bypass itself is covered in tests/test_context_budget_governor.py.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.engine.turn_runner.harness import _TurnRunnerModelCatalogAdapter
from opensquilla.gateway.config import GatewayConfig

_ENV_NAME = "OPENSQUILLA_LLM_PROVIDER_REQUEST_PROOF_MAX_CHARS"


def _adapter_for(llm_cfg: object) -> _TurnRunnerModelCatalogAdapter:
    runner = SimpleNamespace(
        _config=SimpleNamespace(llm=llm_cfg),
        _model_catalog=None,
    )
    return _TurnRunnerModelCatalogAdapter(runner)  # type: ignore[arg-type]


def _llm_stub(proof_max_chars: object) -> SimpleNamespace:
    return SimpleNamespace(
        max_tokens=0,
        context_window_tokens=0,
        temperature=None,
        top_p=None,
        provider_request_proof_max_chars=proof_max_chars,
    )


def test_catalog_adapter_forwards_explicit_proof_budget() -> None:
    catalog = _adapter_for(_llm_stub(650_000)).lookup("z-ai/glm-5.1")

    assert catalog.provider_request_proof_max_chars == 650_000


def test_catalog_adapter_defaults_proof_budget_to_zero() -> None:
    catalog = _adapter_for(_llm_stub(0)).lookup("z-ai/glm-5.1")

    assert catalog.provider_request_proof_max_chars == 0


@pytest.mark.parametrize("junk", ["not-a-number", None, -1, 0.0])
def test_catalog_adapter_treats_junk_proof_budget_as_zero(junk: object) -> None:
    catalog = _adapter_for(_llm_stub(junk)).lookup("z-ai/glm-5.1")

    assert catalog.provider_request_proof_max_chars == 0


def test_gateway_config_toml_delivers_proof_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_ENV_NAME, raising=False)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[llm]",
                "provider_request_proof_max_chars = 650000",
            ]
        ),
        encoding="utf-8",
    )

    cfg = GatewayConfig.load(toml_path)

    assert cfg.llm.provider_request_proof_max_chars == 650_000


def test_gateway_config_toml_beats_env_for_proof_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Init/TOML values outrank OPENSQUILLA_LLM_* env in pydantic-settings.

    Delivery consequence: the env var is only a fallback; when config.toml
    carries the key, the TOML value is what the run actually applies.
    """
    monkeypatch.setenv(_ENV_NAME, "111111")

    cfg = GatewayConfig(llm={"provider_request_proof_max_chars": 650_000})

    assert cfg.llm.provider_request_proof_max_chars == 650_000


def test_gateway_config_env_fills_proof_budget_when_toml_omits_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV_NAME, "424242")

    cfg = GatewayConfig(llm={})

    assert cfg.llm.provider_request_proof_max_chars == 424_242


def test_gateway_config_default_proof_budget_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_ENV_NAME, raising=False)

    cfg = GatewayConfig(llm={})

    assert cfg.llm.provider_request_proof_max_chars == 0
