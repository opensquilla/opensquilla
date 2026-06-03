from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.sandbox.run_context import RunContext
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
