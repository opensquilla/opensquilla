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
