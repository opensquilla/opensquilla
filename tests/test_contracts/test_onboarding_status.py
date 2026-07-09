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
from opensquilla.migration.legacy_detect import LegacyHomeCandidate, suggested_migrate_command

# Exact top-level shape of onboarding.status as shipped today.
STATUS_TOP_LEVEL_KEYS = frozenset(
    {
        "configPath",
        "hasConfig",
        "llmConfigured",
        "llmSource",
        "llmEnvKey",
        "llmCredentialStatus",
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
        "ensembleCredentialStatus",
        "needsOnboarding",
        "sections",
        "sectionDetails",
        "envRecoveryCommands",
        "warnings",
        # Nullable legacy-data advisory block: a deliberate additive
        # extension for the legacy-home import flow. Detection is read-only;
        # the Web UI setup flow renders the block's `command` for the
        # operator to run against a stopped gateway.
        "legacyData",
    }
)

# Exact shape of the populated ``legacyData`` block; ``None`` when no legacy
# home is detected.
LEGACY_DATA_KEYS = frozenset({"path", "kind", "command"})

# Section names double as wire keys inside ``sections`` / ``sectionDetails``.
# ``ensemble`` is a deliberate additive extension of this frozen set: the
# ``[llm_ensemble]`` routing surface gained CLI onboarding parity
# (``opensquilla onboard configure ensemble``), and the CLI status table
# renders straight from this payload, so the section rides the same frozen
# contract. Its verifier only ever reports ``ok`` (enabled) or ``optional``
# (disabled) — it can never block onboarding or add action-required noise
# for existing clients. Extending this set here is the conscious decision
# the freeze forces.
SECTION_NAMES = frozenset(
    {
        "llm",
        "router",
        "ensemble",
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

# Additive per-section keys, allowed only on the named section. ``routerMode``
# is a deliberate router-card addition: a server-computed
# ``recommended|openrouter-mix|custom|disabled`` value so clients stop
# inferring the mode from (provider, tier_profile) pairs. Adding to this map is
# the conscious decision the friction forces.
SECTION_EXTRA_KEYS = {"router": frozenset({"routerMode"})}

# Every mode value the router card may carry; matched verbatim by clients.
ROUTER_MODE_VALUES = frozenset({"recommended", "openrouter-mix", "custom", "disabled"})

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
        allowed_extra = {"detail"} | SECTION_EXTRA_KEYS.get(name, frozenset())
        extra = set(detail) - SECTION_DETAIL_REQUIRED_KEYS - allowed_extra
        assert not extra, (name, extra)


async def test_router_section_carries_an_explicit_router_mode(tmp_path) -> None:
    # routerMode must always be present on the router card and only ever be
    # one of the four frozen mode strings.
    payload = _status_payload(RpcContext(conn_id="contract", config=_synthetic_config(tmp_path)))
    assert payload["sectionDetails"]["router"]["routerMode"] in ROUTER_MODE_VALUES


async def test_router_mode_computation_is_frozen(tmp_path) -> None:
    """Pin the (enabled, provider, tier_profile) → routerMode mapping."""

    def mode_for(cfg: GatewayConfig) -> str:
        payload = _status_payload(RpcContext(conn_id="contract", config=cfg))
        return payload["sectionDetails"]["router"]["routerMode"]

    # Default config: tokenrhythm provider, router enabled, no tier_profile.
    assert mode_for(_synthetic_config(tmp_path)) == "custom"

    # Explicit openrouter with no tier_profile is the openrouter-mix alias.
    assert (
        mode_for(_synthetic_config(tmp_path, llm={"provider": "openrouter"}))
        == "openrouter-mix"
    )

    # Router off wins regardless of provider/profile.
    assert (
        mode_for(_synthetic_config(tmp_path, squilla_router={"enabled": False})) == "disabled"
    )

    # A persisted legacy tier_profile is the recommended shape.
    assert (
        mode_for(
            _synthetic_config(
                tmp_path,
                llm=LlmProviderConfig(provider="deepseek", model="deepseek-v4-flash"),
                squilla_router={"enabled": True, "tier_profile": "deepseek"},
            )
        )
        == "recommended"
    )

    # Enabled with no tier_profile on a non-openrouter provider is custom.
    # (groq is outside the legacy nine, so the boot auto-default never
    # assigns it a tier_profile.)
    assert (
        mode_for(
            _synthetic_config(
                tmp_path,
                llm=LlmProviderConfig(provider="groq", model="m"),
                squilla_router={"enabled": True},
            )
        )
        == "custom"
    )


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


# Every value ``llmSource`` may carry over the wire. ``unsupported`` is a
# deliberate additive extension: registered-but-runtime-unsupported providers
# (e.g. coding-plan stubs) used to report ``not_required``, which read as a
# satisfied credential state for a provider nothing can run against. Client
# authors switching on llmSource must treat unknown values as
# not-configured; extending this set here is the conscious decision the
# freeze forces.
LLM_SOURCE_VALUES = frozenset(
    {"explicit", "env", "missing_env", "none", "not_required", "unsupported"}
)


async def test_llm_source_value_space_is_frozen(tmp_path) -> None:
    payload = _status_payload(
        RpcContext(conn_id="contract", config=_synthetic_config(tmp_path))
    )
    assert payload["llmSource"] in LLM_SOURCE_VALUES


async def test_unsupported_provider_source_is_consistent_across_the_payload(
    tmp_path,
) -> None:
    """llmSource and llmCredentialStatus.source must agree for a registered
    but runtime-unsupported provider: both say "unsupported" (never a
    satisfied "not_required") and the credential is not available."""
    cfg = _synthetic_config(
        tmp_path,
        llm=LlmProviderConfig(provider="github_copilot", model="stub-model"),
    )

    payload = _status_payload(RpcContext(conn_id="contract", config=cfg))

    assert payload["llmSource"] == "unsupported"
    credential = payload["llmCredentialStatus"]
    assert credential["source"] == "unsupported"
    assert credential["available"] is False
    assert payload["sectionDetails"]["llm"]["detail"] == (
        "registered but not runtime-supported"
    )


async def test_legacy_data_block_is_null_without_a_candidate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Detection is stubbed to the no-candidate outcome so the assertion holds
    # on developer machines that do have a real legacy home lying around.
    monkeypatch.setattr(
        "opensquilla.migration.legacy_detect.detect_legacy_home",
        lambda target=None: None,
    )

    payload = _status_payload(
        RpcContext(conn_id="contract", config=_synthetic_config(tmp_path))
    )

    assert payload["legacyData"] is None


async def test_legacy_data_block_shape_is_frozen(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = LegacyHomeCandidate(path=tmp_path / "legacy-home", kind="cli-home")
    monkeypatch.setattr(
        "opensquilla.migration.legacy_detect.detect_legacy_home",
        lambda target=None: candidate,
    )

    payload = _status_payload(
        RpcContext(conn_id="contract", config=_synthetic_config(tmp_path))
    )

    block = payload["legacyData"]
    assert set(block) == LEGACY_DATA_KEYS
    assert block["path"] == str(tmp_path / "legacy-home")
    assert block["kind"] == "cli-home"
    # The command is the exact CLI invocation the advisory tells the operator
    # to run (dry-run by default; clients append --apply themselves).
    assert block["command"] == suggested_migrate_command(candidate)
    assert block["command"].startswith("opensquilla migrate opensquilla ")
