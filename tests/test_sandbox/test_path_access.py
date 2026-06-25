from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, get_runtime, reset_runtime
from opensquilla.sandbox.operation_runtime import SandboxOperation, SandboxOperationResult
from opensquilla.sandbox.path_validation import decide_path_access
from opensquilla.sandbox.run_context import RunContext
from opensquilla.sandbox.run_mode import RunMode
from opensquilla.sandbox.types import SandboxRequest
from opensquilla.tools.builtin import filesystem as fs
from opensquilla.tools.builtin import shell
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


class _InlineExecutorLoop:
    async def run_in_executor(self, executor: object, func: object, *args: object) -> object:
        return func(*args)  # type: ignore[operator]


class _FilesystemBackend:
    name = "filesystem_backend"

    def operation_domains_supported(self) -> frozenset[str]:
        return frozenset({"filesystem"})

    async def run_operation(self, operation: SandboxOperation) -> SandboxOperationResult:
        request = getattr(operation, "request", None)
        path = getattr(request, "path", None)
        if path is None:
            raise AssertionError("filesystem operation missing path")
        if operation.kind == "read_file":
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            return SandboxOperationResult(message=path.read_text(encoding="utf-8"))
        if operation.kind == "list_dir":
            if not path.exists():
                raise FileNotFoundError(f"Path not found: {path}")
            entries = []
            for entry in sorted(path.iterdir(), key=lambda item: item.name):
                if entry.is_dir():
                    entries.append(f"[dir]  {entry.name}/")
                else:
                    entries.append(f"[file] {entry.name} ({entry.stat().st_size} bytes)")
            return SandboxOperationResult(
                message="\n".join(entries) if entries else f"{path}: (empty directory)"
            )
        if operation.kind == "write_text":
            created = not path.exists()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(request.content, encoding="utf-8")
            return SandboxOperationResult(
                message=f"Written {len(request.content)} bytes to {path}",
                created=created,
            )
        if operation.kind == "edit_text":
            original = path.read_text(encoding="utf-8")
            updated = original.replace(request.old_text, request.new_text, 1)
            path.write_text(updated, encoding="utf-8")
            return SandboxOperationResult(
                message=(
                    f"Edited {path}: replaced {len(request.old_text)} chars "
                    f"with {len(request.new_text)} chars"
                )
            )
        if operation.kind == "grep_search":
            matches = []
            for entry in sorted(path.rglob("*")):
                if entry.is_symlink() or not entry.is_file():
                    continue
                try:
                    text = entry.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for line_no, line in enumerate(text.splitlines(), start=1):
                    if request.pattern in line:
                        matches.append(f"{entry}:{line_no}:{line}")
            return SandboxOperationResult(
                message="\n".join(matches) if matches else "No matches"
            )
        raise AssertionError(f"unsupported filesystem operation: {operation.kind}")


def _install_filesystem_read_backend() -> None:
    runtime = get_runtime()
    assert runtime is not None
    runtime.backend = _FilesystemBackend()


@contextmanager
def tool_context(
    workspace: Path,
    *,
    run_mode: str | None = "standard",
    sandbox_mounts: list[dict[str, object]] | None = None,
    workspace_strict: bool = False,
) -> Iterator[ToolContext]:
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.CLI,
        workspace_dir=str(workspace),
        workspace_strict=workspace_strict,
        run_mode=run_mode,
        session_key="s1",
        sandbox_mounts=sandbox_mounts or [],
    )
    token = current_tool_context.set(ctx)
    try:
        yield ctx
    finally:
        current_tool_context.reset(token)


@pytest.fixture(autouse=True)
def sandbox_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from opensquilla.application import approval_queue as approval_queue_mod

    monkeypatch.setattr(
        approval_queue_mod,
        "_DEFAULT_APPROVAL_QUEUE_PATH",
        tmp_path / "approval_queue.sqlite",
    )
    reset_approval_queue()
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    runtime = configure_runtime(
        SandboxSettings(run_mode="standard", backend="noop", allow_legacy_mode=True),
        workspace=workspace,
    )
    runtime.backend = _FilesystemBackend()
    try:
        yield
    finally:
        reset_approval_queue()
        reset_runtime()


