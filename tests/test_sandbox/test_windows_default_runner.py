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


def test_parse_payload_decodes_stdin_base64(tmp_path) -> None:
    from opensquilla.sandbox.backend.windows_default_runner import _parse_payload

    payload = {
        "backend": "windows_default",
        "argv": ["cmd", "/c", "more"],
        "cwd": str(tmp_path),
        "env": {},
        "policy": {
            "network": "none",
            "mounts": [],
            "windowsAclPlan": {"autoGrants": [], "capabilitySids": []},
        },
        "runMode": "trusted",
        "timeout": 5,
        "stdinBase64": "YWJjMTIz",
    }

    parsed = _parse_payload([json.dumps(payload)])

    assert parsed.stdin == b"abc123"


def test_parse_payload_rejects_wrong_backend(tmp_path) -> None:
    from opensquilla.sandbox.backend.windows_default_runner import _parse_payload

    payload = {
        "backend": "not_windows_default",
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
                        "capabilitySid": "S-1-5-21-100-101-102-103",
                    }
                ],
                "capabilitySids": ["S-1-5-21-100-101-102-103"],
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
    assert calls[1] == ("run", ("S-1-5-21-100-101-102-103",))


def test_grant_path_to_sid_uses_native_acl_writer(tmp_path, monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    calls = []

    def fail_subprocess(*args, **kwargs):  # pragma: no cover - only reached on regression
        raise AssertionError("icacls must not be used for random restricting SIDs")

    monkeypatch.setattr(mod.subprocess, "run", fail_subprocess)
    monkeypatch.setattr(
        mod,
        "_grant_path_to_sid_native",
        lambda path, access, sid: calls.append((path, access, sid)),
    )

    mod._grant_path_to_sid(tmp_path, "RWX", "S-1-5-21-100-101-102-103")

    assert calls == [(tmp_path, "RWX", "S-1-5-21-100-101-102-103")]


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


def test_restricted_token_flags_match_codex_legacy() -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    assert mod.RESTRICTED_TOKEN_FLAGS == (
        mod.DISABLE_MAX_PRIVILEGE | mod.LUA_TOKEN | mod.WRITE_RESTRICTED
    )


def test_token_post_create_hooks_are_called(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    calls = []

    monkeypatch.setattr(
        mod,
        "_set_token_default_dacl",
        lambda token, sids: calls.append(("default_dacl", token, tuple(sids))),
    )
    monkeypatch.setattr(
        mod,
        "_enable_token_privilege",
        lambda token, name: calls.append(("privilege", token, name)),
    )

    mod._finalize_restricted_token(
        token=123,
        dacl_sids=("logon", "everyone", "cap-a"),
    )

    assert calls == [
        ("default_dacl", 123, ("logon", "everyone", "cap-a")),
        ("privilege", 123, "SeChangeNotifyPrivilege"),
    ]


def test_child_stdin_writer_writes_payload_and_closes(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    calls = []

    class FakeKernel32:
        def WriteFile(self, handle, data, size, written_ptr, overlapped):
            calls.append(("write", handle, bytes(data[:size])))
            written_ptr._obj.value = size
            return 1

        def CloseHandle(self, handle):
            calls.append(("close", handle))
            return 1

    mod._write_child_stdin(FakeKernel32(), 42, b"abc")

    assert calls == [("write", 42, b"abc"), ("close", 42)]
