from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, get_runtime, reset_runtime
from opensquilla.sandbox.run_context import (
    DomainGrant,
    PackageBundleGrant,
    RunContext,
    TemporaryGrant,
)
from opensquilla.sandbox.run_mode import RunMode
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


@pytest.fixture
def managed_runtime(tmp_path: Path) -> Iterator[Path]:
    reset_approval_queue()
    configure_runtime(
        SandboxSettings(
            run_mode="standard",
            backend="noop",
            allow_legacy_mode=True,
            network_default="proxy_allowlist",
        ),
        workspace=tmp_path,
    )
    try:
        yield tmp_path
    finally:
        reset_runtime()
        reset_approval_queue()


@pytest.fixture
def standard_runtime_no_preflight(tmp_path: Path) -> Iterator[Path]:
    reset_approval_queue()
    configure_runtime(
        SandboxSettings(
            run_mode="standard",
            backend="noop",
            allow_legacy_mode=True,
            network_default="none",
        ),
        workspace=tmp_path,
    )
    try:
        yield tmp_path
    finally:
        reset_runtime()
        reset_approval_queue()


@pytest.mark.asyncio
async def test_shell_network_command_passes_network_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    from opensquilla.tools.builtin import shell

    calls: list[dict[str, object]] = []

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)

    async def _fake_gate_action(**kwargs):
        calls.append(kwargs)
        policy = SimpleNamespace()
        request = SimpleNamespace(cwd="/tmp", action_kind="shell.exec", policy=policy)
        return object(), policy, request

    async def _fake_run_under_backend(request, *, runtime=None):
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="", backend_notes=())

    monkeypatch.setattr(shell, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    result = await shell.exec_command("curl https://example.com")

    assert "ok" in result
    assert len(calls) == 1
    hints = calls[0]["hints"]
    assert hints.needs_network is True
    assert hints.high_impact is False


@pytest.mark.asyncio
async def test_shell_url_text_does_not_pass_network_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    calls: list[dict[str, object]] = []

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)

    async def _fake_gate_action(**kwargs):
        calls.append(kwargs)
        policy = SimpleNamespace()
        request = SimpleNamespace(cwd="/tmp", action_kind="shell.exec", policy=policy)
        return object(), policy, request

    async def _fake_run_under_backend(request, *, runtime=None):
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="", backend_notes=())

    monkeypatch.setattr(shell, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    result = await shell.exec_command("echo https://example.com")

    assert "ok" in result
    assert len(calls) == 1
    hints = calls[0]["hints"]
    assert hints.needs_network is False
    assert hints.high_impact is False


@pytest.mark.asyncio
async def test_code_with_url_literal_passes_network_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import code_exec, shell

    calls: list[dict[str, object]] = []

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)
        workspace = tmp_path

    async def _fake_gate_action(**kwargs):
        calls.append(kwargs)
        policy = SimpleNamespace()
        request = SimpleNamespace(cwd="/tmp", action_kind="code.exec", policy=policy)
        return object(), policy, request

    async def _fake_run_under_backend(request, *, runtime=None):
        return SimpleNamespace(
            returncode=0,
            stdout="ok\n",
            stderr="",
            timed_out=False,
            backend_notes=(),
        )

    monkeypatch.setattr(code_exec, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(code_exec, "gate_action", _fake_gate_action)
    monkeypatch.setattr(code_exec, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(code_exec, "_resolve_python_bin", lambda *, sandbox_enabled: sys.executable)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)

    result = json.loads(
        await code_exec.execute_code('import requests\nrequests.get("https://example.com")')
    )

    assert result["stdout"] == "ok\n"
    assert len(calls) == 1
    hints = calls[0]["hints"]
    assert hints.needs_network is True
    assert hints.high_impact is False


@pytest.mark.asyncio
async def test_code_plain_url_literal_does_not_pass_network_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import code_exec, shell

    calls: list[dict[str, object]] = []

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)
        workspace = tmp_path

    async def _fake_gate_action(**kwargs):
        calls.append(kwargs)
        policy = SimpleNamespace()
        request = SimpleNamespace(cwd="/tmp", action_kind="code.exec", policy=policy)
        return object(), policy, request

    async def _fake_run_under_backend(request, *, runtime=None):
        return SimpleNamespace(
            returncode=0,
            stdout="ok\n",
            stderr="",
            timed_out=False,
            backend_notes=(),
        )

    monkeypatch.setattr(code_exec, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(code_exec, "gate_action", _fake_gate_action)
    monkeypatch.setattr(code_exec, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(code_exec, "_resolve_python_bin", lambda *, sandbox_enabled: sys.executable)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)

    result = json.loads(await code_exec.execute_code('print("https://example.com")'))

    assert result["stdout"] == "ok\n"
    assert len(calls) == 1
    hints = calls[0]["hints"]
    assert hints.needs_network is False
    assert hints.high_impact is False


@pytest.mark.asyncio
async def test_shell_unknown_explicit_url_queues_network_approval_before_proxy_run(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    async def _fail_run_under_backend(request, *, runtime=None):
        pytest.fail("network approval preflight should run before proxy execution")

    monkeypatch.setattr(shell, "run_under_backend", _fail_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(run_mode=RunMode.STANDARD),
        )
    )
    try:
        payload = json.loads(
            await shell.exec_command(
                "curl https://unknown.test/path",
                workdir=str(managed_runtime),
            )
        )
    finally:
        current_tool_context.reset(token)

    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_network"
    assert payload["host"] == "unknown.test"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["host"] == "unknown.test"


@pytest.mark.asyncio
async def test_windows_proxy_allowlist_runtime_skips_platform_network_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.sandbox.types import (
        NetworkMode,
        NetworkProxySpec,
        ResourceLimits,
        SandboxPolicy,
        SandboxRequest,
        SecurityLevel,
    )

    events = []

    async def fake_prepare_boundary(request, runtime):
        events.append(("prepare", request.policy.network_proxy.port))
        return "ctx"

    async def fake_cleanup_boundary(ctx):
        events.append(("cleanup", ctx))

    class Backend:
        name = "windows_default"

        async def run(self, request):
            events.append(("run", request.policy.network_proxy.port))
            return SimpleNamespace(returncode=0, stdout="ok", stderr="", backend_notes=())

    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.PROXY_ALLOWLIST,
        network_proxy=NetworkProxySpec(host="127.0.0.1", port=48123),
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=30),
        env_allowlist=("PATH",),
        require_approval=False,
    )
    request = SandboxRequest(
        argv=("python", "-m", "pip", "install", "humanize"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        env={"PATH": "x"},
    )
    runtime = SimpleNamespace(backend=Backend())

    monkeypatch.setattr(
        integration_mod,
        "_prepare_platform_network_boundary",
        fake_prepare_boundary,
    )
    monkeypatch.setattr(
        integration_mod,
        "_cleanup_platform_network_boundary",
        fake_cleanup_boundary,
    )

    result = await integration_mod.run_under_backend(request, runtime=runtime)

    assert result.stdout == "ok"
    assert events == [("run", 48123)]


@pytest.mark.asyncio
async def test_windows_unready_proxy_allowlist_blocks_network_workarounds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.sandbox.types import (
        NetworkMode,
        ResourceLimits,
        SandboxPolicy,
        SandboxRequest,
        SecurityLevel,
    )

    class _Ledger:
        async def record_denial(self, *args: object, **kwargs: object) -> None:
            return None

    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.PROXY_ALLOWLIST,
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=30),
        env_allowlist=("PATH",),
        require_approval=False,
    )
    request = SandboxRequest(
        argv=("powershell", "-Command", "python -m pip install humanize"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        env={"PATH": r"C:\Windows\System32"},
    )
    runtime = SimpleNamespace(
        backend=SimpleNamespace(name="windows_default"),
        workspace=tmp_path,
        ledger=_Ledger(),
    )

    monkeypatch.setattr(
        integration_mod,
        "_windows_proxy_allowlist_enforced",
        lambda runtime: False,
    )

    result = await integration_mod.preflight_subprocess_managed_network(
        request,
        runtime,
    )

    assert result is not None
    assert not isinstance(result, dict)
    assert result.retryable is False
    assert "Windows sandbox managed network is unavailable" in result.message
    assert "PROXY_ALLOWLIST" in result.message
    assert "Do not retry with http_request" in result.message
    assert "Do not retry with web_fetch" in result.message
    assert "Do not retry with offline wheel downloads" in result.message
    assert "Do not retry with host Python" in result.message


@pytest.mark.asyncio
async def test_shell_package_install_queues_bundle_approval_before_proxy_run(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    async def _fail_run_under_backend(request, *, runtime=None):
        pytest.fail("package bundle approval should run before proxy execution")

    monkeypatch.setattr(shell, "run_under_backend", _fail_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(run_mode=RunMode.STANDARD),
        )
    )
    try:
        payload = json.loads(
            await shell.exec_command(
                "pip install requests",
                workdir=str(managed_runtime),
            )
        )
    finally:
        current_tool_context.reset(token)

    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_network"
    assert payload["bundle_id"] == "python-package-install"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["bundle_id"] == "python-package-install"


@pytest.mark.asyncio
async def test_uv_pip_install_queues_bundle_approval_before_proxy_run(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    async def _fail_run_under_backend(request, *, runtime=None):
        pytest.fail("uv pip package bundle approval should run before proxy execution")

    monkeypatch.setattr(shell, "run_under_backend", _fail_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(run_mode=RunMode.STANDARD),
        )
    )
    try:
        payload = json.loads(
            await shell.exec_command(
                "uv pip install --no-cache-dir httpx[http2] pendulum",
                workdir=str(managed_runtime),
            )
        )
    finally:
        current_tool_context.reset(token)

    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_network"
    assert payload["bundle_id"] == "python-package-install"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["bundle_id"] == "python-package-install"


@pytest.mark.asyncio
async def test_poetry_install_queues_python_bundle_before_proxy_run(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.tools.builtin import shell

    profile_calls: list[tuple[str, ...]] = []

    async def _fail_run_under_backend(request, *, runtime=None):
        pytest.fail("poetry package bundle approval should run before proxy execution")

    def _fake_capability_profile_for_command(argv):
        profile_calls.append(tuple(argv))
        return SimpleNamespace(package_bundles=("python-package-install",))

    monkeypatch.setattr(
        integration_mod,
        "capability_profile_for_command",
        _fake_capability_profile_for_command,
    )
    monkeypatch.setattr(shell, "run_under_backend", _fail_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(run_mode=RunMode.STANDARD),
        )
    )
    try:
        payload = json.loads(
            await shell.exec_command(
                "poetry install",
                workdir=str(managed_runtime),
            )
        )
    finally:
        current_tool_context.reset(token)

    assert profile_calls == [("sh", "-lc", "poetry install")]
    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_network"
    assert payload["bundle_id"] == "python-package-install"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["bundle_id"] == "python-package-install"


@pytest.mark.asyncio
async def test_composer_install_queues_php_bundle_before_proxy_run(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.tools.builtin import shell

    profile_calls: list[tuple[str, ...]] = []

    async def _fail_run_under_backend(request, *, runtime=None):
        pytest.fail("composer package bundle approval should run before proxy execution")

    def _fake_capability_profile_for_command(argv):
        profile_calls.append(tuple(argv))
        return SimpleNamespace(package_bundles=("php-package-install",))

    monkeypatch.setattr(
        integration_mod,
        "capability_profile_for_command",
        _fake_capability_profile_for_command,
    )
    monkeypatch.setattr(shell, "run_under_backend", _fail_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(run_mode=RunMode.STANDARD),
        )
    )
    try:
        payload = json.loads(
            await shell.exec_command(
                "composer install",
                workdir=str(managed_runtime),
            )
        )
    finally:
        current_tool_context.reset(token)

    assert profile_calls == [("sh", "-lc", "composer install")]
    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_network"
    assert payload["bundle_id"] == "php-package-install"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["bundle_id"] == "php-package-install"


@pytest.mark.asyncio
async def test_trusted_uv_pip_install_receives_managed_proxy_without_prompt(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.tools.builtin import shell

    class _FakeProxyServer:
        host = "127.0.0.1"
        port = 48123

        def __init__(self, *args, **kwargs) -> None:
            return None

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    seen: dict[str, object] = {}

    async def _fake_run_under_backend(request, *, runtime=None):
        managed = await integration_mod.prepare_subprocess_managed_network_proxy(
            request,
            runtime=runtime,
        )
        try:
            seen["env"] = managed.request.env
            seen["policy"] = managed.request.policy
            return SimpleNamespace(returncode=0, stdout="installed\n", stderr="", backend_notes=())
        finally:
            await managed.cleanup()

    monkeypatch.setattr(integration_mod, "SandboxProxyServer", _FakeProxyServer)
    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = await shell.exec_command(
            "uv pip install --no-cache-dir httpx[http2] pendulum",
            workdir=str(managed_runtime),
        )
    finally:
        current_tool_context.reset(token)

    assert "installed" in result
    assert get_approval_queue().list_pending("exec") == []
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["HTTP_PROXY"] == "http://127.0.0.1:48123"
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"]


@pytest.mark.asyncio
async def test_trusted_unknown_install_uses_managed_proxy_without_redundant_retry(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.types import SandboxRequest
    from opensquilla.tools.builtin import shell

    backend_calls: list[SandboxRequest] = []
    cleanup_calls = 0

    async def _fake_run_under_backend(request, *, runtime=None):
        backend_calls.append(request)
        if len(backend_calls) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="curl: (6) Could not resolve host: pypi.org\n",
                backend_notes=(),
            )
        return SimpleNamespace(
            returncode=0,
            stdout="installed\n",
            stderr="",
            backend_notes=(),
        )

    async def _fake_prepare_subprocess_managed_network_proxy(request, *, runtime=None):
        managed_env = dict(request.env)
        managed_env["HTTP_PROXY"] = "http://127.0.0.1:48123"
        managed_env["HTTPS_PROXY"] = managed_env["HTTP_PROXY"]
        managed_request = SandboxRequest(
            argv=request.argv,
            cwd=request.cwd,
            action_kind=request.action_kind,
            policy=request.policy,
            stdin=request.stdin,
            env=managed_env,
            reason=request.reason,
        )

        async def _cleanup() -> None:
            nonlocal cleanup_calls
            cleanup_calls += 1

        return SimpleNamespace(request=managed_request, cleanup=_cleanup)

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "prepare_subprocess_managed_network_proxy",
        _fake_prepare_subprocess_managed_network_proxy,
    )
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = await shell.exec_command("pip install demo", workdir=str(managed_runtime))
    finally:
        current_tool_context.reset(token)

    assert "Could not resolve host: pypi.org" in result
    assert len(backend_calls) == 1
    assert backend_calls[0].env["HTTP_PROXY"] == "http://127.0.0.1:48123"
    assert cleanup_calls == 1


@pytest.mark.asyncio
async def test_standard_runtime_network_recovery_returns_package_bundle_approval(
    standard_runtime_no_preflight: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    backend_calls = 0

    async def _fake_run_under_backend(request, *, runtime=None):
        nonlocal backend_calls
        backend_calls += 1
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="curl: (6) Could not resolve host: pypi.org\n",
            backend_notes=(),
        )

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(standard_runtime_no_preflight),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(run_mode=RunMode.STANDARD),
        )
    )
    try:
        payload = json.loads(
            await shell.exec_command(
                "pip install demo",
                workdir=str(standard_runtime_no_preflight),
            )
        )
    finally:
        current_tool_context.reset(token)

    assert backend_calls == 1
    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_network"
    assert payload["bundle_id"] == "python-package-install"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["bundle_id"] == "python-package-install"


