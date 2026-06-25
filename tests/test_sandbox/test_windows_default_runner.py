from __future__ import annotations

import json
from pathlib import Path

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


def test_parse_payload_accepts_payload_from_environment(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    payload = {
        "backend": "windows_default",
        "argv": ["cmd", "/c", "echo ok"],
        "cwd": str(tmp_path),
        "env": {},
        "policy": {
            "network": "none",
            "mounts": [],
            "windowsAclPlan": {"autoGrants": [], "capabilitySids": []},
        },
        "runMode": "trusted",
        "timeout": 5,
        "offlineChild": True,
    }
    monkeypatch.setenv(mod.OFFLINE_PAYLOAD_ENV, json.dumps(payload))

    parsed = mod._parse_payload(["--payload-env"])

    assert parsed.argv == ("cmd", "/c", "echo ok")
    assert parsed.offline_child is True


def test_parse_payload_accepts_payload_from_file(tmp_path) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    payload = {
        "backend": "windows_default",
        "argv": ["cmd", "/c", "echo ok"],
        "cwd": str(tmp_path),
        "env": {},
        "policy": {
            "network": "none",
            "mounts": [],
            "windowsAclPlan": {"autoGrants": [], "capabilitySids": []},
        },
        "runMode": "trusted",
        "timeout": 5,
        "offlineChild": True,
    }
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    parsed = mod._parse_payload(["--payload-file", str(payload_path)])

    assert parsed.argv == ("cmd", "/c", "echo ok")
    assert parsed.offline_child is True


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


def test_runner_rejects_proxy_allowlist_without_proxy_endpoint(tmp_path) -> None:
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

    with pytest.raises(SystemExit, match="requires network_proxy"):
        _validate_policy_is_enforceable(parsed.policy)


def test_runner_accepts_proxy_allowlist_with_proxy_endpoint(tmp_path) -> None:
    from opensquilla.sandbox.backend.windows_default_runner import (
        _parse_payload,
        _validate_policy_is_enforceable,
    )

    payload = {
        "backend": "windows_default",
        "argv": ["cmd"],
        "cwd": str(tmp_path),
        "env": {
            "HTTP_PROXY": "http://127.0.0.1:48123",
            "HTTPS_PROXY": "http://127.0.0.1:48123",
            "NO_PROXY": "",
        },
        "policy": {
            "network": "proxy_allowlist",
            "network_proxy": {"host": "127.0.0.1", "port": 48123},
            "windowsNetworkBoundary": {
                "offlineUserSid": "S-1-5-21-100-200-300-400",
                "allowedProxyPorts": [48123],
                "allowLocalBinding": False,
            },
            "mounts": [],
        },
        "runMode": "trusted",
        "timeout": 5,
    }

    parsed = _parse_payload([json.dumps(payload)])

    _validate_policy_is_enforceable(parsed.policy)


def test_runner_rejects_proxy_allowlist_without_windows_network_boundary(tmp_path) -> None:
    from opensquilla.sandbox.backend.windows_default_runner import (
        _parse_payload,
        _validate_policy_is_enforceable,
    )

    payload = {
        "backend": "windows_default",
        "argv": ["cmd"],
        "cwd": str(tmp_path),
        "env": {},
        "policy": {
            "network": "proxy_allowlist",
            "network_proxy": {"host": "127.0.0.1", "port": 48123},
            "mounts": [],
        },
        "runMode": "trusted",
        "timeout": 5,
    }

    parsed = _parse_payload([json.dumps(payload)])

    with pytest.raises(SystemExit, match="windowsNetworkBoundary"):
        _validate_policy_is_enforceable(parsed.policy)


def test_runner_accepts_proxy_allowlist_with_matching_network_boundary(tmp_path) -> None:
    from opensquilla.sandbox.backend.windows_default_runner import (
        _parse_payload,
        _validate_policy_is_enforceable,
    )

    payload = {
        "backend": "windows_default",
        "argv": ["cmd"],
        "cwd": str(tmp_path),
        "env": {},
        "policy": {
            "network": "proxy_allowlist",
            "network_proxy": {"host": "127.0.0.1", "port": 48123},
            "windowsNetworkBoundary": {
                "offlineUserSid": "S-1-5-21-100-200-300-400",
                "allowedProxyPorts": [48123],
                "allowLocalBinding": False,
            },
            "mounts": [],
        },
        "runMode": "trusted",
        "timeout": 5,
    }

    parsed = _parse_payload([json.dumps(payload)])

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


def test_restricting_sid_specs_match_codex_legacy_base() -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    sid_specs = mod._base_restricting_sid_specs()
    sid_values = {sid for sid, _label in sid_specs}

    assert "S-1-1-0" in sid_values
    assert "S-1-5-11" not in sid_values
    assert "S-1-5-32-545" not in sid_values
    assert "S-1-5-12" not in sid_values


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
        def WriteFile(self, handle, data, size, written_ptr, overlapped):  # noqa: N802
            calls.append(("write", handle, bytes(data[:size])))
            written_ptr._obj.value = size
            return 1

        def CloseHandle(self, handle):  # noqa: N802
            calls.append(("close", handle))
            return 1

    mod._write_child_stdin(FakeKernel32(), 42, b"abc")

    assert calls == [("write", 42, b"abc"), ("close", 42)]


def test_runner_uses_offline_token_for_proxy_allowlist(monkeypatch, tmp_path) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    payload = mod.HelperPayload(
        argv=("cmd",),
        cwd=tmp_path,
        env={},
        policy={
            "network": "proxy_allowlist",
            "network_proxy": {"host": "127.0.0.1", "port": 48123},
            "windowsNetworkBoundary": {
                "offlineUserSid": "S-1-5-21-100-200-300-400",
                "offlineUsername": "OpenSquillaSandbox",
                "protectedPassword": "base64-dpapi-payload",
                "allowedProxyPorts": [48123],
                "allowLocalBinding": False,
            },
        },
        run_mode="trusted",
        timeout=5,
    )
    calls: list[str] = []

    monkeypatch.setattr(
        mod,
        "_open_current_process_token",
        lambda: calls.append("current") or 11,
    )

    def fake_logon(identity):
        calls.append(identity.username)
        return 22

    import opensquilla.sandbox.backend.windows_default_identity as identity_mod

    monkeypatch.setattr(identity_mod, "logon_offline_identity", fake_logon)

    assert mod._open_source_token_for_payload(payload) == 22
    assert calls == ["OpenSquillaSandbox"]


def test_proxy_allowlist_reexecs_helper_under_offline_identity(
    monkeypatch, tmp_path
) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    payload = mod.HelperPayload(
        argv=("cmd",),
        cwd=tmp_path,
        env={},
        policy={
            "network": "proxy_allowlist",
            "network_proxy": {"host": "127.0.0.1", "port": 48123},
            "windowsAclPlan": {"autoGrants": [], "capabilitySids": []},
            "windowsNetworkBoundary": {
                "offlineUserSid": "S-1-5-21-100-200-300-400",
                "offlineUsername": "OpenSquillaSandbox",
                "protectedPassword": "base64-dpapi-payload",
                "allowedProxyPorts": [48123],
                "allowLocalBinding": False,
            },
        },
        run_mode="trusted",
        timeout=5,
    )
    calls: list[mod.HelperPayload] = []

    monkeypatch.setattr(mod, "_apply_acl_refresh", lambda _plan: None)
    monkeypatch.setattr(
        mod,
        "_run_payload_as_offline_identity",
        lambda request: calls.append(request) or 7,
        raising=False,
    )
    monkeypatch.setattr(
        mod,
        "_run_restricted_process_native",
        lambda *_args: pytest.fail("offline parent must not launch final process"),
    )

    assert mod._run_windows_default(payload) == 7
    assert calls == [payload]


def test_offline_identity_launch_grants_helper_runtime_rx(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    payload = mod.HelperPayload(
        argv=("cmd",),
        cwd=tmp_path,
        env={},
        policy={
            "network": "proxy_allowlist",
            "network_proxy": {"host": "127.0.0.1", "port": 48123},
            "windowsAclPlan": {"autoGrants": [], "capabilitySids": []},
            "windowsNetworkBoundary": {
                "offlineUserSid": "S-1-5-21-100-200-300-400",
                "offlineUsername": "OpenSquillaSandbox",
                "protectedPassword": "base64-dpapi-payload",
                "allowedProxyPorts": [48123],
                "allowLocalBinding": False,
            },
        },
        run_mode="trusted",
        timeout=5,
    )
    runtime_root = tmp_path / "runtime-python"
    import_root = tmp_path / "src"
    runtime_root.mkdir()
    import_root.mkdir()
    grants: list[tuple[Path, str, str]] = []

    monkeypatch.setattr(
        mod,
        "_offline_helper_runtime_roots",
        lambda: (runtime_root, import_root),
        raising=False,
    )
    monkeypatch.setattr(
        mod,
        "_grant_path_to_sid",
        lambda path, access, sid: grants.append((path, access, sid)),
    )
    import opensquilla.sandbox.backend.windows_default_identity as identity_mod

    monkeypatch.setattr(identity_mod, "unprotect_password", lambda _value: "plain")
    monkeypatch.setattr(
        mod,
        "_run_payload_as_offline_identity_native",
        lambda request, *, username, password: 9,
    )

    assert mod._run_payload_as_offline_identity(payload) == 9

    assert grants == [
        (runtime_root, "RX", "S-1-5-21-100-200-300-400"),
        (import_root, "RX", "S-1-5-21-100-200-300-400"),
    ]


def test_offline_identity_launch_grants_payload_acl_roots_to_offline_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    payload = mod.HelperPayload(
        argv=("cmd",),
        cwd=tmp_path,
        env={},
        policy={
            "network": "proxy_allowlist",
            "network_proxy": {"host": "127.0.0.1", "port": 48123},
            "windowsAclPlan": {
                "autoGrants": [
                    {
                        "path": str(tmp_path),
                        "access": "RWX",
                        "kind": "required",
                        "capabilitySid": "S-1-15-3-100-200-300",
                    }
                ],
                "capabilitySids": ["S-1-15-3-100-200-300"],
            },
            "windowsNetworkBoundary": {
                "offlineUserSid": "S-1-5-21-100-200-300-400",
                "offlineUsername": "OpenSquillaSandbox",
                "protectedPassword": "base64-dpapi-payload",
                "allowedProxyPorts": [48123],
                "allowLocalBinding": False,
            },
        },
        run_mode="trusted",
        timeout=5,
    )
    grants: list[tuple[Path, str, str]] = []

    monkeypatch.setattr(mod, "_offline_helper_runtime_roots", lambda: (), raising=False)
    monkeypatch.setattr(
        mod,
        "_grant_path_to_sid",
        lambda path, access, sid: grants.append((path, access, sid)),
    )
    import opensquilla.sandbox.backend.windows_default_identity as identity_mod

    monkeypatch.setattr(identity_mod, "unprotect_password", lambda _value: "plain")
    monkeypatch.setattr(
        mod,
        "_run_payload_as_offline_identity_native",
        lambda request, *, username, password: 9,
    )

    assert mod._run_payload_as_offline_identity(payload) == 9

    assert grants == [(tmp_path, "RWX", "S-1-5-21-100-200-300-400")]


def test_offline_identity_native_launch_sets_all_stdio_handles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import ctypes
    import os
    import sys

    if not sys.platform.startswith("win"):
        pytest.skip("native offline identity launch only runs on Windows")

    import msvcrt

    from opensquilla.sandbox.backend import windows_default_runner as mod

    payload = mod.HelperPayload(
        argv=("cmd", "/c", "echo ok"),
        cwd=tmp_path,
        env={},
        policy={
            "network": "proxy_allowlist",
            "network_proxy": {"host": "127.0.0.1", "port": 48123},
            "windowsAclPlan": {"autoGrants": [], "capabilitySids": []},
            "windowsNetworkBoundary": {
                "offlineUserSid": "S-1-5-21-100-200-300-400",
                "offlineUsername": "OpenSquillaSandbox",
                "protectedPassword": "base64-dpapi-payload",
                "allowedProxyPorts": [48123],
                "allowLocalBinding": False,
            },
        },
        run_mode="trusted",
        timeout=5,
    )
    captured: dict[str, object] = {}
    next_handle = 1000

    def _handle_value(value: object) -> int:
        return int(getattr(value, "value", value) or 0)

    def _new_handle() -> int:
        nonlocal next_handle
        next_handle += 1
        return next_handle

    class FakeFunction:
        def __init__(self, func):
            self._func = func
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self._func(*args)

    def _create_pipe(read_handle, write_handle, _security_attributes, _size):
        read_handle._obj.value = _new_handle()
        write_handle._obj.value = _new_handle()
        return 1

    def _create_process_with_logon(
        _username,
        _domain,
        _password,
        _logon_flags,
        _application_name,
        _command_line,
        _creation_flags,
        _environment,
        _cwd,
        startup,
        process_info,
    ):
        captured["command_line"] = _command_line.value
        captured["env_block"] = "" if _environment is None else "".join(_environment)
        startup_info = startup._obj
        captured["stdin"] = _handle_value(startup_info.hStdInput)
        captured["stdout"] = _handle_value(startup_info.hStdOutput)
        captured["stderr"] = _handle_value(startup_info.hStdError)
        if not all(captured.values()):
            return 0
        process_info._obj.hProcess = _new_handle()
        process_info._obj.hThread = _new_handle()
        return 1

    def _get_exit_code_process(_process, code):
        code._obj.value = 0
        return 1

    class FakeAdvapi32:
        def __init__(self):
            self.CreateProcessWithLogonW = FakeFunction(_create_process_with_logon)

    class FakeKernel32:
        def __init__(self):
            self.CreatePipe = FakeFunction(_create_pipe)
            self.SetHandleInformation = FakeFunction(lambda *_args: 1)
            self.CloseHandle = FakeFunction(lambda *_args: 1)
            self.WaitForSingleObject = FakeFunction(lambda *_args: 0)
            self.TerminateProcess = FakeFunction(lambda *_args: 1)
            self.GetExitCodeProcess = FakeFunction(_get_exit_code_process)
            self.SetErrorMode = FakeFunction(lambda *_args: 0)

    fake_advapi32 = FakeAdvapi32()
    fake_kernel32 = FakeKernel32()

    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda name, **_kwargs: fake_advapi32 if name == "advapi32" else fake_kernel32,
    )
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 87)
    monkeypatch.setattr(ctypes, "FormatError", lambda code: "The parameter is incorrect.")
    monkeypatch.setattr(
        msvcrt,
        "open_osfhandle",
        lambda _handle, _flags: os.open(os.devnull, os.O_RDONLY),
    )

    assert (
        mod._run_payload_as_offline_identity_native(
            payload,
            username="OpenSquillaSandbox",
            password="secret",
        )
        == 0
    )
    assert captured["stdin"]
    assert captured["stdout"]
    assert captured["stderr"]
    assert "--payload-file" in captured["command_line"]
    assert "--payload-env" not in captured["command_line"]
    assert mod.OFFLINE_PAYLOAD_ENV not in captured["env_block"]


