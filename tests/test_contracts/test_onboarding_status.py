"""Wire-contract freeze for the ``onboarding.status`` RPC payload.

The status payload drives the Web UI onboarding checklist and the CLI
``onboard status`` renderers, so its camelCase key names are a public
protocol contract (see CLAUDE.md: public RPC field names are stable).

- Renaming or removing any frozen key is a contract break and must fail here.
- Adding a key requires deliberately extending the frozen set in this file —
  that friction is the point: wire additions should be a conscious decision.

The payload is built by ``rpc_onboarding._status_payload`` against a fully
synthetic ``GatewayConfig`` handed to the RPC context, so no config file, no
network, and no credentials are involved (tests/conftest.py already strips
provider keys from the environment).
"""

from __future__ import annotations

import pytest

from opensquilla.gateway.config import GatewayConfig, LlmProviderConfig
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.rpc_onboarding import _status_payload

# Exact top-level shape of onboarding.status as shipped today.
STATUS_TOP_LEVEL_KEYS = frozenset(
    {
        "configPath",
        "hasConfig",
        "llmConfigured",
        "llmSource",
        "llmEnvKey",
        "imageGenerationConfigured",
        "imageGenerationEnabled",
        "imageGenerationSource",
        "imageGenerationProvider",
        "imageGenerationPrimary",
        "imageGenerationEnvKey",
        "audioConfigured",
        "audioEnabled",
        "audioSource",
        "audioProvider",
        "audioEnvKey",
        "searchConfigured",
        "searchProvider",
        "searchSource",
        "searchEnvKey",
        "memoryEmbeddingConfigured",
        "memoryEmbeddingProvider",
        "memoryEmbeddingSource",
        "memoryEmbeddingEnvKey",
        "channelCount",
        "channelsConfigured",
        "needsOnboarding",
        "sections",
        "sectionDetails",
        "envRecoveryCommands",
        "warnings",
    }
)

# Section names double as wire keys inside ``sections`` / ``sectionDetails``.
SECTION_NAMES = frozenset(
    {
        "llm",
        "router",
        "search",
        "channels",
        "image_generation",
        "audio",
        "memory_embedding",
    }
)

# Per-section detail card shape. ``detail`` is the only optional key (a
# human-readable annotation); everything else must always be present.
SECTION_DETAIL_REQUIRED_KEYS = frozenset(
    {"label", "status", "required", "optional", "blocking", "actionRequired"}
)

# Shape of one env-recovery command row shown when a configured env key is
# not visible in the running shell.
ENV_RECOVERY_COMMAND_KEYS = frozenset({"section", "label", "command"})


def _synthetic_config(tmp_path, **overrides) -> GatewayConfig:
    # config_path points at a nonexistent tmp file so the status builder never
    # reads the developer's real ~/.opensquilla config.
    return GatewayConfig(config_path=str(tmp_path / "opensquilla.toml"), **overrides)


async def test_onboarding_status_top_level_keys_are_frozen(tmp_path) -> None:
    cfg = _synthetic_config(tmp_path)
    payload = _status_payload(RpcContext(conn_id="contract", config=cfg))
    assert set(payload) == STATUS_TOP_LEVEL_KEYS
    # configPath must round-trip the running config's path so clients can tell
    # operators which file to edit.
    assert payload["configPath"] == cfg.config_path


async def test_onboarding_status_section_keys_are_frozen(tmp_path) -> None:
    payload = _status_payload(RpcContext(conn_id="contract", config=_synthetic_config(tmp_path)))

    assert set(payload["sections"]) == SECTION_NAMES
    assert set(payload["sectionDetails"]) == SECTION_NAMES

    for name, detail in payload["sectionDetails"].items():
        missing = SECTION_DETAIL_REQUIRED_KEYS - set(detail)
        assert not missing, (name, missing)
        extra = set(detail) - SECTION_DETAIL_REQUIRED_KEYS - {"detail"}
        assert not extra, (name, extra)


async def test_env_recovery_command_rows_are_frozen(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A provider pointed at an env key that is not visible in this shell is
    # the one state that must produce a recovery command; freeze its row shape.
    env_key = "OPENSQUILLA_TEST_UNSET_KEY"
    monkeypatch.delenv(env_key, raising=False)
    cfg = _synthetic_config(tmp_path, llm=LlmProviderConfig(api_key_env=env_key))

    payload = _status_payload(RpcContext(conn_id="contract", config=cfg))

    assert payload["llmSource"] == "missing_env"
    assert payload["llmEnvKey"] == env_key
    commands = payload["envRecoveryCommands"]
    assert commands, "missing_env must surface a recovery command"
    for command in commands:
        assert set(command) == ENV_RECOVERY_COMMAND_KEYS
