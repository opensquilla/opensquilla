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


async def test_windows_setup_status_uses_service_client(monkeypatch) -> None:
    from opensquilla.sandbox import setup_state
    from opensquilla.sandbox.windows_service_client import WindowsSandboxServiceClient

    calls = []

    async def fake_health(self):
        calls.append(self.pipe_name)
        return setup_state.SetupResult(
            state=setup_state.SandboxSetupState.READY,
            platform="win32",
            message="Windows sandbox service is ready.",
            requires_admin=True,
        )

    monkeypatch.setattr(setup_state.sys, "platform", "win32")
    monkeypatch.setattr(WindowsSandboxServiceClient, "health", fake_health)

    result = await setup_state.current_sandbox_setup_status(
        SimpleNamespace(sandbox=SimpleNamespace(windows_service_pipe=r"\\.\pipe\custom"))
    )

    assert result.state is setup_state.SandboxSetupState.READY
    assert calls == [r"\\.\pipe\custom"]


async def test_windows_service_client_fails_closed_by_default() -> None:
    from opensquilla.sandbox.setup_state import SandboxSetupState
    from opensquilla.sandbox.windows_service_client import WindowsSandboxServiceClient

    client = WindowsSandboxServiceClient()

    health = await client.health()
    setup = await client.ensure_setup()

    assert health.state is SandboxSetupState.NOT_SETUP
    assert health.requires_admin is True
    assert setup.state is SandboxSetupState.FAILED
    assert setup.requires_admin is True