def test_normal_sibling_path_requests_ro_mount(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sibling = tmp_path / "sibling" / "notes.txt"

    decision = decide_path_access(sibling, workspace=workspace)

    assert decision.status == "request"
    assert decision.access == "ro"
    assert decision.normalized_path == str(sibling.resolve(strict=False))


def test_sensitive_ssh_path_is_blocked(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    target = Path.home() / ".ssh" / "id_rsa"

    decision = decide_path_access(target, workspace=workspace)

    assert decision.status == "blocked"
    assert decision.reason == "sensitive_path"


def test_workspace_child_is_allowed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "src" / "app.py"

    decision = decide_path_access(target, workspace=workspace)

    assert decision.status == "allowed"
    assert decision.access == "ro"


def test_default_container_workspace_child_is_allowed_before_root_block() -> None:
    workspace = "/root/.opensquilla/workspace"
    target = "/root/.opensquilla/workspace/project/src/app.py"

    decision = decide_path_access(target, workspace=workspace)

    assert decision.status == "allowed"
    assert decision.access == "ro"


def test_sensitive_file_inside_default_container_workspace_stays_blocked() -> None:
    workspace = "/root/.opensquilla/workspace"
    target = "/root/.opensquilla/workspace/project/.env.local"

    decision = decide_path_access(target, workspace=workspace)

    assert decision.status == "blocked"
    assert decision.reason == "sensitive_path"


def test_write_request_asks_for_rw_mount(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sibling = tmp_path / "sibling" / "notes.txt"

    decision = decide_path_access(sibling, workspace=workspace, write=True)

    assert decision.status == "request"
    assert decision.access == "rw"


def test_request_path_builds_structured_mount_escalation_choices(tmp_path: Path) -> None:
    from opensquilla.sandbox.escalation import build_path_approval_params

    workspace = tmp_path / "workspace"
    sibling = tmp_path / "sibling" / "notes.txt"
    decision = decide_path_access(sibling, workspace=workspace, write=True)

    proposal = build_path_approval_params(
        decision,
        session_key="agent:main:webchat:abc",
        workspace=str(workspace),
    )

    assert proposal is not None
    assert proposal["approvalKind"] == "sandbox_path"
    assert proposal["path"] == str(sibling.resolve(strict=False))
    assert proposal["access"] == "rw"
    assert [choice["id"] for choice in proposal["choices"]] == [
        "mount_rw_chat",
        "deny",
    ]
    assert [choice["label"] for choice in proposal["choices"]] == [
        "Allow read/write",
        "Deny",
    ]
    assert proposal["choices"][0]["style"] == "primary"


def test_blocked_path_has_no_mount_escalation_choices(tmp_path: Path) -> None:
    from opensquilla.sandbox.escalation import build_path_approval_params

    workspace = tmp_path / "workspace"
    decision = decide_path_access("/", workspace=workspace, write=False)

    assert decision.status == "blocked"
    assert build_path_approval_params(
        decision,
        session_key="agent:main:webchat:abc",
        workspace=str(workspace),
    ) is None


def test_most_specific_rw_mount_allows_write_under_ro_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    parent = tmp_path / "parent"
    child = parent / "child"
    target = child / "out.txt"

    decision = decide_path_access(
        target,
        workspace=workspace,
        mounts=[
            {"path": str(parent), "access": "ro"},
            {"path": str(child), "access": "rw"},
        ],
        write=True,
    )

    assert decision.status == "allowed"
    assert decision.access == "rw"


def test_most_specific_ro_mount_requests_write_under_rw_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    parent = tmp_path / "parent"
    child = parent / "child"
    target = child / "out.txt"

    decision = decide_path_access(
        target,
        workspace=workspace,
        mounts=[
            {"path": str(parent), "access": "rw"},
            {"path": str(child), "access": "ro"},
        ],
        write=True,
    )

    assert decision.status == "request"
    assert decision.access == "rw"


@pytest.mark.asyncio
async def test_existing_ro_mount_allows_filesystem_read_and_list(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    mounted = tmp_path / "mounted"
    mounted.mkdir()
    missing_file = mounted / "missing.txt"
    missing_dir = mounted / "missing-dir"

    with tool_context(
        workspace,
        sandbox_mounts=[{"path": str(mounted), "access": "ro"}],
    ):
        with pytest.raises(FileNotFoundError):
            await fs.read_file(str(missing_file))
        with pytest.raises(FileNotFoundError):
            await fs.list_dir(str(missing_dir))


@pytest.mark.asyncio
async def test_existing_ro_mount_allows_list_dir_when_workspace_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    mounted = tmp_path / "mounted"
    mounted.mkdir()
    (mounted / "notes.txt").write_text("hello\n", encoding="utf-8")
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(
        workspace,
        sandbox_mounts=[{"path": str(mounted), "access": "ro"}],
        workspace_strict=True,
    ):
        result = await fs.list_dir(str(mounted))

    assert "notes.txt" in result


@pytest.mark.asyncio
async def test_filesystem_read_outside_workspace_requests_ro_mount(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside" / "notes.txt"
    outside.parent.mkdir()
    outside.write_text("outside body\n", encoding="utf-8")

    with tool_context(workspace):
        payload = json.loads(await fs.read_file(str(outside)))

    assert payload["status"] == "approval_required"
    assert payload["approval_id"]
    assert payload["path"] == str(outside.resolve(strict=False))
    assert payload["access"] == "ro"
    assert payload["approvalKind"] == "sandbox_path"
    assert [choice["id"] for choice in payload["choices"]] == [
        "mount_ro_chat",
        "mount_rw_chat",
        "deny",
    ]
    assert "outside the current workspace" in payload["message"]
    assert str(workspace) in payload["message"]
    assert "read-only or read/write access" in payload["message"]
    assert "appears as /workspace" not in payload["message"]
    pending = get_approval_queue().get(payload["approval_id"])
    assert pending.params["approvalKind"] == "sandbox_path"
    assert pending.params["path"] == str(outside.resolve(strict=False))


@pytest.mark.asyncio
async def test_denied_sandbox_path_request_does_not_create_repeated_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from opensquilla.gateway.rpc_approvals import _handle_exec_approval_resolve

    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(workspace):
        first = json.loads(await fs.list_dir(str(outside)))

    assert first["status"] == "approval_required"
    assert first["approvalKind"] == "sandbox_path"
    approval_id = first["approval_id"]
    assert len(get_approval_queue().list_pending("exec")) == 1

    await _handle_exec_approval_resolve(
        {"id": approval_id, "approved": False, "choice": "deny"},
        SimpleNamespace(session_manager=None, config=None),
    )

    with tool_context(workspace):
        second = json.loads(await fs.list_dir(str(outside)))

    assert second["status"] == "approval_denied"
    assert second["approval_id"] == approval_id
    assert "user denied" in second["message"].lower()
    assert "do not ask" in second["message"].lower()
    assert "Add the requested path" not in second["message"]
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_denied_sandbox_path_request_can_be_requested_again_next_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from opensquilla.gateway.rpc_approvals import _handle_exec_approval_resolve
    from opensquilla.sandbox.escalation import clear_sandbox_approval_denials

    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(workspace):
        first = json.loads(await fs.list_dir(str(outside)))

    assert first["status"] == "approval_required"
    approval_id = first["approval_id"]

    await _handle_exec_approval_resolve(
        {"id": approval_id, "approved": False, "choice": "deny"},
        SimpleNamespace(session_manager=None, config=None),
    )

    with tool_context(workspace):
        same_turn = json.loads(await fs.list_dir(str(outside)))

    assert same_turn["status"] == "approval_denied"
    assert same_turn["approval_id"] == approval_id

    clear_sandbox_approval_denials("s1")

    with tool_context(workspace):
        next_turn = json.loads(await fs.list_dir(str(outside)))

    assert next_turn["status"] == "approval_required"
    assert next_turn["approval_id"] != approval_id


@pytest.mark.asyncio
async def test_denied_sandbox_path_request_clears_duplicate_pending_prompts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from opensquilla.gateway.rpc_approvals import _handle_exec_approval_resolve

    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(workspace):
        first = json.loads(await fs.list_dir(str(outside)))
        second = json.loads(await fs.list_dir(str(outside)))

    assert first["status"] == "approval_required"
    assert second["status"] == "approval_pending"
    assert second["approval_id"] == first["approval_id"]
    assert len(get_approval_queue().list_pending("exec")) == 1

    await _handle_exec_approval_resolve(
        {"id": first["approval_id"], "approved": False, "choice": "deny"},
        SimpleNamespace(session_manager=None, config=None),
    )

    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_filesystem_write_outside_workspace_requests_rw_mount(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside" / "notes.txt"

    with tool_context(workspace):
        payload = json.loads(await fs.write_file(str(outside), "outside body\n"))

    assert payload["status"] == "approval_required"
    assert payload["approval_id"]
    assert payload["path"] == str(outside.resolve(strict=False))
    assert payload["access"] == "rw"
    assert payload["approvalKind"] == "sandbox_path"
    assert [choice["id"] for choice in payload["choices"]] == ["mount_rw_chat", "deny"]
    assert not outside.exists()


@pytest.mark.asyncio
async def test_trusted_sandbox_write_outside_workspace_auto_grants_rw_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside" / "notes.txt"
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(workspace, run_mode="trusted") as ctx:
        result = await fs.write_file(str(outside), "outside body\n")

    assert "Written 13 bytes" in result
    assert outside.read_text(encoding="utf-8") == "outside body\n"
    assert get_approval_queue().list_pending("exec") == []
    assert ctx.sandbox_mounts == [
        {"path": str(outside.parent.resolve(strict=False)), "access": "rw"}
    ]


@pytest.mark.asyncio
async def test_existing_rw_mount_allows_write_file_without_legacy_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    mounted = tmp_path / "mounted"
    mounted.mkdir()
    target = mounted / "out.txt"
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(
        workspace,
        sandbox_mounts=[{"path": str(mounted), "access": "rw"}],
    ):
        result = await fs.write_file(str(target), "x")

    assert "Written 1 bytes" in result
    assert target.read_text(encoding="utf-8") == "x"


@pytest.mark.asyncio
async def test_existing_rw_mount_allows_edit_file_without_legacy_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    mounted = tmp_path / "mounted"
    mounted.mkdir()
    target = mounted / "out.txt"
    target.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(
        workspace,
        sandbox_mounts=[{"path": str(mounted), "access": "rw"}],
    ):
        result = await fs.edit_file(str(target), "old", "new")

    assert "Edited" in result
    assert target.read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_existing_ro_mount_write_requests_rw_mount_not_legacy_approval(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    mounted = tmp_path / "mounted"
    mounted.mkdir()
    target = mounted / "out.txt"

    with tool_context(
        workspace,
        sandbox_mounts=[{"path": str(mounted), "access": "ro"}],
    ):
        payload = json.loads(await fs.write_file(str(target), "x"))

    assert payload["status"] == "approval_required"
    assert payload["path"] == str(target.resolve(strict=False))
    assert payload["access"] == "rw"
    assert payload["approval_id"]
    assert not target.exists()


@pytest.mark.asyncio
async def test_list_dir_retry_accepts_path_approval_id_after_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    mounted = tmp_path / "mounted"
    mounted.mkdir()
    (mounted / "notes.txt").write_text("hello\n", encoding="utf-8")
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(
        workspace,
        sandbox_mounts=[{"path": str(mounted), "access": "ro"}],
    ):
        result = await fs.list_dir(str(mounted), approval_id="approved-path")

    assert "notes.txt" in result


@pytest.mark.asyncio
async def test_grep_search_does_not_follow_workspace_symlink_to_unmounted_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("needle secret-token\n", encoding="utf-8")
    link = workspace / "linked-secret.txt"
    try:
        link.symlink_to(outside_file)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("creating symlinks requires Windows developer mode or elevation")
        raise
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(workspace):
        result = await fs.grep_search("needle", path=str(workspace))

    assert "secret-token" not in result
    assert "outside current sandbox view" in result or "No matches" in result


@pytest.mark.asyncio
async def test_shell_read_only_workdir_outside_workspace_requests_ro_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    backend_calls: list[object] = []

    async def fail_backend(request: object, *, runtime: object = None) -> object:
        backend_calls.append(request)
        raise AssertionError("backend should not run before path access is granted")

    monkeypatch.setattr(shell, "run_under_backend", fail_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(workspace):
        payload = json.loads(await shell.exec_command("pwd", workdir=str(outside)))

    assert payload["status"] == "approval_required"
    approval_id = str(payload["approval_id"])
    assert payload["path"] == str(outside.resolve(strict=False))
    assert payload["access"] == "ro"
    assert payload["approvalKind"] == "sandbox_path"
    assert backend_calls == []

    with tool_context(workspace):
        pending = json.loads(
            await shell.exec_command("pwd", workdir=str(outside), approval_id=approval_id)
        )

    assert pending["status"] == "approval_pending"
    assert pending["approval_id"] == approval_id
    assert backend_calls == []


@pytest.mark.asyncio
async def test_shell_ro_workdir_mount_stays_read_only_in_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    backend_calls: list[SandboxRequest] = []

    async def fake_backend(request: SandboxRequest, *, runtime: object = None) -> object:
        backend_calls.append(request)
        return SimpleNamespace(stdout="", stderr="", returncode=0, backend_notes=[])

    monkeypatch.setattr(shell, "run_under_backend", fake_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(
        workspace,
        sandbox_mounts=[{"path": str(outside), "access": "ro"}],
    ):
        await shell.exec_command(
            "python -c 'open(\"x\", \"w\").write(\"1\")'",
            workdir=str(outside),
        )

    assert len(backend_calls) == 1
    request = backend_calls[0]
    workspace_mount = next(
        mount
        for mount in request.policy.mounts
        if str(mount.sandbox_path) == "/workspace"
    )
    outside_mount = next(
        mount
        for mount in request.policy.mounts
        if mount.host_path == outside.resolve(strict=False)
    )
    assert request.cwd == outside.resolve(strict=False)
    assert workspace_mount.host_path == workspace.resolve(strict=False)
    assert workspace_mount.mode == "rw"
    assert outside_mount.mode == "ro"


@pytest.mark.asyncio
async def test_shell_workdir_relative_write_requests_rw_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    backend_calls: list[object] = []

    async def fail_backend(request: object, *, runtime: object = None) -> object:
        backend_calls.append(request)
        raise AssertionError("backend should not run before path access is granted")

    monkeypatch.setattr(shell, "run_under_backend", fail_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(workspace):
        payload = json.loads(await shell.exec_command("echo ok > out.txt", workdir=str(outside)))

    assert payload["status"] == "approval_required"
    assert payload["path"] == str(outside.resolve(strict=False))
    assert payload["access"] == "rw"
    assert payload["approvalKind"] == "sandbox_path"
    assert backend_calls == []


@pytest.mark.asyncio
async def test_standard_shell_simple_read_path_outside_workspace_requests_ro_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    backend_calls: list[object] = []

    async def fail_backend(request: object, *, runtime: object = None) -> object:
        backend_calls.append(request)
        raise AssertionError("backend should not run before path access is granted")

    monkeypatch.setattr(shell, "run_under_backend", fail_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(workspace, run_mode="standard"):
        payload = json.loads(await shell.exec_command(f"ls {outside}"))

    assert payload["status"] == "approval_required"
    assert payload["path"] == str(outside.resolve(strict=False))
    assert payload["access"] == "ro"
    assert payload["approvalKind"] == "sandbox_path"
    assert backend_calls == []


@pytest.mark.asyncio
async def test_trusted_filesystem_read_path_outside_workspace_auto_mounts_without_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "notes.txt"
    target.write_text("trusted read\n", encoding="utf-8")
    _install_filesystem_read_backend()
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(workspace, run_mode="trusted") as ctx:
        result = await fs.read_file(str(target))

    assert "trusted read" in result
    assert get_approval_queue().list_pending("exec") == []
    assert ctx.sandbox_mounts == [{"path": str(target.resolve(strict=False)), "access": "ro"}]


@pytest.mark.asyncio
async def test_trusted_run_context_read_path_outside_workspace_auto_mounts_without_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "notes.txt"
    target.write_text("trusted context read\n", encoding="utf-8")
    _install_filesystem_read_backend()
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(workspace, run_mode=None) as ctx:
        ctx.sandbox_run_context = RunContext(
            run_mode=RunMode.TRUSTED,
            workspace=str(workspace),
        )
        result = await fs.read_file(str(target))

    assert "trusted context read" in result
    assert get_approval_queue().list_pending("exec") == []
    assert ctx.sandbox_mounts == [{"path": str(target.resolve(strict=False)), "access": "ro"}]


@pytest.mark.asyncio
async def test_trusted_shell_simple_read_path_outside_workspace_auto_mounts_without_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    backend_calls: list[object] = []

    async def fake_backend(request: object, *, runtime: object = None) -> object:
        backend_calls.append(request)
        return SimpleNamespace(stdout="listed\n", stderr="", returncode=0, backend_notes=[])

    monkeypatch.setattr(shell, "run_under_backend", fake_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(workspace, run_mode="trusted") as ctx:
        result = await shell.exec_command(f"ls {outside}")

    assert "exit_code=0" in result
    assert "listed" in result
    assert backend_calls
    assert get_approval_queue().list_pending("exec") == []
    assert ctx.sandbox_mounts == [{"path": str(outside.resolve(strict=False)), "access": "ro"}]


@pytest.mark.asyncio
async def test_trusted_shell_delete_existing_file_auto_mounts_file_without_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside" / "outside-sandbox-smoke.txt"
    outside.parent.mkdir()
    outside.write_text("hello\n", encoding="utf-8")
    backend_calls: list[SandboxRequest] = []

    async def fake_backend(request: SandboxRequest, *, runtime: object = None) -> object:
        backend_calls.append(request)
        return SimpleNamespace(stdout="", stderr="", returncode=0, backend_notes=[])

    monkeypatch.setattr(shell, "run_under_backend", fake_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=True, reason=""),
    )

    with tool_context(workspace, run_mode="trusted") as ctx:
        result = await shell.exec_command(f'del "{outside}"')

    assert "exit_code=0" in result
    assert backend_calls
    assert get_approval_queue().list_pending("exec") == []
    assert ctx.sandbox_mounts == [{"path": str(outside.resolve(strict=False)), "access": "rw"}]
    request = backend_calls[0]
    assert any(mount.host_path == outside for mount in request.policy.mounts)


@pytest.mark.asyncio
async def test_shell_write_to_protected_metadata_is_blocked_before_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".codex").mkdir()
    backend_calls: list[SandboxRequest] = []

    async def fake_backend(request: SandboxRequest, *, runtime: object = None) -> object:
        backend_calls.append(request)
        return SimpleNamespace(stdout="", stderr="", returncode=0, backend_notes=[])

    monkeypatch.setattr(shell, "run_under_backend", fake_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(workspace, run_mode="trusted"):
        git_result = await shell.exec_command(
            f"sh -lc 'printf \"%s\\n\" blocked > {repo}/.git/_sandbox_should_not_write.txt'"
        )
        codex_result = await shell.exec_command(
            f"sh -lc 'printf \"%s\\n\" blocked > {repo}/.codex/_sandbox_should_not_write.txt'"
        )

    git_payload = json.loads(git_result)
    codex_payload = json.loads(codex_result)
    assert git_payload["reason"] == "protected_metadata"
    assert git_payload["protected_name"] == ".git"
    assert codex_payload["reason"] == "protected_metadata"
    assert codex_payload["protected_name"] == ".codex"
    assert backend_calls == []
    assert not (repo / ".git/_sandbox_should_not_write.txt").exists()
    assert not (repo / ".codex/_sandbox_should_not_write.txt").exists()


@pytest.mark.asyncio
async def test_trusted_shell_delete_existing_file_under_rw_mount_adds_file_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    mounted = tmp_path / "outside"
    mounted.mkdir()
    outside = mounted / "outside-sandbox-smoke.txt"
    outside.write_text("hello\n", encoding="utf-8")
    backend_calls: list[SandboxRequest] = []

    async def fake_backend(request: SandboxRequest, *, runtime: object = None) -> object:
        backend_calls.append(request)
        return SimpleNamespace(stdout="", stderr="", returncode=0, backend_notes=[])

    monkeypatch.setattr(shell, "run_under_backend", fake_backend)
    monkeypatch.setattr(shell, "_windows_sandbox_backend_active", lambda runtime=None: True)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=True, reason=""),
    )

    with tool_context(
        workspace,
        run_mode="trusted",
        sandbox_mounts=[{"path": str(mounted.resolve(strict=False)), "access": "rw"}],
    ) as ctx:
        result = await shell.exec_command(f'del "{outside}"')

    assert "exit_code=0" in result
    assert backend_calls
    assert get_approval_queue().list_pending("exec") == []
    assert ctx.sandbox_mounts == [
        {"path": str(mounted.resolve(strict=False)), "access": "rw"},
        {"path": str(outside.resolve(strict=False)), "access": "rw"},
    ]
    request = backend_calls[0]
    assert any(mount.host_path == outside for mount in request.policy.mounts)


def test_windows_shell_policy_ignores_deleted_active_file_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.types import (
        MountSpec,
        NetworkMode,
        ResourceLimits,
        SandboxPolicy,
        SecurityLevel,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    stale = workspace / "sandbox_probe_workspace.txt"
    stale.write_text("workspace-ok", encoding="utf-8")
    stale.unlink()
    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(
            MountSpec(workspace, workspace, mode="rw"),
            MountSpec(stale, stale, mode="rw", required=False),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(),
        env_allowlist=(),
        require_approval=False,
    )
    monkeypatch.setattr(shell, "_windows_sandbox_backend_active", lambda runtime=None: True)

    with tool_context(
        workspace,
        run_mode="trusted",
        sandbox_mounts=[{"path": str(stale.resolve(strict=False)), "access": "rw"}],
    ):
        updated = shell._policy_with_active_tool_mounts(policy)

    assert stale not in {mount.host_path for mount in updated.mounts}
    assert workspace in {mount.host_path for mount in updated.mounts}


def test_shell_policy_preserves_workspace_rw_absolute_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.types import (
        SANDBOX_WORKSPACE_PATH,
        MountSpec,
        NetworkMode,
        ResourceLimits,
        SandboxPolicy,
        SecurityLevel,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(
            MountSpec(
                host_path=workspace,
                sandbox_path=SANDBOX_WORKSPACE_PATH,
                mode="rw",
                required=True,
            ),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(),
        env_allowlist=(),
        require_approval=False,
    )
    monkeypatch.setattr(shell, "_windows_sandbox_backend_active", lambda runtime=None: False)

    with tool_context(
        workspace,
        run_mode="trusted",
        sandbox_mounts=[{"path": str(workspace), "access": "ro"}],
    ):
        updated = shell._policy_with_active_tool_mounts(policy)

    mounts_by_sandbox = {str(mount.sandbox_path): mount for mount in updated.mounts}
    assert mounts_by_sandbox["/workspace"].mode == "rw"
    assert mounts_by_sandbox[str(workspace)].mode == "rw"


@pytest.mark.asyncio
async def test_shell_copy_from_outside_workspace_requests_ro_mount_before_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "notes.txt"
    target = workspace / "notes.txt"
    backend_calls: list[object] = []

    async def fail_backend(request: object, *, runtime: object = None) -> object:
        backend_calls.append(request)
        raise AssertionError("backend should not run before source path access is granted")

    monkeypatch.setattr(shell, "run_under_backend", fail_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(workspace, run_mode="standard"):
        payload = json.loads(await shell.exec_command(f"cp {source} {target}"))

    assert payload["status"] == "approval_required"
    assert payload["path"] == str(source.resolve(strict=False))
    assert payload["access"] == "ro"
    assert payload["approvalKind"] == "sandbox_path"
    assert backend_calls == []


@pytest.mark.asyncio
async def test_standard_shell_copy_to_outside_workspace_requests_rw_mount_before_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    source = workspace / "notes.txt"
    target = tmp_path / "outside" / "notes.txt"
    backend_calls: list[object] = []

    async def fail_backend(request: object, *, runtime: object = None) -> object:
        backend_calls.append(request)
        raise AssertionError("backend should not run before destination path access is granted")

    monkeypatch.setattr(shell, "run_under_backend", fail_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(workspace, run_mode="standard"):
        payload = json.loads(await shell.exec_command(f"cp {source} {target}"))

    assert payload["status"] == "approval_required"
    assert payload["path"] == str(target.resolve(strict=False))
    assert payload["access"] == "rw"
    assert payload["approvalKind"] == "sandbox_path"
    assert backend_calls == []


@pytest.mark.asyncio
async def test_trusted_shell_copy_to_outside_workspace_auto_mounts_rw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    source = workspace / "notes.txt"
    source.write_text("hello\n", encoding="utf-8")
    target = tmp_path / "outside" / "notes.txt"
    backend_calls: list[SandboxRequest] = []

    async def fake_backend(request: SandboxRequest, *, runtime: object = None) -> object:
        backend_calls.append(request)
        return SimpleNamespace(stdout="", stderr="", returncode=0, backend_notes=[])

    monkeypatch.setattr(shell, "run_under_backend", fake_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(workspace, run_mode="trusted") as ctx:
        result = await shell.exec_command(f"cp {source} {target}")

    assert "exit_code=0" in result
    assert backend_calls
    assert get_approval_queue().list_pending("exec") == []
    assert ctx.sandbox_mounts == [
        {"path": str(target.parent.resolve(strict=False)), "access": "rw"}
    ]
    request = backend_calls[0]
    assert any(mount.host_path == target.parent for mount in request.policy.mounts)


@pytest.mark.asyncio
async def test_trusted_shell_external_workdir_write_auto_mounts_rw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    backend_calls: list[SandboxRequest] = []

    async def fake_backend(request: SandboxRequest, *, runtime: object = None) -> object:
        backend_calls.append(request)
        return SimpleNamespace(stdout="", stderr="", returncode=0, backend_notes=[])

    monkeypatch.setattr(shell, "run_under_backend", fake_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(workspace, run_mode="trusted") as ctx:
        result = await shell.exec_command("echo hi > out.txt", workdir=str(outside))

    assert "exit_code=0" in result
    assert backend_calls
    assert get_approval_queue().list_pending("exec") == []
    assert ctx.sandbox_mounts == [{"path": str(outside.resolve(strict=False)), "access": "rw"}]
    request = backend_calls[0]
    assert any(mount.host_path == outside for mount in request.policy.mounts)


@pytest.mark.asyncio
async def test_shell_absolute_redirection_requests_rw_mount_before_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    target = tmp_path / "outside" / "out.txt"
    backend_calls: list[object] = []

    async def fail_backend(request: object, *, runtime: object = None) -> object:
        backend_calls.append(request)
        raise AssertionError("backend should not run before redirection target is granted")

    monkeypatch.setattr(shell, "run_under_backend", fail_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(workspace, run_mode="standard"):
        payload = json.loads(await shell.exec_command(f"echo hi > {target}"))

    assert payload["status"] == "approval_required"
    assert payload["path"] == str(target.resolve(strict=False))
    assert payload["access"] == "rw"
    assert payload["approvalKind"] == "sandbox_path"
    assert backend_calls == []


@pytest.mark.asyncio
async def test_shell_simple_read_path_full_host_access_does_not_request_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    backend_calls: list[object] = []
    host_calls: list[tuple[str, str | None]] = []

    async def fail_backend(request: object, *, runtime: object = None) -> object:
        backend_calls.append(request)
        raise AssertionError("full host access should not use the sandbox backend")

    async def fake_host(
        command: str,
        *,
        cwd: str | None,
        env: dict[str, str],
        stdin_bytes: bytes | None,
        effective_timeout: float,
    ) -> str:
        host_calls.append((command, cwd))
        return "host-ran"

    monkeypatch.setattr(shell, "run_under_backend", fail_backend)
    monkeypatch.setattr(shell, "_run_host_shell_command", fake_host)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    with tool_context(workspace, run_mode="full"):
        result = await shell.exec_command(f"ls {outside}")

    assert result == "host-ran"
    assert host_calls == [(f"ls {outside}", str(workspace.resolve()))]
    assert backend_calls == []


@pytest.mark.asyncio
async def test_path_request_approval_does_not_mutate_until_choice_is_resolved(
    tmp_path: Path,
) -> None:
    from opensquilla.gateway.rpc import RpcContext, get_dispatcher
    from opensquilla.sandbox.run_context import get_run_context

    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside" / "notes.txt"
    manager = SimpleNamespace()
    manager.node = SimpleNamespace(session_key="s1", agent_id="main", origin=None)

    async def _get_session(session_key: str):
        return manager.node if session_key == manager.node.session_key else None

    async def _update(session_key: str, **fields):
        for key, value in fields.items():
            setattr(manager.node, key, value)
        return manager.node

    manager.get_session = _get_session
    manager.update = _update
    config = SimpleNamespace(
        sandbox=SimpleNamespace(run_mode="standard", sandbox=True, security_grading=True),
        permissions=SimpleNamespace(default_mode="off"),
    )

    with tool_context(workspace):
        payload = json.loads(await fs.write_file(str(outside), "outside body\n"))

    approval_id = str(payload["approval_id"])
    pending = get_approval_queue().get(approval_id)
    assert pending.resolved is False
    assert outside.exists() is False
    saved_before = await get_run_context(manager, "s1", config=config, workspace=str(workspace))
    assert saved_before.mounts == ()

    result = await get_dispatcher().dispatch(
        "r1",
        "exec.approval.resolve",
        {"id": approval_id, "approved": True, "choice": "mount_rw_chat"},
        RpcContext(conn_id="test", session_manager=manager, config=config),
    )
    assert result.error is None, result.error

    saved_after = await get_run_context(manager, "s1", config=config, workspace=str(workspace))
    assert [(mount.path, mount.access, mount.scope) for mount in saved_after.mounts] == [
        (str(outside.resolve(strict=False)), "rw", "chat")
    ]


@pytest.mark.asyncio
async def test_write_retry_uses_resolved_rw_mount_even_with_stale_tool_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway.rpc import RpcContext, get_dispatcher

    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside" / "notes.txt"
    manager = SimpleNamespace()
    manager.node = SimpleNamespace(session_key="s1", agent_id="main", origin=None)

    async def _get_session(session_key: str):
        return manager.node if session_key == manager.node.session_key else None

    async def _update(session_key: str, **fields):
        for key, value in fields.items():
            setattr(manager.node, key, value)
        return manager.node

    manager.get_session = _get_session
    manager.update = _update
    config = SimpleNamespace(
        sandbox=SimpleNamespace(run_mode="standard", sandbox=True, security_grading=True),
        permissions=SimpleNamespace(default_mode="off"),
    )
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with tool_context(workspace):
        payload = json.loads(await fs.write_file(str(outside), "outside body\n"))
        approval_id = str(payload["approval_id"])

        result = await get_dispatcher().dispatch(
            "r1",
            "exec.approval.resolve",
            {"id": approval_id, "approved": True, "choice": "mount_rw_chat"},
            RpcContext(conn_id="test", session_manager=manager, config=config),
        )
        assert result.error is None, result.error

        retried = await fs.write_file(str(outside), "outside body\n", approval_id=approval_id)

    assert "Written 13 bytes" in retried
    assert outside.read_text(encoding="utf-8") == "outside body\n"


@pytest.mark.asyncio
async def test_write_request_rejects_ro_mount_choice(
    tmp_path: Path,
) -> None:
    from opensquilla.gateway.rpc import RpcContext, get_dispatcher

    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside" / "notes.txt"
    manager = SimpleNamespace()
    manager.node = SimpleNamespace(session_key="s1", agent_id="main", origin=None)

    async def _get_session(session_key: str):
        return manager.node if session_key == manager.node.session_key else None

    async def _update(session_key: str, **fields):
        for key, value in fields.items():
            setattr(manager.node, key, value)
        return manager.node

    manager.get_session = _get_session
    manager.update = _update
    config = SimpleNamespace(
        sandbox=SimpleNamespace(run_mode="standard", sandbox=True, security_grading=True),
        permissions=SimpleNamespace(default_mode="off"),
    )

    with tool_context(workspace):
        payload = json.loads(await fs.write_file(str(outside), "outside body\n"))
        approval_id = str(payload["approval_id"])

        result = await get_dispatcher().dispatch(
            "r1",
            "exec.approval.resolve",
            {"id": approval_id, "approved": True, "choice": "mount_ro_chat"},
            RpcContext(conn_id="test", session_manager=manager, config=config),
        )
        assert result.error is not None

    assert outside.exists() is False
