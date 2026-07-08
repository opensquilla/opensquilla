"""Explicit llm.base_url must win over provider-derived env overrides (#484).

The resolver distinguishes an operator-chosen base_url from a derived one by
value-vs-baseline: a stored value equal to the pydantic field default, the
provider spec default, or the current derived env value (``OPENAI_BASE_URL``
et al.) is *derived*, everything else is *explicit*. Explicit values beat the
env var; derived values keep today's env-first behavior so a fleet-wide
``*_BASE_URL`` still applies to configs that never chose an endpoint.

Everything here is offline and synthetic; env vars are scoped via monkeypatch.
"""

from __future__ import annotations

import tomllib
from types import SimpleNamespace

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config
from opensquilla.gateway.rpc_config import _handle_config_set
from opensquilla.onboarding.config_store import persist_config
from opensquilla.onboarding.mutations import upsert_llm_provider

_ENV_URL = "https://corp-endpoint.example/v1"
_USER_URL = "https://user-proxy.example/v1"
_OPENAI_SPEC_DEFAULT = "https://api.openai.com/v1"
_FIELD_DEFAULT = "https://openrouter.ai/api/v1"


class _CapturingSelector:
    def __init__(self) -> None:
        self.synced = None

    def sync_primary(self, cfg) -> None:
        self.synced = cfg


def _admin_ctx(config, selector=None):
    return SimpleNamespace(config=config, provider_selector=selector)


def test_explicit_config_base_url_beats_provider_env(monkeypatch) -> None:
    """#484 core: a user-chosen base_url must survive env-present resolution."""
    monkeypatch.setenv("OPENAI_BASE_URL", _ENV_URL)
    cfg = GatewayConfig(
        llm={
            "provider": "openai",
            "model": "gpt-5.5",
            "api_key": "sk-explicit",
            "base_url": _USER_URL,
        }
    )

    runtime = resolve_llm_runtime_config(cfg)

    assert runtime.base_url == _USER_URL
    assert runtime.base_url_from_env is False
    # The live model must keep serving the explicit URL too (no env clobber).
    assert cfg.llm.base_url == _USER_URL


def test_saved_base_url_survives_restart_with_env_set(tmp_path, monkeypatch) -> None:
    """#484 end-to-end: save via the provider mutation, persist, reboot, resolve."""
    monkeypatch.setenv("OPENAI_BASE_URL", _ENV_URL)
    config_path = tmp_path / "config.toml"
    cfg = GatewayConfig(config_path=str(config_path))
    resolve_llm_runtime_config(cfg)  # boot-time resolution on the default config

    res = upsert_llm_provider(
        cfg,
        provider_id="openai_responses",
        model="gpt-5.5",
        api_key="sk-user",
        base_url=_USER_URL,
    )
    persist_config(res.config, path=config_path)

    assert tomllib.loads(config_path.read_text())["llm"]["base_url"] == _USER_URL

    rebooted = GatewayConfig.load_from_toml(config_path)
    runtime = resolve_llm_runtime_config(rebooted)

    assert runtime.base_url == _USER_URL
    assert rebooted.llm.base_url == _USER_URL
    assert runtime.base_url_from_env is False


def test_minimal_toml_resolves_spec_default_not_field_default(tmp_path, monkeypatch) -> None:
    """A config that never chose an endpoint must get the PROVIDER's default.

    The pydantic field default is the openrouter URL; before value-vs-baseline
    resolution it leaked into every minimal non-openrouter config.
    """
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    config_path = tmp_path / "config.toml"
    config_path.write_text('[llm]\nprovider = "openai"\nmodel = "gpt-5.5"\napi_key = "sk-x"\n')

    runtime = resolve_llm_runtime_config(GatewayConfig.load_from_toml(config_path))

    assert runtime.base_url == _OPENAI_SPEC_DEFAULT
    assert runtime.base_url_from_env is False


def test_spec_default_stored_value_yields_to_env(monkeypatch) -> None:
    """A stored value equal to the spec default is derived, not operator-chosen.

    The Web UI seeds the endpoint field with the spec default and submits it
    verbatim, so this shape is common on disk; a fleet-wide env override must
    keep applying to it.
    """
    monkeypatch.setenv("OPENAI_BASE_URL", _ENV_URL)
    cfg = GatewayConfig(
        llm={
            "provider": "openai",
            "model": "gpt-5.5",
            "api_key": "sk-x",
            "base_url": _OPENAI_SPEC_DEFAULT,
        }
    )

    runtime = resolve_llm_runtime_config(cfg)

    assert runtime.base_url == _ENV_URL
    assert runtime.base_url_from_env is True