@pytest.mark.asyncio
async def test_standard_runtime_network_recovery_returns_host_approval_for_explicit_url(
    standard_runtime_no_preflight: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    backend_calls = 0

    async def _fake_run_under_backend(request, *, runtime=None):
        nonlocal backend_calls
        backend_calls += 1
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="curl: (6) Could not resolve host: unknown.test\n",
            backend_notes=(),
        )

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(standard_runtime_no_preflight),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(run_mode=RunMode.STANDARD),
        )
    )
    try:
        payload = json.loads(
            await shell.exec_command(
                "curl https://unknown.test/path",
                workdir=str(standard_runtime_no_preflight),
            )
        )
    finally:
        current_tool_context.reset(token)

    assert backend_calls == 1
    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_network"
    assert payload["host"] == "unknown.test"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["host"] == "unknown.test"


@pytest.mark.asyncio
async def test_standard_runtime_network_recovery_retries_once_with_approved_bundle(
    standard_runtime_no_preflight: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.types import NetworkMode, SandboxRequest
    from opensquilla.tools.builtin import shell

    backend_calls: list[SandboxRequest] = []
    cleanup_calls = 0

    async def _fake_run_under_backend(request, *, runtime=None):
        backend_calls.append(request)
        if len(backend_calls) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="curl: (6) Could not resolve host: pypi.org\n",
                backend_notes=(),
            )
        return SimpleNamespace(returncode=0, stdout="installed\n", stderr="", backend_notes=())

    async def _fake_prepare_subprocess_managed_network_proxy(request, *, runtime=None):
        managed_env = dict(request.env)
        managed_env["HTTP_PROXY"] = "http://127.0.0.1:48123"
        managed_env["HTTPS_PROXY"] = managed_env["HTTP_PROXY"]
        managed_request = SandboxRequest(
            argv=request.argv,
            cwd=request.cwd,
            action_kind=request.action_kind,
            policy=request.policy,
            stdin=request.stdin,
            env=managed_env,
            reason=request.reason,
        )

        async def _cleanup() -> None:
            nonlocal cleanup_calls
            cleanup_calls += 1

        return SimpleNamespace(request=managed_request, cleanup=_cleanup)

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "prepare_subprocess_managed_network_proxy",
        _fake_prepare_subprocess_managed_network_proxy,
    )
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(standard_runtime_no_preflight),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(
                run_mode=RunMode.STANDARD,
                workspace=str(standard_runtime_no_preflight),
                bundles=(PackageBundleGrant(bundle_id="python-package-install"),),
            ),
        )
    )
    try:
        result = await shell.exec_command(
            "pip install demo",
            workdir=str(standard_runtime_no_preflight),
        )
    finally:
        current_tool_context.reset(token)

    assert "installed" in result
    assert len(backend_calls) == 2
    assert cleanup_calls == 1
    assert backend_calls[0].policy.network is NetworkMode.NONE
    assert backend_calls[1].policy.network is NetworkMode.PROXY_ALLOWLIST
    assert backend_calls[1].env["HTTP_PROXY"] == "http://127.0.0.1:48123"
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_standard_runtime_network_recovery_preserves_allow_once_for_proxy_retry(
    standard_runtime_no_preflight: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.sandbox.types import (
        NetworkMode,
        ResourceLimits,
        SandboxPolicy,
        SandboxRequest,
        SecurityLevel,
    )
    from opensquilla.tools.builtin import shell

    command = "curl https://unknown.test/path"
    workdir = standard_runtime_no_preflight.resolve(strict=False)
    base_policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(),
        env_allowlist=("PATH",),
        require_approval=False,
    )
    approval_policy = SandboxPolicy(
        level=base_policy.level,
        network=NetworkMode.PROXY_ALLOWLIST,
        mounts=base_policy.mounts,
        workspace_rw=base_policy.workspace_rw,
        tmp_writable=base_policy.tmp_writable,
        limits=base_policy.limits,
        env_allowlist=base_policy.env_allowlist,
        require_approval=base_policy.require_approval,
        description=base_policy.description,
        network_proxy=base_policy.network_proxy,
    )
    approval_request = SandboxRequest(
        argv=("sh", "-lc", command),
        cwd=workdir,
        action_kind="shell.exec",
        policy=approval_policy,
        env=dict(os.environ),
    )

    class _FakeProxyServer:
        host = "127.0.0.1"
        port = 48123

        def __init__(self, decide, *args, **kwargs) -> None:
            self._decide = decide

        async def start(self) -> None:
            decision = self._decide("unknown.test")
            assert decision.status == "allow"

        async def stop(self) -> None:
            return None

    async def _fake_gate_action(**kwargs):
        request = SimpleNamespace(
            cwd=workdir,
            action_kind="shell.exec",
            policy=base_policy,
            reason="",
        )
        return object(), base_policy, request

    backend_calls: list[SandboxRequest] = []

    async def _fake_run_under_backend(request, *, runtime=None):
        backend_calls.append(request)
        if len(backend_calls) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="curl: (6) Could not resolve host: unknown.test\n",
                backend_notes=(),
            )
        return SimpleNamespace(returncode=0, stdout="downloaded\n", stderr="", backend_notes=())

    monkeypatch.setattr(integration_mod, "SandboxProxyServer", _FakeProxyServer)
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    grant = TemporaryGrant(
        kind="domain",
        value="unknown.test",
        fingerprint=integration_mod.action_fingerprint(approval_request),
    )
    run_context = RunContext(
        run_mode=RunMode.STANDARD,
        workspace=str(standard_runtime_no_preflight),
        temporary_grants=(grant,),
    )
    tool_context = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.CLI,
        workspace_dir=str(standard_runtime_no_preflight),
        session_key="s1",
        run_mode="standard",
        sandbox_run_context=run_context,
    )
    token = current_tool_context.set(tool_context)
    try:
        result = await shell.exec_command(command, workdir=str(standard_runtime_no_preflight))
    finally:
        current_tool_context.reset(token)

    assert "downloaded" in result
    assert len(backend_calls) == 2
    assert backend_calls[0].policy.network is NetworkMode.NONE
    assert backend_calls[1].policy.network is NetworkMode.PROXY_ALLOWLIST
    assert backend_calls[1].env["HTTP_PROXY"] == "http://127.0.0.1:48123"
    assert isinstance(tool_context.sandbox_run_context, RunContext)
    assert tool_context.sandbox_run_context.temporary_grants == ()
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_trusted_hostless_private_network_failure_does_not_retry(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    backend_calls = 0

    async def _fake_run_under_backend(request, *, runtime=None):
        nonlocal backend_calls
        backend_calls += 1
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Network is unreachable\n",
            backend_notes=(),
        )

    async def _fake_preflight_subprocess_managed_network(request, runtime):
        return None

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(shell, "_sensitive_shell_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        shell,
        "preflight_subprocess_managed_network",
        _fake_preflight_subprocess_managed_network,
    )
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = await shell.exec_command(
            "curl http://127.0.0.1:8000/",
            workdir=str(managed_runtime),
        )
    finally:
        current_tool_context.reset(token)

    assert backend_calls == 1
    assert "Network is unreachable" in result


