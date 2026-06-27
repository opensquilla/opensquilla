"""RPC tests for channel status payloads."""

from __future__ import annotations

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
    assert row["capability_profile"] == {
        "channel_type": "discord",
        "transports": ["websocket"],
    }
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
