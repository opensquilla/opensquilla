from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from opensquilla.tools.types import CallerKind, ToolContext, ToolError, current_tool_context


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
async def test_backend_denial_does_not_fall_back_to_host(monkeypatch) -> None:
    from opensquilla.tools.builtin import shell

    calls: list[str] = []

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)

    class _Proc:
        pid = 999999
        returncode = 0

        async def wait(self):
            return 0

        def terminate(self) -> None:
            return None

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
        return object()

    async def _fake_create_subprocess_shell(*args, **kwargs):
        calls.append("host")
        assert kwargs["stdout"] != shell.asyncio.subprocess.PIPE
        assert kwargs["stderr"] == shell.asyncio.subprocess.STDOUT
        if shell.os.name == "posix":
            assert kwargs["start_new_session"] is True
        return _Proc()

    class _FakeTemporaryFile:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def flush(self) -> None:
            return None

        def seek(self, offset: int) -> None:
            return None

        def read(self) -> bytes:
            return b"host fallback should not run\n"

    monkeypatch.setattr(shell, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(shell, "escalate_backend_denial", _fake_escalate_backend_denial)
    monkeypatch.setattr(shell.asyncio, "create_subprocess_shell", _fake_create_subprocess_shell)
    monkeypatch.setattr(shell.tempfile, "TemporaryFile", lambda: _FakeTemporaryFile())
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(is_owner=True, caller_kind=CallerKind.CLI, session_key="s1")
    )
    try:
        with pytest.raises(ToolError, match="host fallback disabled"):
            await shell.exec_command("echo hi")
    finally:
        current_tool_context.reset(token)

    assert calls == ["gate", "backend", "escalate"]


@pytest.mark.asyncio
async def test_full_host_access_code_exec_resolves_host_python(monkeypatch, tmp_path) -> None:
    from opensquilla.tools.builtin import code_exec

    resolve_calls: list[bool] = []
    child_env: dict[str, str] = {}

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)
        workspace = tmp_path

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"host python\n", b""

    def _fake_resolve_python_bin(*, sandbox_enabled: bool) -> str:
        resolve_calls.append(sandbox_enabled)
        return "/host/python"

    async def _fake_create_subprocess_exec(*args, **kwargs):
        assert args[:2] == ("/host/python", "-c")
        child_env.update(kwargs["env"])
        return _Proc()

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("WINDIR", r"C:\Windows")
    monkeypatch.setenv("ComSpec", r"C:\Windows\System32\cmd.exe")
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))
    monkeypatch.setenv("TMP", str(tmp_path / "temp"))
    monkeypatch.setattr(code_exec, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(code_exec, "_resolve_python_bin", _fake_resolve_python_bin)
    monkeypatch.setattr(code_exec.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            session_key="s1",
            run_mode="full",
            workspace_dir=str(tmp_path),
        )
    )
    try:
        result = await code_exec.execute_code("print('hi')")
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["exit_code"] == 0
    assert payload["stdout"] == "host python\n"
    assert resolve_calls == [False]
    folded_env = {key.upper(): value for key, value in child_env.items()}
    assert folded_env["SYSTEMROOT"] == r"C:\Windows"
    assert folded_env["WINDIR"] == r"C:\Windows"
    assert folded_env["COMSPEC"] == r"C:\Windows\System32\cmd.exe"
    assert folded_env["TEMP"] == str(tmp_path / "temp")
    assert folded_env["TMP"] == str(tmp_path / "temp")


@pytest.mark.asyncio
async def test_full_host_access_shell_uses_host_and_skips_sandbox_gates(
    monkeypatch,
    tmp_path,
) -> None:
    from opensquilla.tools.builtin import shell

    calls: list[str] = []

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)

    async def _fail_gate_action(**kwargs):
        pytest.fail("Full Host Access shell should not enter sandbox gate_action")

    async def _fake_host_shell_command(*args, **kwargs):
        calls.append("host")
        return "exit_code=1\nhead: cannot open '/etc/shadow' for reading: Permission denied\n"

    monkeypatch.setattr(shell, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(shell, "gate_action", _fail_gate_action)
    monkeypatch.setattr(shell, "_run_host_shell_command", _fake_host_shell_command)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            session_key="s1",
            run_mode="full",
            workspace_dir=str(tmp_path),
        )
    )
    try:
        result = await shell.exec_command("head -n 1 /etc/shadow 2>&1; echo exit=$?")
    finally:
        current_tool_context.reset(token)

    assert calls == ["host"]
    assert "Permission denied" in result
    assert "sensitive_path" not in result


@pytest.mark.asyncio
async def test_full_host_access_shell_strips_managed_proxy_environment(
    monkeypatch,
    tmp_path,
) -> None:
    from opensquilla.tools.builtin import shell

    seen_env: dict[str, str] = {}

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)

    async def _fake_host_shell_command(*args, **kwargs):
        seen_env.update(kwargs["env"])
        return "exit_code=0\n"

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:48123")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:48123")
    monkeypatch.setenv("OPENSQUILLA_SANDBOX_NETWORK", "proxy_allowlist")
    monkeypatch.setattr(shell, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(shell, "_run_host_shell_command", _fake_host_shell_command)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            session_key="s1",
            run_mode="full",
            workspace_dir=str(tmp_path),
        )
    )
    try:
        await shell.exec_command("env")
    finally:
        current_tool_context.reset(token)

    assert "OPENSQUILLA_SANDBOX_NETWORK" not in seen_env
    assert "HTTP_PROXY" not in seen_env
    assert "HTTPS_PROXY" not in seen_env


@pytest.mark.asyncio
async def test_full_host_access_background_strips_managed_proxy_environment(
    monkeypatch,
    tmp_path,
) -> None:
    from opensquilla.tools.builtin import shell

    seen_env: dict[str, str] = {}

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)

    class _FakeProcess:
        stdout = None
        stdin = None
        returncode = 0

        async def wait(self) -> int:
            return 0

    async def _fake_create_subprocess_shell(*args, **kwargs):
        seen_env.update(kwargs["env"])
        return _FakeProcess()

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:48123")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:48123")
    monkeypatch.setenv("OPENSQUILLA_SANDBOX_NETWORK", "proxy_allowlist")
    monkeypatch.setattr(shell, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(shell.asyncio, "create_subprocess_shell", _fake_create_subprocess_shell)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            session_key="s1",
            run_mode="full",
            workspace_dir=str(tmp_path),
        )
    )
    try:
        result = await shell.background_process("env")
        session_id = result.splitlines()[0].split("=", 1)[1]
        session = shell._bg_sessions[session_id]
        assert session.collector_task is not None
        await session.collector_task
    finally:
        current_tool_context.reset(token)

    assert "OPENSQUILLA_SANDBOX_NETWORK" not in seen_env
    assert "HTTP_PROXY" not in seen_env
    assert "HTTPS_PROXY" not in seen_env
