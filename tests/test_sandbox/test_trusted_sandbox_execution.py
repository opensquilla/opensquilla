from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


@pytest.mark.asyncio
async def test_trusted_sandbox_does_not_mark_shell_host_elevated(monkeypatch) -> None:
    from opensquilla.tools.builtin import shell

    calls: list[tuple[str, object]] = []

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)

    async def _fake_gate_action(**kwargs):
        calls.append(("gate", kwargs))
        policy = SimpleNamespace()
        request = SimpleNamespace(cwd="/tmp", action_kind="shell.exec", policy=policy)
        return object(), policy, request

    async def _fake_run_under_backend(request, *, runtime=None):
        calls.append(("backend", request))
        return SimpleNamespace(
            returncode=0,
            stdout="sandboxed\n",
            stderr="",
            backend_notes=(),
        )

    monkeypatch.setattr(shell, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(is_owner=True, caller_kind=CallerKind.WEB, session_key="s1", run_mode="trusted")
    )
    try:
        result = await shell.exec_command("echo hi")
    finally:
        current_tool_context.reset(token)

    assert "sandboxed" in result
    assert [name for name, _ in calls] == ["gate", "backend"]


@pytest.mark.asyncio
async def test_ordinary_approval_result_does_not_carry_elevated_mode(monkeypatch) -> None:
    from opensquilla.application.approval_queue import ApprovalQueue

    queue = ApprovalQueue(db_path=":memory:")
    try:
        approval_id = queue.request(
            namespace="exec",
            params={"sessionKey": "s1", "command": "rm x"},
        )
        queue.resolve(approval_id, True)
        status = queue.status(approval_id)
        assert "elevatedMode" not in status["params"]
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_resolved_warnlist_approval_still_runs_shell_in_sandbox(monkeypatch) -> None:
    from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
    from opensquilla.tools.builtin import shell

    calls: list[tuple[str, object]] = []
    reset_approval_queue()

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)

    async def _fake_gate_action(**kwargs):
        calls.append(("gate", kwargs))
        policy = SimpleNamespace()
        request = SimpleNamespace(cwd="/tmp", action_kind="shell.exec", policy=policy)
        return object(), policy, request

    async def _fake_run_under_backend(request, *, runtime=None):
        calls.append(("backend", request))
        return SimpleNamespace(
            returncode=0,
            stdout="sandboxed after approval\n",
            stderr="",
            backend_notes=(),
        )

    monkeypatch.setattr(shell, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(
            allowed=True,
            needs_approval=True,
            reason="command requires approval",
        ),
    )

    token = current_tool_context.set(
        ToolContext(is_owner=True, caller_kind=CallerKind.CLI, session_key="s1")
    )
    try:
        first = await shell.exec_command("rm x")
        approval_id = get_approval_queue().list_pending("exec")[0]["id"]
        get_approval_queue().resolve(approval_id, True)
        second = await shell.exec_command("rm x", approval_id=approval_id)
    finally:
        current_tool_context.reset(token)
        reset_approval_queue()

    assert "approval_required" in first
    assert "sandboxed after approval" in second
    assert [name for name, _ in calls] == ["gate", "backend"]


@pytest.mark.asyncio
async def test_backend_denial_host_once_does_not_persist(monkeypatch) -> None:
    from opensquilla.sandbox.types import ALLOW
    from opensquilla.tools.builtin import shell

    calls: list[str] = []

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"host once\n", None

        def kill(self) -> None:
            return None

    async def _fake_gate_action(**kwargs):
        calls.append("gate")
        policy = SimpleNamespace()
        request = SimpleNamespace(
            cwd="/tmp",
            action_kind="shell.exec",
            policy=policy,
            reason="",
        )
        return object(), policy, request

    backend_results = [
        SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="denied",
            backend_notes=("exec denied",),
        ),
        SimpleNamespace(
            returncode=0,
            stdout="sandboxed again\n",
            stderr="",
            backend_notes=(),
        ),
    ]

    async def _fake_run_under_backend(request, *, runtime=None):
        calls.append("backend")
        return backend_results.pop(0)

    async def _fake_escalate_backend_denial(*args, **kwargs):
        calls.append("escalate")
        return ALLOW

    async def _fake_create_subprocess_shell(*args, **kwargs):
        calls.append("host")
        return _Proc()

    monkeypatch.setattr(shell, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(shell, "escalate_backend_denial", _fake_escalate_backend_denial)
    monkeypatch.setattr(shell.asyncio, "create_subprocess_shell", _fake_create_subprocess_shell)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(is_owner=True, caller_kind=CallerKind.CLI, session_key="s1")
    )
    try:
        first = await shell.exec_command("echo hi")
        second = await shell.exec_command("echo hi")
    finally:
        current_tool_context.reset(token)

    assert "host once" in first
    assert "sandboxed again" in second
    assert calls == ["gate", "backend", "escalate", "host", "gate", "backend"]