def test_field_default_stored_value_yields_to_env(tmp_path, monkeypatch) -> None:
    """Minimal TOML (field default in the loaded model) keeps env-first behavior."""
    monkeypatch.setenv("OPENAI_BASE_URL", _ENV_URL)
    config_path = tmp_path / "config.toml"
    config_path.write_text('[llm]\nprovider = "openai"\nmodel = "gpt-5.5"\napi_key = "sk-x"\n')

    runtime = resolve_llm_runtime_config(GatewayConfig.load_from_toml(config_path))

    assert runtime.base_url == _ENV_URL
    assert runtime.base_url_from_env is True


def test_stored_env_value_is_env_derived_and_idempotent(monkeypatch) -> None:
    """A stored value equal to the current env value counts as env-derived.

    This is what keeps repeated in-process resolves stable: the first resolve
    materializes the env URL into the model, and the second must classify it
    exactly the same way (from_env stays True, no explicit promotion).
    """
    monkeypatch.setenv("OPENAI_BASE_URL", _ENV_URL)
    cfg = GatewayConfig(
        llm={"provider": "openai", "model": "gpt-5.5", "api_key": "sk-x", "base_url": _ENV_URL}
    )

    first = resolve_llm_runtime_config(cfg)
    second = resolve_llm_runtime_config(cfg)

    assert first.base_url == _ENV_URL
    assert first.base_url_from_env is True
    assert second.base_url == _ENV_URL
    assert second.base_url_from_env is True


def test_base_url_from_env_reports_false_without_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    explicit = GatewayConfig(
        llm={"provider": "openai", "model": "gpt-5.5", "api_key": "sk-x", "base_url": _USER_URL}
    )
    derived = GatewayConfig(llm={"provider": "openai", "model": "gpt-5.5", "api_key": "sk-x"})

    assert resolve_llm_runtime_config(explicit).base_url_from_env is False
    assert resolve_llm_runtime_config(derived).base_url_from_env is False


def test_unknown_provider_preserves_explicit_base_url(monkeypatch) -> None:
    """Degraded boot (unregistered provider) must not lose the stored endpoint."""
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    cfg = GatewayConfig(
        llm={"provider": "not-a-provider", "model": "m", "api_key": "k", "base_url": _USER_URL}
    )

    runtime = resolve_llm_runtime_config(cfg)

    assert runtime.base_url == _USER_URL
    assert runtime.base_url_from_env is False


async def test_config_set_persists_user_base_url_with_env_set(tmp_path, monkeypatch) -> None:
    """#484 via config.set: the user's URL must reach disk and the selector."""
    monkeypatch.setenv("OPENAI_BASE_URL", _ENV_URL)
    config_path = tmp_path / "config.toml"
    cfg = GatewayConfig(
        config_path=str(config_path),
        llm={"provider": "openai", "model": "gpt-5.5", "api_key": "sk-x"},
    )
    resolve_llm_runtime_config(cfg)  # boot
    selector = _CapturingSelector()
    ctx = _admin_ctx(cfg, selector)

    await _handle_config_set({"path": "llm.base_url", "value": _USER_URL}, ctx)

    assert tomllib.loads(config_path.read_text())["llm"]["base_url"] == _USER_URL
    assert _ENV_URL not in config_path.read_text()
    assert ctx.config.llm.base_url == _USER_URL
    assert selector.synced.base_url == _USER_URL

    rebooted = GatewayConfig.load_from_toml(config_path)
    assert resolve_llm_runtime_config(rebooted).base_url == _USER_URL


async def test_config_set_unrelated_change_does_not_bake_env_url(tmp_path, monkeypatch) -> None:
    """An unrelated config.set on an env-resolved config must not write the env URL."""
    monkeypatch.setenv("OPENAI_BASE_URL", _ENV_URL)
    config_path = tmp_path / "config.toml"
    config_path.write_text('[llm]\nprovider = "openai"\nmodel = "gpt-5.5"\napi_key = "sk-x"\n')
    cfg = GatewayConfig.load_from_toml(config_path)
    cfg.config_path = str(config_path)
    resolve_llm_runtime_config(cfg)  # boot materializes the env URL + records it
    assert cfg.llm.base_url == _ENV_URL
    ctx = _admin_ctx(cfg, _CapturingSelector())

    await _handle_config_set({"path": "port", "value": 18795}, ctx)

    text = config_path.read_text()
    assert _ENV_URL not in text
    assert tomllib.loads(text)["port"] == 18795