@pytest.mark.asyncio
async def test_trusted_metadata_target_is_not_auto_retried(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    backend_calls = 0

    async def _fake_run_under_backend(request, *, runtime=None):
        nonlocal backend_calls
        backend_calls += 1
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Network is unreachable\n",
            backend_notes=(),
        )

    async def _fake_preflight_subprocess_managed_network(request, runtime):
        return None

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(shell, "_sensitive_shell_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        shell,
        "preflight_subprocess_managed_network",
        _fake_preflight_subprocess_managed_network,
    )
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = await shell.exec_command(
            "curl http://169.254.169.254/latest/meta-data/",
            workdir=str(managed_runtime),
        )
    finally:
        current_tool_context.reset(token)

    assert backend_calls == 1
    assert "exit_code=1" in result
    assert "Network is unreachable" in result
    assert "approval_required" not in result


@pytest.mark.asyncio
async def test_trusted_recovery_rewrites_retry_policy_to_managed_proxy(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.sandbox.types import NetworkMode
    from opensquilla.tools.builtin import shell

    class _FakeProxyServer:
        host = "127.0.0.1"
        port = 48123

        def __init__(self, *args, **kwargs) -> None:
            return None

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    async def _fake_gate_action(**kwargs):
        _, policy, request = await integration_mod.gate_action(**kwargs)
        policy = policy.__class__(
            level=policy.level,
            network=NetworkMode.NONE,
            mounts=policy.mounts,
            workspace_rw=policy.workspace_rw,
            tmp_writable=policy.tmp_writable,
            limits=policy.limits,
            env_allowlist=policy.env_allowlist,
            require_approval=policy.require_approval,
            description=policy.description,
            network_proxy=policy.network_proxy,
        )
        request = SimpleNamespace(
            cwd=request.cwd,
            action_kind=request.action_kind,
            policy=policy,
            reason=getattr(request, "reason", ""),
        )
        return object(), policy, request

    backend_calls = []

    async def _fake_run_under_backend(request, *, runtime=None):
        backend_calls.append(request)
        if len(backend_calls) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="curl: (6) Could not resolve host: pypi.org\n",
                backend_notes=(),
            )
        return SimpleNamespace(returncode=0, stdout="installed\n", stderr="", backend_notes=())

    monkeypatch.setattr(integration_mod, "SandboxProxyServer", _FakeProxyServer)
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = await shell.exec_command("pip install demo", workdir=str(managed_runtime))
    finally:
        current_tool_context.reset(token)

    assert "installed" in result
    assert len(backend_calls) == 2
    assert backend_calls[0].policy.network is NetworkMode.NONE
    assert backend_calls[1].policy.network is NetworkMode.PROXY_ALLOWLIST
    assert backend_calls[1].env["HTTP_PROXY"] == "http://127.0.0.1:48123"


