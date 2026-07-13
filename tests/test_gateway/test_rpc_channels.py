"""RPC tests for channel status payloads."""

from __future__ import annotations

import httpx
import pytest

import opensquilla.gateway.rpc_channels  # noqa: F401  ensures registration
from opensquilla.channels.contract import (
    ChannelCapabilities,
    ChannelCapabilityProfile,
    ChannelPlatformCapabilityStatus,
    ChannelPlatformCategories,
)
from opensquilla.gateway.auth import Principal
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.onboarding.mutations import upsert_channel


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


def _admin_ctx() -> RpcContext:
    return RpcContext(
        conn_id="t-admin",
        principal=Principal(
            role="operator",
            scopes=frozenset({"operator.admin"}),
            is_owner=True,
            authenticated=True,
        ),
    )


@pytest.mark.asyncio
async def test_channels_status_includes_configured_channels_without_manager():
    ctx = _read_ctx()
    res = upsert_channel(
        GatewayConfig(),
        entry_payload={
            "type": "slack",
            "name": "work",
            "token": "xoxb-secret",
            "signing_secret": "ss",
        },
    )
    ctx.config = res.config

    rpc_res = await get_dispatcher().dispatch("r1", "channels.status", {}, ctx)

    assert rpc_res.error is None, rpc_res.error
    assert rpc_res.payload["channels"] == [
        {
            "name": "work",
            "connected": False,
            "status": "stopped",
            "bot_user_id": None,
            "connected_since": None,
            "restart_attempts": 0,
            "type": "slack",
            "enabled": True,
            "configured": True,
            "capabilities": [],
            "capability_profile": None,
            "platform_manifest": None,
            "diagnostics": {"network_probe": "not_run"},
        }
    ]


@pytest.mark.asyncio
async def test_channels_status_reports_adapter_capabilities_without_network_probe():
    class FakeHealth:
        connected = True
        bot_user_id = "bot-1"
        extra = {"connected_since": "now", "restart_attempts": 2}

    class FakeAdapter:
        capability_profile = ChannelCapabilityProfile(
            channel_type="discord",
            group_chat=True,
            native_file_upload=True,
            inbound_reactions=True,
            thread_messages=True,
            group_dm=True,
            transports=("websocket",),
        )

    class FakeManager:
        _channel_types = {"discord": "discord"}

        async def health(self):
            return {"discord": FakeHealth()}

        def get(self, name: str):
            assert name == "discord"
            return FakeAdapter()

    ctx = _read_ctx()
    ctx.channel_manager = FakeManager()

    rpc_res = await get_dispatcher().dispatch("r1", "channels.status", {}, ctx)

    assert rpc_res.error is None, rpc_res.error
    assert rpc_res.payload is not None
    row = rpc_res.payload["channels"][0]
    assert row["name"] == "discord"
    assert row["status"] == "connected"
    assert set(row["capabilities"]) >= {
        ChannelCapabilities.GROUP_CHAT,
        ChannelCapabilities.GROUP_DM,
        ChannelCapabilities.INBOUND_REACTIONS,
        ChannelCapabilities.NATIVE_FILE_UPLOAD,
        ChannelCapabilities.THREAD_MESSAGES,
        ChannelCapabilities.WEBSOCKET,
    }
    assert row["capability_profile"]["channel_type"] == "discord"
    assert row["capability_profile"]["transports"] == ["websocket"]
    assert row["capability_profile"]["maturity"] == "unrated"
    assert (
        row["capability_profile"]["evidence"][ChannelCapabilities.NATIVE_FILE_UPLOAD][
            "implemented"
        ]
        is False
    )
    assert row["platform_manifest"]["channel_type"] == "discord"
    assert row["platform_manifest"]["capabilities"][ChannelPlatformCategories.CHAT][
        "status"
    ] == ChannelPlatformCapabilityStatus.SUPPORTED
    assert row["platform_manifest"]["capabilities"][ChannelPlatformCategories.FILES][
        "status"
    ] == ChannelPlatformCapabilityStatus.CONFIG_REQUIRED
    assert row["platform_manifest"]["capabilities"][ChannelPlatformCategories.DOCS][
        "status"
    ] == ChannelPlatformCapabilityStatus.UNSUPPORTED
    assert row["diagnostics"] == {"network_probe": "not_run"}


@pytest.mark.asyncio
async def test_channels_status_merges_start_error_diagnostics_for_configured_channel():
    ctx = _read_ctx()
    res = upsert_channel(
        GatewayConfig(),
        entry_payload={
            "type": "dingtalk",
            "name": "dingtalk",
            "client_id": "app-key",
            "client_secret": "app-secret",
        },
    )
    ctx.config = res.config

    class FakeManager:
        _channel_types = {"dingtalk": "dingtalk"}

        async def health(self):
            return {}

        def get(self, name: str):
            assert name == "dingtalk"
            return None

        def start_errors(self):
            return {
                "dingtalk": {
                    "error_type": "DingTalkAuthError",
                    "error": "DingTalk credentials were rejected",
                    "diagnostic": {
                        "error_class": "auth_invalid",
                        "provider_code": "authFailed",
                        "message": "凭证无效：检查 DingTalk AppKey/AppSecret",
                        "retryable": False,
                    },
                }
            }

    ctx.channel_manager = FakeManager()

    rpc_res = await get_dispatcher().dispatch("r1", "channels.status", {}, ctx)

    assert rpc_res.error is None, rpc_res.error
    row = rpc_res.payload["channels"][0]
    assert row["name"] == "dingtalk"
    assert row["status"] == "stopped"
    assert row["connected"] is False
    assert row["diagnostics"]["last_error"] == {
        "error_class": "auth_invalid",
        "provider_code": "authFailed",
        "message": "凭证无效：检查 DingTalk AppKey/AppSecret",
        "retryable": False,
        "source": "start_error",
    }