def test_offline_reexecuted_helper_uses_current_token(monkeypatch, tmp_path) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    payload = mod.HelperPayload(
        argv=("cmd",),
        cwd=tmp_path,
        env={},
        policy={
            "network": "proxy_allowlist",
            "network_proxy": {"host": "127.0.0.1", "port": 48123},
            "windowsAclPlan": {"autoGrants": [], "capabilitySids": []},
            "windowsNetworkBoundary": {
                "offlineUserSid": "S-1-5-21-100-200-300-400",
                "offlineUsername": "OpenSquillaSandbox",
                "protectedPassword": "base64-dpapi-payload",
                "allowedProxyPorts": [48123],
                "allowLocalBinding": False,
            },
        },
        run_mode="trusted",
        timeout=5,
        offline_child=True,
    )
    calls: list[str] = []

    monkeypatch.setattr(
        mod,
        "_open_current_process_token",
        lambda: calls.append("current") or 11,
    )

    assert mod._open_source_token_for_payload(payload) == 11
    assert calls == ["current"]


def test_restricted_process_creation_flags_hide_error_windows() -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    flags = mod._restricted_process_creation_flags()

    assert flags & mod.CREATE_NO_WINDOW
    assert flags & mod.CREATE_UNICODE_ENVIRONMENT
    assert flags & mod.CREATE_SUSPENDED
    assert mod._restricted_process_startup_flags() & mod.STARTF_USESHOWWINDOW
    assert mod._runner_error_mode_flags() & mod.SEM_NOOPENFILEERRORBOX