@pytest.mark.asyncio
async def test_trusted_normal_user_path_denial_retries_once(
    managed_runtime: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.types import SandboxRequest
    from opensquilla.tools.builtin import shell

    outside = tmp_path_factory.mktemp("outside-project")
    backend_calls: list[SandboxRequest] = []

    async def _fake_run_under_backend(request, *, runtime=None):
        backend_calls.append(request)
        if len(backend_calls) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="",
                backend_notes=(f"mount denied: {outside}",),
            )
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="", backend_notes=())

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(shell, "_sensitive_shell_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_workdir_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_read_path_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_write_path_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = await shell.exec_command("python -m pip install -e .", workdir=str(outside))
    finally:
        current_tool_context.reset(token)

    assert "ok" in result
    assert len(backend_calls) == 2
    retry_mounts = backend_calls[1].policy.mounts
    assert any(
        mount.mode == "rw" and outside.resolve(strict=False).is_relative_to(mount.host_path)
        for mount in retry_mounts
    )


@pytest.mark.asyncio
async def test_trusted_read_path_denial_retries_with_ro_mount(
    managed_runtime: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.types import SandboxRequest
    from opensquilla.tools.builtin import shell

    outside = tmp_path_factory.mktemp("outside-read")
    target = outside / "data.txt"
    target.write_text("data\n", encoding="utf-8")
    backend_calls: list[SandboxRequest] = []

    async def _fake_run_under_backend(request, *, runtime=None):
        backend_calls.append(request)
        if len(backend_calls) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="",
                backend_notes=(f"filesystem.read.denied: {target}",),
            )
        return SimpleNamespace(returncode=0, stdout="data\n", stderr="", backend_notes=())

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(shell, "_sensitive_shell_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_read_path_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_write_path_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = await shell.exec_command("pip install demo", workdir=str(managed_runtime))
    finally:
        current_tool_context.reset(token)

    assert "data" in result
    assert len(backend_calls) == 2
    retry_mounts = backend_calls[1].policy.mounts
    assert any(
        mount.mode == "ro" and target.resolve(strict=False).is_relative_to(mount.host_path)
        for mount in retry_mounts
    )
    assert not any(
        mount.mode == "rw" and target.resolve(strict=False).is_relative_to(mount.host_path)
        for mount in retry_mounts
    )


@pytest.mark.asyncio
async def test_trusted_execve_path_denial_retries_with_ro_mount(
    managed_runtime: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.types import SandboxRequest
    from opensquilla.tools.builtin import shell

    outside = tmp_path_factory.mktemp("outside-exec")
    target = outside / "tool"
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    backend_calls: list[SandboxRequest] = []

    async def _fake_run_under_backend(request, *, runtime=None):
        backend_calls.append(request)
        if len(backend_calls) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="",
                backend_notes=(f"execve.denied: {target}",),
            )
        return SimpleNamespace(returncode=0, stdout="ran\n", stderr="", backend_notes=())

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(shell, "_sensitive_shell_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_read_path_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_write_path_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = await shell.exec_command("pip install demo", workdir=str(managed_runtime))
    finally:
        current_tool_context.reset(token)

    assert "ran" in result
    retry_mounts = backend_calls[1].policy.mounts
    assert any(
        mount.mode == "ro" and target.resolve(strict=False).is_relative_to(mount.host_path)
        for mount in retry_mounts
    )
    assert not any(
        mount.mode == "rw" and target.resolve(strict=False).is_relative_to(mount.host_path)
        for mount in retry_mounts
    )


@pytest.mark.asyncio
async def test_trusted_path_recovery_preserves_mount_without_redundant_network_retry(
    managed_runtime: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.types import SandboxRequest
    from opensquilla.tools.builtin import shell

    outside = tmp_path_factory.mktemp("outside-path-network")
    backend_calls: list[SandboxRequest] = []
    cleanup_calls = 0

    async def _fake_run_under_backend(request, *, runtime=None):
        backend_calls.append(request)
        if len(backend_calls) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="",
                backend_notes=(f"mount denied: {outside}",),
            )
        if len(backend_calls) == 2:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="curl: (6) Could not resolve host: pypi.org\n",
                backend_notes=(),
            )
        return SimpleNamespace(returncode=0, stdout="installed\n", stderr="", backend_notes=())

    async def _fake_prepare_subprocess_managed_network_proxy(request, *, runtime=None):
        managed_env = dict(request.env)
        managed_env["HTTP_PROXY"] = "http://127.0.0.1:48123"
        managed_env["HTTPS_PROXY"] = managed_env["HTTP_PROXY"]
        managed_request = SandboxRequest(
            argv=request.argv,
            cwd=request.cwd,
            action_kind=request.action_kind,
            policy=request.policy,
            stdin=request.stdin,
            env=managed_env,
            reason=request.reason,
        )

        async def _cleanup() -> None:
            nonlocal cleanup_calls
            cleanup_calls += 1

        return SimpleNamespace(request=managed_request, cleanup=_cleanup)

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "prepare_subprocess_managed_network_proxy",
        _fake_prepare_subprocess_managed_network_proxy,
    )
    monkeypatch.setattr(shell, "_sensitive_shell_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_workdir_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_read_path_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_write_path_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = await shell.exec_command("pip install demo", workdir=str(outside))
    finally:
        current_tool_context.reset(token)

    assert "Could not resolve host: pypi.org" in result
    assert len(backend_calls) == 2
    assert cleanup_calls == 2
    assert backend_calls[1].env["HTTP_PROXY"] == "http://127.0.0.1:48123"
    assert any(
        mount.mode == "rw" and outside.resolve(strict=False).is_relative_to(mount.host_path)
        for mount in backend_calls[1].policy.mounts
    )


@pytest.mark.asyncio
async def test_trusted_sensitive_path_denial_does_not_auto_retry(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.types import (
        DenialReason,
        DenialResult,
        SandboxRequest,
        SecurityLevel,
        SuggestedNextStep,
    )
    from opensquilla.tools.builtin import shell

    backend_calls: list[SandboxRequest] = []

    async def _fake_run_under_backend(request, *, runtime=None):
        backend_calls.append(request)
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="",
            backend_notes=("mount denied: /etc/passwd",),
        )

    async def _fake_escalate_backend_denial(*args, **kwargs):
        return DenialResult(
            reason=DenialReason.SEATBELT_DENIED,
            suggested_next_step=SuggestedNextStep.ASK_USER,
            level=SecurityLevel.STANDARD,
            action_fingerprint="test",
            message="denied",
            retryable=False,
        )

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(shell, "escalate_backend_denial", _fake_escalate_backend_denial)
    monkeypatch.setattr(shell, "_sensitive_shell_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_read_path_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(shell, "_sandbox_write_path_access_envelope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = await shell.exec_command("cat /etc/passwd", workdir=str(managed_runtime))
    finally:
        current_tool_context.reset(token)

    assert json.loads(result)["status"] == "denied"
    assert len(backend_calls) == 1


@pytest.mark.asyncio
async def test_trusted_successful_network_failure_text_does_not_retry(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    backend_calls = 0

    async def _fake_run_under_backend(request, *, runtime=None):
        nonlocal backend_calls
        backend_calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout="Could not resolve host: pypi.org\n",
            stderr="",
            backend_notes=(),
        )

    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = await shell.exec_command("pip install demo", workdir=str(managed_runtime))
    finally:
        current_tool_context.reset(token)

    assert backend_calls == 1
    assert "Could not resolve host: pypi.org" in result


@pytest.mark.asyncio
async def test_timeout_wrapped_node_install_queues_bundle_approval_before_proxy_run(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    async def _fail_run_under_backend(request, *, runtime=None):
        pytest.fail("node package bundle approval should run before proxy execution")

    monkeypatch.setattr(shell, "run_under_backend", _fail_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(run_mode=RunMode.STANDARD),
        )
    )
    try:
        payload = json.loads(
            await shell.exec_command(
                "timeout 30 npm install lodash",
                workdir=str(managed_runtime),
            )
        )
    finally:
        current_tool_context.reset(token)

    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_network"
    assert payload["bundle_id"] == "node-package-install"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["bundle_id"] == "node-package-install"


@pytest.mark.asyncio
async def test_subprocess_network_approval_uses_session_workspace_for_external_cwd(
    managed_runtime: Path,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.sandbox.types import (
        NetworkMode,
        ResourceLimits,
        SandboxPolicy,
        SandboxRequest,
        SecurityLevel,
    )

    external = managed_runtime.parent / f"{managed_runtime.name}-external"
    external.mkdir()
    runtime = get_runtime()
    assert runtime is not None
    request = SandboxRequest(
        argv=("sh", "-lc", "curl https://unknown.test/path"),
        cwd=external,
        action_kind="shell.exec",
        policy=SandboxPolicy(
            level=SecurityLevel.STANDARD,
            network=NetworkMode.PROXY_ALLOWLIST,
            mounts=(),
            workspace_rw=True,
            tmp_writable=True,
            limits=ResourceLimits(),
            env_allowlist=("PATH",),
            require_approval=False,
        ),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(
                run_mode=RunMode.STANDARD,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        payload = await integration_mod.preflight_subprocess_managed_network(
            request,
            runtime,
        )
    finally:
        current_tool_context.reset(token)

    assert isinstance(payload, dict)
    assert payload["status"] == "approval_required"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["workspace"] == str(managed_runtime)
    assert pending[0]["params"]["workspace"] != str(external)


@pytest.mark.asyncio
async def test_subprocess_network_once_grant_consumes_from_session_workspace(
    managed_runtime: Path,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.sandbox.types import (
        NetworkMode,
        ResourceLimits,
        SandboxPolicy,
        SandboxRequest,
        SecurityLevel,
    )

    external = managed_runtime.parent / f"{managed_runtime.name}-external"
    external.mkdir()
    runtime = get_runtime()
    assert runtime is not None
    request = SandboxRequest(
        argv=("sh", "-lc", "curl https://unknown.test/path"),
        cwd=external,
        action_kind="shell.exec",
        policy=SandboxPolicy(
            level=SecurityLevel.STANDARD,
            network=NetworkMode.PROXY_ALLOWLIST,
            mounts=(),
            workspace_rw=True,
            tmp_writable=True,
            limits=ResourceLimits(),
            env_allowlist=("PATH",),
            require_approval=False,
        ),
    )
    grant = TemporaryGrant(
        kind="domain",
        value="unknown.test",
        fingerprint=integration_mod.action_fingerprint(request),
    )
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.CLI,
        workspace_dir=str(managed_runtime),
        session_key="s1",
        run_mode="standard",
        sandbox_run_context=RunContext(
            run_mode=RunMode.STANDARD,
            workspace=str(managed_runtime),
            temporary_grants=(grant,),
        ),
    )

    token = current_tool_context.set(ctx)
    try:
        payload = await integration_mod.preflight_subprocess_managed_network(
            request,
            runtime,
        )
    finally:
        current_tool_context.reset(token)

    assert payload is None
    assert isinstance(ctx.sandbox_run_context, RunContext)
    assert ctx.sandbox_run_context.temporary_grants == ()


@pytest.mark.asyncio
async def test_background_shell_network_spawn_receives_managed_proxy(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.tools.builtin import shell

    class _FakeProxyServer:
        host = "127.0.0.1"
        port = 48123

        def __init__(self, *args, **kwargs) -> None:
            return None

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    class _FakeStream:
        async def read(self, size: int) -> bytes:
            return b""

    class _FakeProcess:
        stdout = _FakeStream()
        stdin = None
        returncode = 0

        async def wait(self) -> int:
            return 0

    seen: dict[str, object] = {}

    async def _fake_spawn(*, runtime: object, request: object) -> object:
        seen["policy"] = request.policy
        seen["env"] = request.env
        assert request.policy.network_proxy is not None
        return shell._SpawnedBackgroundProcess(process=_FakeProcess())  # type: ignore[arg-type]

    monkeypatch.setattr(shell, "_spawn_sandboxed_background_process", _fake_spawn)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)
    monkeypatch.setattr(integration_mod, "SandboxProxyServer", _FakeProxyServer)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(
                run_mode=RunMode.STANDARD,
                domains=(DomainGrant(domain="example.com"),),
            ),
        )
    )
    try:
        result = await shell.background_process(
            "curl https://example.com",
            workdir=str(managed_runtime),
            timeout=5,
        )
        session_id = result.splitlines()[0].split("=", 1)[1]
        session = shell._bg_sessions[session_id]
        assert session.collector_task is not None
        await session.collector_task
    finally:
        current_tool_context.reset(token)

    assert "policy" in seen
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"]
    assert env["NO_PROXY"] == ""


@pytest.mark.asyncio
async def test_code_network_subprocess_receives_managed_proxy_env(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.tools.builtin import code_exec, shell

    class _FakeProxyServer:
        host = "127.0.0.1"
        port = 48123

        def __init__(self, *args, **kwargs) -> None:
            return None

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(code_exec, "_resolve_python_bin", lambda *, sandbox_enabled: sys.executable)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)
    monkeypatch.setattr(integration_mod, "SandboxProxyServer", _FakeProxyServer)
    seen: dict[str, object] = {}

    async def _fake_run_under_backend(request, *, runtime=None):
        managed = await integration_mod.prepare_subprocess_managed_network_proxy(
            request,
            runtime=runtime,
        )
        try:
            seen["env"] = managed.request.env
            seen["policy"] = managed.request.policy
            return SimpleNamespace(
                returncode=0,
                stdout="ok\n",
                stderr="",
                timed_out=False,
                backend_notes=(),
            )
        finally:
            await managed.cleanup()

    monkeypatch.setattr(code_exec, "run_under_backend", _fake_run_under_backend)

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(
                run_mode=RunMode.STANDARD,
                domains=(DomainGrant(domain="example.com"),),
            ),
        )
    )
    try:
        result = json.loads(
            await code_exec.execute_code(
                "\n".join(
                    (
                        "import os, socket",
                        "url = 'https://example.com/path'",
                        "socket.gethostname()",
                        "print(os.environ.get('HTTP_PROXY', ''))",
                        "print(os.environ.get('HTTPS_PROXY', ''))",
                        "print(os.environ.get('NO_PROXY', '<missing>'))",
                    )
                )
            )
        )
    finally:
        current_tool_context.reset(token)

    assert result["exit_code"] == 0, result
    assert result["stdout"] == "ok\n"
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"]
    assert env["NO_PROXY"] == ""


@pytest.mark.asyncio
async def test_trusted_code_exec_normal_user_path_denial_retries_once(
    managed_runtime: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.types import (
        DenialReason,
        DenialResult,
        SandboxRequest,
        SecurityLevel,
        SuggestedNextStep,
    )
    from opensquilla.tools.builtin import code_exec, shell

    outside = tmp_path_factory.mktemp("outside-code")
    backend_calls: list[SandboxRequest] = []

    async def _fake_run_under_backend(request, *, runtime=None):
        backend_calls.append(request)
        if len(backend_calls) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="",
                timed_out=False,
                backend_notes=(f"filesystem.read.denied: {outside}",),
            )
        return SimpleNamespace(
            returncode=0,
            stdout="ok\n",
            stderr="",
            timed_out=False,
            backend_notes=(),
        )

    async def _fake_escalate_backend_denial(*args, **kwargs):
        return DenialResult(
            reason=DenialReason.SEATBELT_DENIED,
            suggested_next_step=SuggestedNextStep.ASK_USER,
            level=SecurityLevel.STANDARD,
            action_fingerprint="test",
            message="denied",
            retryable=False,
        )

    monkeypatch.setattr(code_exec, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(code_exec, "escalate_backend_denial", _fake_escalate_backend_denial)
    monkeypatch.setattr(code_exec, "_resolve_python_bin", lambda *, sandbox_enabled: sys.executable)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(managed_runtime),
            ),
        )
    )
    try:
        result = json.loads(await code_exec.execute_code("print('ok')"))
    finally:
        current_tool_context.reset(token)

    assert result["stdout"] == "ok\n"
    assert len(backend_calls) == 2
    assert any(
        mount.mode == "ro" and outside.resolve(strict=False).is_relative_to(mount.host_path)
        for mount in backend_calls[1].policy.mounts
    )


@pytest.mark.asyncio
async def test_code_unknown_explicit_url_queues_network_approval_before_proxy_run(
    managed_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import code_exec, shell

    async def _fail_run_under_backend(request, *, runtime=None):
        pytest.fail("network approval preflight should run before proxy execution")

    monkeypatch.setattr(code_exec, "run_under_backend", _fail_run_under_backend)
    monkeypatch.setattr(code_exec, "_resolve_python_bin", lambda *, sandbox_enabled: sys.executable)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(managed_runtime),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(run_mode=RunMode.STANDARD),
        )
    )
    try:
        payload = json.loads(
            await code_exec.execute_code(
                'import requests\nrequests.get("https://unknown.test/path")'
            )
        )
    finally:
        current_tool_context.reset(token)

    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_network"
    assert payload["host"] == "unknown.test"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["host"] == "unknown.test"
