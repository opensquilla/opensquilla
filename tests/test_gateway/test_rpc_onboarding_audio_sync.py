"""Synchronous local coverage for audio onboarding RPC behavior."""

from __future__ import annotations

import asyncio
import platform
import tomllib

import pytest

import opensquilla.gateway.rpc_onboarding  # noqa: F401  ensures registration
from opensquilla.gateway.auth import Principal
from opensquilla.gateway.rpc import RpcContext, get_dispatcher


def _env_command(env_key: str) -> str:
    if platform.system().lower().startswith("win"):
        return f'$env:{env_key} = "<your-key>"'
    return f'export {env_key}="<your-key>"'


def _admin_ctx() -> RpcContext:
    return RpcContext(
        conn_id="t",
        principal=Principal(
            role="operator",
            scopes=frozenset({"operator.admin"}),
            is_owner=True,
            authenticated=True,
        ),
    )


def _read_ctx() -> RpcContext:
    return RpcContext(
        conn_id="t",
        principal=Principal(
            role="operator",
            scopes=frozenset({"operator.read"}),
            is_owner=False,
            authenticated=True,
        ),
    )


@pytest.mark.parametrize("system_name", ["Linux", "Windows"])
def test_audio_onboarding_catalog_configure_and_status(
    tmp_path,
    monkeypatch,
    system_name,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: system_name)
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    async def run_case() -> None:
        catalog = await get_dispatcher().dispatch(
            "catalog",
            "onboarding.catalog",
            {},
            _read_ctx(),
        )
        assert catalog.error is None, catalog.error
        audio_provider_ids = {
            p["providerId"] for p in catalog.payload["audioProviders"]
        }
        assert "elevenlabs" in audio_provider_ids

        res = await get_dispatcher().dispatch(
            "configure",
            "onboarding.audio.configure",
            {
                "providerId": "elevenlabs",
                "apiKeyEnv": "ELEVENLABS_API_KEY",
                "enabled": True,
                "ttsVoice": "voice_custom",
                "ttsModel": "eleven_turbo_v2_5",
                "languageCode": "zh-CN",
            },
            _admin_ctx(),
        )
        assert res.error is None, res.error
        assert res.payload["entry"]["api_key_source"] == "missing_env"
        assert res.payload["entry"]["api_key_env"] == "ELEVENLABS_API_KEY"
        assert res.payload["entry"]["tts_voice"] == "voice_custom"

        status = await get_dispatcher().dispatch(
            "status",
            "onboarding.status",
            {},
            _read_ctx(),
        )
        assert status.error is None, status.error
        assert status.payload["sections"]["audio"] == "degraded"
        assert status.payload["audioEnabled"] is True
        assert status.payload["audioSource"] == "missing_env"
        assert status.payload["audioEnvKey"] == "ELEVENLABS_API_KEY"
        assert status.payload["envRecoveryCommands"] == [
            {
                "section": "audio",
                "label": "Set audio key",
                "command": _env_command("ELEVENLABS_API_KEY"),
            }
        ]

    asyncio.run(run_case())

    data = tomllib.loads(target.read_text())
    assert data["audio"]["enabled"] is True
    # Sparse persistence omits provider fields equal to the built-in
    # defaults (elevenlabs already defaults to ELEVENLABS_API_KEY); the
    # effective reference is asserted through the RPC payload above.
    providers = data["audio"].get("providers", {})
    assert (
        providers.get("elevenlabs", {}).get("api_key_env", "ELEVENLABS_API_KEY")
        == "ELEVENLABS_API_KEY"
    )
    assert data["audio"]["tts"]["voice"] == "voice_custom"
    assert data["audio"]["tts"]["model"] == "eleven_turbo_v2_5"
    assert data["audio"]["tts"]["language_code"] == "zh-CN"


def test_audio_onboarding_redacts_pasted_api_key(tmp_path, monkeypatch) -> None:
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    async def run_case() -> None:
        res = await get_dispatcher().dispatch(
            "configure",
            "onboarding.audio.configure",
            {
                "providerId": "elevenlabs",
                "apiKey": "el-secret",
                "baseUrl": "https://audio.example",
            },
            _admin_ctx(),
        )
        assert res.error is None, res.error
        assert res.payload["entry"]["api_key"] == "***"
        assert "el-secret" not in str(res.payload)

    asyncio.run(run_case())

    data = tomllib.loads(target.read_text())
    assert data["audio"]["providers"]["elevenlabs"]["api_key"] == "el-secret"
    assert data["audio"]["providers"]["elevenlabs"]["base_url"] == "https://audio.example"