def test_restricted_process_application_name_uses_absolute_executable() -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    powershell = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

    assert mod._restricted_process_application_name((powershell, "-NoProfile")) == powershell
    assert mod._restricted_process_application_name(("powershell.exe", "-NoProfile")) is None


def test_restricted_token_includes_source_user_sid_in_restricting_sids() -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    assert mod._ordered_restricting_sids(
        capability_sids=("cap",),
        user_sid="user",
        logon_sid="logon",
        base_sids=("everyone",),
    ) == ("cap", "user", "logon", "everyone")


def test_runner_overrides_proxy_env_for_proxy_allowlist(tmp_path) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    payload = mod.HelperPayload(
        argv=("cmd",),
        cwd=tmp_path,
        env={
            "HTTP_PROXY": "http://attacker.invalid:1",
            "HTTPS_PROXY": "http://attacker.invalid:1",
            "NO_PROXY": "localhost",
        },
        policy={
            "network": "proxy_allowlist",
            "network_proxy": {"host": "127.0.0.1", "port": 48123},
            "windowsNetworkBoundary": {
                "offlineUserSid": "S-1-5-21-100-200-300-400",
                "offlineUsername": "OpenSquillaSandbox",
                "protectedPassword": "protected",
                "allowedProxyPorts": [48123],
                "allowLocalBinding": False,
            },
        },
        run_mode="trusted",
        timeout=5,
    )

    env = mod._effective_child_env(payload)

    assert env["HTTP_PROXY"] == "http://127.0.0.1:48123"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:48123"
    assert env["http_proxy"] == "http://127.0.0.1:48123"
    assert env["https_proxy"] == "http://127.0.0.1:48123"
    assert env["ALL_PROXY"] == "http://127.0.0.1:48123"
    assert env["all_proxy"] == "http://127.0.0.1:48123"
    assert env["npm_config_https_proxy"] == "http://127.0.0.1:48123"
    assert env["NPM_CONFIG_HTTPS_PROXY"] == "http://127.0.0.1:48123"
    assert env["PIP_PROXY"] == "http://127.0.0.1:48123"
    assert env["NODE_USE_ENV_PROXY"] == "1"
    assert env["NO_PROXY"]
    assert env["no_proxy"] == env["NO_PROXY"]


def test_runner_injects_git_safe_directory_after_existing_git_config(tmp_path) -> None:
    from opensquilla.sandbox.backend import windows_default_runner as mod

    (tmp_path / ".git").mkdir()
    payload = mod.HelperPayload(
        argv=("git", "status"),
        cwd=tmp_path,
        env={
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.sslBackend",
            "GIT_CONFIG_VALUE_0": "openssl",
        },
        policy={
            "network": "none",
            "windowsAclPlan": {"autoGrants": [], "capabilitySids": []},
        },
        run_mode="trusted",
        timeout=5,
    )

    env = mod._effective_child_env(payload)

    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_KEY_0"] == "http.sslBackend"
    assert env["GIT_CONFIG_VALUE_0"] == "openssl"
    assert env["GIT_CONFIG_KEY_1"] == "safe.directory"
    assert env["GIT_CONFIG_VALUE_1"] == str(tmp_path).replace("\\", "/")
