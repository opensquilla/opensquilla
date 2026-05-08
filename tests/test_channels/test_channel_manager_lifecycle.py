"""ChannelManager lifecycle diagnostics."""

from __future__ import annotations

import pytest

from opensquilla.channels.manager import ChannelManager


class _FailingChannel:
    async def start(self) -> None:
        raise RuntimeError("Install Feishu support with `opensquilla[feishu]`")


class _SlowChannel:
    startup_timeout_s = 0.001

    async def start(self) -> None:
        await __import__("asyncio").sleep(0.05)


@pytest.mark.asyncio
async def test_start_all_retains_start_exception_details():
    manager = ChannelManager({"feishu": _FailingChannel()}, None, None)

    results = await manager.start_all()

    assert results == {"feishu": False}
    assert manager.start_errors()["feishu"] == {
        "error_type": "RuntimeError",
        "error": "Install Feishu support with `opensquilla[feishu]`",
        "exception": "RuntimeError('Install Feishu support with `opensquilla[feishu]`')",
    }


@pytest.mark.asyncio
async def test_start_all_honors_adapter_startup_timeout():
    manager = ChannelManager({"feishu": _SlowChannel()}, None, None)

    results = await manager.start_all()

    assert results == {"feishu": False}
    assert manager.start_errors()["feishu"]["error_type"] == "TimeoutError"
