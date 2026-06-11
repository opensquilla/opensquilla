from __future__ import annotations

from types import SimpleNamespace


def test_setup_status_payload_defaults_to_not_setup() -> None:
    from opensquilla.sandbox.setup_state import SandboxSetupState, setup_status_payload

    payload = setup_status_payload(SandboxSetupState.NOT_SETUP, platform="win32")

    assert payload == {
        "state": "not_setup",
        "platform": "win32",
        "message": "Sandbox setup has not been completed.",
        "requiresAdmin": False,
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
            message="Windows restricted-token sandbox is ready.",
            requires_admin=False,
        )

    monkeypatch.setattr(setup_state.sys, "platform", "win32")
    monkeypatch.setattr(setup_state, "_ensure_windows_setup", fake_windows_setup)

    result = await setup_state.ensure_sandbox_setup(SimpleNamespace())

    assert result.state is setup_state.SandboxSetupState.READY
    assert calls


async def test_windows_setup_status_reports_restricted_token_ready(monkeypatch) -> None:
    from opensquilla.sandbox import setup_state

    monkeypatch.setattr(setup_state.sys, "platform", "win32")
    monkeypatch.setattr(
        setup_state,
        "_probe_windows_sandbox_support",
        lambda: setup_state.WindowsSetupSupport(
            restricted_token_available=True,
            ctypes_available=True,
            restricted_token_enforced=True,
            proxy_allowlist_enforced=False,
        ),
    )

    result = await setup_state.current_sandbox_setup_status(SimpleNamespace())

    assert result.state is setup_state.SandboxSetupState.READY
    assert result.requires_admin is False
    assert result.message == "Windows restricted-token sandbox is ready."


async def test_windows_setup_status_reports_restricted_token_unavailable(
    monkeypatch,
) -> None:
    from opensquilla.sandbox import setup_state

    monkeypatch.setattr(setup_state.sys, "platform", "win32")
    monkeypatch.setattr(
        setup_state,
        "_probe_windows_sandbox_support",
        lambda: setup_state.WindowsSetupSupport(
            restricted_token_available=False,
            ctypes_available=True,
            restricted_token_enforced=False,
            proxy_allowlist_enforced=False,
        ),
    )

    result = await setup_state.ensure_sandbox_setup(SimpleNamespace())

    assert result.state is setup_state.SandboxSetupState.UNAVAILABLE
    assert result.requires_admin is False
    assert result.detail == "restricted_token=not ready"
