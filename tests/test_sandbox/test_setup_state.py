from __future__ import annotations

from types import SimpleNamespace


def test_setup_status_payload_defaults_to_not_setup() -> None:
    from opensquilla.sandbox.setup_state import SandboxSetupState, setup_status_payload

    payload = setup_status_payload(SandboxSetupState.NOT_SETUP, platform="win32")

    assert payload == {
        "state": "not_setup",
        "platform": "win32",
        "message": "Sandbox setup has not been completed.",
        "requiresAdmin": True,
    }


def test_linux_setup_does_not_require_admin() -> None:
    from opensquilla.sandbox.setup_state import SandboxSetupState, setup_status_payload

    payload = setup_status_payload(SandboxSetupState.READY, platform="linux")

    assert payload["state"] == "ready"
    assert payload["requiresAdmin"] is False


async def test_platform_setup_dispatches_windows(monkeypatch) -> None:
    from opensquilla.sandbox import setup_state

    calls = []

    async def fake_windows_setup(config):
        calls.append(config)
        return setup_state.SetupResult(
            state=setup_state.SandboxSetupState.READY,
            platform="win32",
            message="Windows sandbox service is ready.",
            requires_admin=True,
        )

    monkeypatch.setattr(setup_state.sys, "platform", "win32")
    monkeypatch.setattr(setup_state, "_ensure_windows_setup", fake_windows_setup)

    result = await setup_state.ensure_sandbox_setup(SimpleNamespace())

    assert result.state is setup_state.SandboxSetupState.READY
    assert calls
