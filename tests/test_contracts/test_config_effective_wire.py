"""Wire-contract freeze for the ``config.effective`` provenance view.

``config.effective`` returns the effective LLM routing fields with per-field
provenance. Clients (Web UI config screens, ``opensquilla config``) script
against the envelope, the per-field record keys, the dotted field paths, and
the source vocabulary, so all four are public protocol contracts (CLAUDE.md:
public RPC field names are stable).

Unlike ``config.get`` (superset-friendly), this view is a curated allowlist:
every path it emits was individually chosen to be non-secret, so the tests
below use EXACT-set assertions. Adding a field here is itself a wire-contract
change: update the list below together with the resolver as a conscious
decision — an unexpected extra path failing this test is the alarm working,
not test friction.

Only synthetic credentials appear (``sk-test-000`` etc.); the environment is
already provider-key-free via tests/conftest.py.
"""

from __future__ import annotations

import pytest

from opensquilla.gateway.config import GatewayConfig, LlmProviderConfig
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.rpc_config import _handle_config_effective

# The full response envelope. Exactly one key: provenance data must never be
# merged with other config surfaces without a new contract decision.
ENVELOPE_KEYS = frozenset({"fields"})

# Every per-field record carries exactly these keys. A {path, value, source}
# triple was deliberately rejected (it defeats key-name redaction); the path
# is the dict key instead.
FIELD_RECORD_KEYS = frozenset({"value", "source"})

# The provenance vocabulary. "session" is reserved (no field emits it yet)
# but is part of the contract so clients can pre-wire rendering for it.
ALLOWED_SOURCES = frozenset({"default", "catalog", "preset", "config", "session"})

# Exact field-path set for a default config (default router tiers c0-c3 +
# image_model). Conscious decision required to change: each entry is an
# individually vetted non-secret path — renames, removals, AND additions are
# contract changes that must update clients and this list together.
EXPECTED_FIELD_PATHS = frozenset(
    {
        "llm.provider",
        "llm.model",
        "llm.base_url",
        "llm.max_tokens",
        "llm.context_window",
        "llm_ensemble.enabled",
        "llm_ensemble.selection_mode",
        "squilla_router.tiers.c0.provider",
        "squilla_router.tiers.c0.model",
        "squilla_router.tiers.c1.provider",
        "squilla_router.tiers.c1.model",
        "squilla_router.tiers.c2.provider",
        "squilla_router.tiers.c2.model",
        "squilla_router.tiers.c3.provider",
        "squilla_router.tiers.c3.model",
        "squilla_router.tiers.image_model.provider",
        "squilla_router.tiers.image_model.model",
    }
)

SYNTHETIC_SECRET = "sk-test-000"  # synthetic; never a real credential


@pytest.fixture()
def default_config(tmp_path, monkeypatch: pytest.MonkeyPatch) -> GatewayConfig:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "state"))
    return GatewayConfig(config_path=str(tmp_path / "opensquilla.toml"))


async def _effective(config: GatewayConfig) -> dict:
    return await _handle_config_effective(None, RpcContext(conn_id="test", config=config))


async def test_envelope_is_exactly_fields(default_config: GatewayConfig) -> None:
    result = await _effective(default_config)
    assert set(result) == ENVELOPE_KEYS


async def test_field_paths_are_frozen_exact_set(default_config: GatewayConfig) -> None:
    result = await _effective(default_config)
    assert set(result["fields"]) == EXPECTED_FIELD_PATHS


async def test_field_records_and_sources_are_frozen(default_config: GatewayConfig) -> None:
    result = await _effective(default_config)
    for path, record in result["fields"].items():
        assert set(record) == FIELD_RECORD_KEYS, path
        assert record["source"] in ALLOWED_SOURCES, path


async def test_no_secret_value_ever_reaches_the_wire(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A config carrying explicit secrets across every secret-bearing surface
    # the resolver walks near: the response must not contain the marker
    # anywhere, in any key or value, at any nesting depth.
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "state"))
    cfg = GatewayConfig(
        config_path=str(tmp_path / "opensquilla.toml"),
        llm=LlmProviderConfig(api_key=SYNTHETIC_SECRET),
        channels={
            "channels": [
                {
                    "name": "feishu-main",
                    "type": "feishu",
                    "app_id": "cli_dummy_0000",
                    "app_secret": SYNTHETIC_SECRET,
                    "encrypt_key": SYNTHETIC_SECRET,
                    "verification_token": SYNTHETIC_SECRET,
                },
                {
                    "name": "wecom-main",
                    "type": "wecom",
                    "connection_mode": "webhook",
                    "corp_id": "ww_dummy_0000",
                    "corp_secret": SYNTHETIC_SECRET,
                    "agent_id_int": 1000002,
                    "token": SYNTHETIC_SECRET,
                    "encoding_aes_key": SYNTHETIC_SECRET,
                },
            ]
        },
    )

    result = await _effective(cfg)

    assert set(result["fields"]) == EXPECTED_FIELD_PATHS
    assert SYNTHETIC_SECRET not in repr(result)
