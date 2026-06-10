from __future__ import annotations

import pytest


def test_install_policy_request_rejects_non_appcontainer_sid() -> None:
    from opensquilla.sandbox.windows_service_client import InstallPolicyRequest

    with pytest.raises(ValueError, match="AppContainer SID"):
        InstallPolicyRequest(
            run_id="run-1",
            appcontainer_sid="S-1-5-21-123",
            proxy_host="127.0.0.1",
            proxy_port=48123,
            ttl_seconds=60,
        )


def test_install_policy_request_rejects_non_loopback_proxy() -> None:
    from opensquilla.sandbox.windows_service_client import InstallPolicyRequest

    with pytest.raises(ValueError, match="loopback"):
        InstallPolicyRequest(
            run_id="run-1",
            appcontainer_sid="S-1-15-2-123",
            proxy_host="192.168.1.2",
            proxy_port=48123,
            ttl_seconds=60,
        )


def test_install_policy_payload_shape() -> None:
    from opensquilla.sandbox.windows_service_client import InstallPolicyRequest

    request = InstallPolicyRequest(
        run_id="run-1",
        appcontainer_sid="S-1-15-2-123",
        proxy_host="127.0.0.1",
        proxy_port=48123,
        ttl_seconds=60,
    )

    assert request.to_payload() == {
        "op": "install_policy",
        "run_id": "run-1",
        "appcontainer_sid": "S-1-15-2-123",
        "proxy_host": "127.0.0.1",
        "proxy_port": 48123,
        "ttl_seconds": 60,
    }


@pytest.mark.asyncio
async def test_service_dispatch_install_policy_calls_wfp(monkeypatch) -> None:
    from opensquilla.sandbox import windows_service_client

    calls = []

    def fake_install(**kwargs):
        calls.append(kwargs)
        return (11, 12, 13, 14)

    monkeypatch.setattr(
        windows_service_client.windows_wfp,
        "install_wfp_policy",
        fake_install,
    )

    response = await windows_service_client.dispatch_service_request(
        {
            "op": "install_policy",
            "run_id": "run-1",
            "appcontainer_sid": "S-1-15-2-123",
            "proxy_host": "127.0.0.1",
            "proxy_port": 48123,
            "ttl_seconds": 60,
        }
    )

    assert response["status"] == "ok"
    assert response["filter_ids"] == [11, 12, 13, 14]
    assert calls[0]["run_id"] == "run-1"
