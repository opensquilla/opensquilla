from __future__ import annotations

import json

import pytest


def test_parse_payload_accepts_valid_windows_default_payload(tmp_path) -> None:
    from opensquilla.sandbox.backend.windows_default_runner import _parse_payload

    payload = {
        "backend": "windows_default",
        "argv": ["python", "-c", "print('ok')"],
        "cwd": str(tmp_path),
        "env": {"TEMP": str(tmp_path / ".opensquilla-cache" / "temp")},
        "policy": {"network": "none", "mounts": [], "workspace_rw": True},
        "runMode": "trusted",
        "timeout": 5,
    }

    parsed = _parse_payload([json.dumps(payload)])

    assert parsed.argv == ("python", "-c", "print('ok')")
    assert parsed.cwd == tmp_path
    assert parsed.run_mode == "trusted"


def test_parse_payload_rejects_wrong_backend(tmp_path) -> None:
    from opensquilla.sandbox.backend.windows_default_runner import _parse_payload

    payload = {
        "backend": "windows_restricted_token",
        "argv": ["cmd"],
        "cwd": str(tmp_path),
        "env": {},
        "policy": {"network": "none", "mounts": []},
        "runMode": "trusted",
        "timeout": 5,
    }

    with pytest.raises(SystemExit, match="expected backend windows_default"):
        _parse_payload([json.dumps(payload)])


def test_runner_rejects_proxy_allowlist_in_phase_one(tmp_path) -> None:
    from opensquilla.sandbox.backend.windows_default_runner import (
        _parse_payload,
        _validate_policy_is_enforceable,
    )

    payload = {
        "backend": "windows_default",
        "argv": ["cmd"],
        "cwd": str(tmp_path),
        "env": {},
        "policy": {"network": "proxy_allowlist", "mounts": []},
        "runMode": "trusted",
        "timeout": 5,
    }

    parsed = _parse_payload([json.dumps(payload)])

    with pytest.raises(SystemExit, match="Windows network boundary is pending"):
        _validate_policy_is_enforceable(parsed.policy)


def test_runner_applies_acl_refresh_before_process_launch(tmp_path, monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    calls = []
    payload = mod.HelperPayload(
        argv=("cmd", "/c", "echo ok"),
        cwd=tmp_path,
        env={},
        policy={
            "network": "none",
            "mounts": [],
            "windowsAclPlan": {
                "autoGrants": [
                    {
                        "path": str(tmp_path),
                        "access": "RWX",
                        "capabilitySid": "S-1-15-3-1",
                    }
                ],
                "capabilitySids": ["S-1-15-3-1"],
            },
        },
        run_mode="trusted",
        timeout=5,
    )

    monkeypatch.setattr(mod, "_apply_acl_refresh", lambda plan: calls.append(("acl", plan)))
    monkeypatch.setattr(
        mod,
        "_run_restricted_process_native",
        lambda payload, sids: calls.append(("run", sids)) or 0,
    )

    assert mod._run_windows_default(payload) == 0
    assert calls[0][0] == "acl"
    assert calls[1] == ("run", ("S-1-15-3-1",))


def test_runner_rejects_missing_acl_plan(tmp_path) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    payload = mod.HelperPayload(
        argv=("cmd",),
        cwd=tmp_path,
        env={},
        policy={"network": "none", "mounts": []},
        run_mode="trusted",
        timeout=5,
    )

    with pytest.raises(SystemExit, match="windowsAclPlan is required"):
        mod._run_windows_default(payload)