@pytest.mark.asyncio
async def test_channels_get_redacts_configured_secrets() -> None:
    token = "xoxb-get-secret"
    signing_secret = "signing-get-secret"
    ctx = _admin_ctx()
    result = upsert_channel(
        GatewayConfig(),
        entry_payload={
            "type": "slack",
            "name": "work",
            "token": token,
            "signing_secret": signing_secret,
        },
    )
    ctx.config = result.config

    rpc_res = await get_dispatcher().dispatch(
        "r-get",
        "channels.get",
        {"name": "work"},
        ctx,
    )

    assert rpc_res.error is None, rpc_res.error
    assert rpc_res.payload["entry"]["name"] == "work"
    assert rpc_res.payload["entry"]["token"] == "***"
    assert rpc_res.payload["entry"]["signing_secret"] == "***"
    assert set(rpc_res.payload["secretFields"]) == {"token", "signing_secret"}
    assert token not in repr(rpc_res.payload)
    assert signing_secret not in repr(rpc_res.payload)


@pytest.mark.asyncio
async def test_channels_probe_merges_secrets_and_runs_real_slack_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.channels import registry as channel_registry

    token = "xoxb-stored-probe-secret"
    signing_secret = "stored-signing-secret"
    ctx = _admin_ctx()
    result = upsert_channel(
        GatewayConfig(),
        entry_payload={
            "type": "slack",
            "name": "work",
            "token": token,
            "signing_secret": signing_secret,
        },
    )
    ctx.config = result.config

    def handle_auth_test(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/auth.test"
        assert request.headers["Authorization"] == f"Bearer {token}"
        return httpx.Response(
            200,
            json={"ok": True, "user_id": "U1", "team_id": "T1"},
        )

    client = httpx.AsyncClient(
        base_url="https://slack.test/api",
        headers={"Authorization": f"Bearer {token}"},
        transport=httpx.MockTransport(handle_auth_test),
    )
    real_build = channel_registry.build_managed_channel
    built_adapters: list[object] = []

    def build_with_mock_transport(entry):
        assert entry.token == token
        assert entry.signing_secret == signing_secret
        adapter = real_build(entry)
        assert adapter is not None
        adapter._client = client
        built_adapters.append(adapter)
        return adapter

    monkeypatch.setattr(channel_registry, "build_managed_channel", build_with_mock_transport)

    rpc_res = await get_dispatcher().dispatch(
        "r-probe",
        "channels.probe",
        {
            "entry": {
                "type": "slack",
                "name": "work",
                "token": "",
                "signing_secret": "",
            }
        },
        ctx,
    )

    assert rpc_res.error is None, rpc_res.error
    assert rpc_res.payload["status"] == "verified"
    assert rpc_res.payload["connected"] is True
    assert isinstance(rpc_res.payload["latencyMs"], int)
    assert rpc_res.payload["result"] == {
        "authenticated": True,
        "bot_user_id": "U1",
        "team_id": "T1",
    }
    assert token not in repr(rpc_res.payload)
    assert signing_secret not in repr(rpc_res.payload)
    assert len(built_adapters) == 1
    assert client.is_closed is True
    assert built_adapters[0]._client is None


@pytest.mark.asyncio
async def test_channels_probe_reports_unsupported_and_stops_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.channels import registry as channel_registry

    class UnsupportedAdapter:
        def __init__(self) -> None:
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    adapter = UnsupportedAdapter()
    monkeypatch.setattr(
        channel_registry,
        "build_managed_channel",
        lambda _entry: adapter,
    )
    ctx = _admin_ctx()
    ctx.config = GatewayConfig()

    rpc_res = await get_dispatcher().dispatch(
        "r-unsupported",
        "channels.probe",
        {
            "entry": {
                "type": "dingtalk",
                "name": "dingtalk",
                "client_id": "dummy-client-id",
                "client_secret": "dummy-client-secret",
            }
        },
        ctx,
    )

    assert rpc_res.error is None, rpc_res.error
    assert rpc_res.payload == {
        "status": "unsupported",
        "connected": False,
        "latencyMs": None,
        "detail": "This adapter does not yet expose a safe non-mutating live probe.",
    }
    assert adapter.stopped is True


@pytest.mark.asyncio
async def test_channels_probe_redacts_provider_error_and_result_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.channels import registry as channel_registry

    token = "123:short-secret"

    class FailingAdapter:
        def __init__(self) -> None:
            self.stopped = False

        async def probe_connection(self) -> dict[str, object]:
            raise RuntimeError(f"GET https://api.example/bot{token}/getMe failed")

        async def stop(self) -> None:
            self.stopped = True

    adapter = FailingAdapter()
    monkeypatch.setattr(
        channel_registry,
        "build_managed_channel",
        lambda _entry: adapter,
    )
    ctx = _admin_ctx()
    ctx.config = GatewayConfig()

    rpc_res = await get_dispatcher().dispatch(
        "r-secret-probe",
        "channels.probe",
        {
            "entry": {
                "type": "telegram",
                "name": "telegram",
                "token": token,
            }
        },
        ctx,
    )

    assert rpc_res.error is None, rpc_res.error
    assert rpc_res.payload["status"] == "failed"
    assert token not in repr(rpc_res.payload)
    assert "***" in rpc_res.payload["detail"]
    assert adapter.stopped is True
