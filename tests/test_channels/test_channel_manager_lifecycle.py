"""ChannelManager lifecycle diagnostics."""

from __future__ import annotations

import pytest

from opensquilla.channels.manager import ChannelManager


class _FailingChannel:
    async def start(self) -> None:
        raise RuntimeError("Feishu adapter dependency missing — reinstall OpenSquilla")


class _SlowChannel:
    startup_timeout_s = 0.001
    stopped = False

    async def start(self) -> None:
        await __import__("asyncio").sleep(0.05)

    async def stop(self) -> None:
        self.stopped = True


class _StructuredAuthError(RuntimeError):
    diagnostic = {
        "error_class": "auth_invalid",
        "provider_code": "authFailed",
        "message": "凭证无效：检查 DingTalk AppKey/AppSecret",
        "retryable": False,
    }


class _StructuredFailingChannel:
    async def start(self) -> None:
        raise _StructuredAuthError("DingTalk credentials were rejected")


@pytest.mark.asyncio
async def test_start_all_retains_start_exception_details():
    manager = ChannelManager({"feishu": _FailingChannel()}, None, None)

    results = await manager.start_all()

    assert results == {"feishu": False}
    assert manager.start_errors()["feishu"] == {
        "error_type": "RuntimeError",
        "error": "Feishu adapter dependency missing — reinstall OpenSquilla",
        "exception": (
            "RuntimeError('Feishu adapter dependency missing — reinstall OpenSquilla')"
        ),
    }


@pytest.mark.asyncio
async def test_start_all_honors_adapter_startup_timeout():
    channel = _SlowChannel()
    manager = ChannelManager({"feishu": channel}, None, None)

    results = await manager.start_all()

    assert results == {"feishu": False}
    assert manager.start_errors()["feishu"]["error_type"] == "TimeoutError"
    assert channel.stopped is True


@pytest.mark.asyncio
async def test_start_all_retains_structured_channel_diagnostic():
    manager = ChannelManager({"dingtalk": _StructuredFailingChannel()}, None, None)

    results = await manager.start_all()

    assert results == {"dingtalk": False}
    error = manager.start_errors()["dingtalk"]
    assert error["diagnostic"] == _StructuredAuthError.diagnostic
    assert "AppKey/AppSecret" in error["diagnostic"]["message"]
