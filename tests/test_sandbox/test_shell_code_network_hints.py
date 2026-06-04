from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, get_runtime, reset_runtime
from opensquilla.sandbox.run_context import DomainGrant, RunContext, TemporaryGrant
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
    from opensquilla.tools.builtin import shell

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
        assert request.policy.network_proxy is not None
        return shell._SpawnedBackgroundProcess(process=_FakeProcess())  # type: ignore[arg-type]

    monkeypatch.setattr(shell, "_spawn_sandboxed_background_process", _fake_spawn)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)
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
