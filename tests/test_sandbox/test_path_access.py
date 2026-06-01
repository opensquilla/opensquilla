from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.sandbox.path_validation import decide_path_access
from opensquilla.tools.builtin import filesystem as fs
from opensquilla.tools.builtin import shell
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


@contextmanager
def tool_context(
    workspace: Path,
    *,
    run_mode: str = "standard",
    sandbox_mounts: list[dict[str, object]] | None = None,
) -> Iterator[ToolContext]:
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.CLI,
        workspace_dir=str(workspace),
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
def sandbox_runtime(tmp_path: Path) -> Iterator[None]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    configure_runtime(
        SandboxSettings(run_mode="standard", backend="noop", allow_legacy_mode=True),
        workspace=workspace,
    )
    try:
        yield
    finally:
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


def test_write_request_asks_for_rw_mount(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sibling = tmp_path / "sibling" / "notes.txt"

    decision = decide_path_access(sibling, workspace=workspace, write=True)

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
async def test_filesystem_read_outside_workspace_requests_ro_mount(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside" / "notes.txt"
    outside.parent.mkdir()
    outside.write_text("outside body\n", encoding="utf-8")

    with tool_context(workspace):
        payload = json.loads(await fs.read_file(str(outside)))

    assert payload["status"] == "path_access_required"
    assert payload["path"] == str(outside.resolve(strict=False))
    assert payload["access"] == "ro"
    assert "outside the current sandbox view" in payload["message"]


@pytest.mark.asyncio
async def test_filesystem_write_outside_workspace_requests_rw_mount(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    outside = tmp_path / "outside" / "notes.txt"

    with tool_context(workspace):
        payload = json.loads(await fs.write_file(str(outside), "outside body\n"))

    assert payload["status"] == "path_access_required"
    assert payload["path"] == str(outside.resolve(strict=False))
    assert payload["access"] == "rw"
    assert not outside.exists()


@pytest.mark.asyncio
async def test_shell_workdir_outside_workspace_requests_rw_mount(
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

    assert payload["status"] == "path_access_required"
    assert payload["path"] == str(outside.resolve(strict=False))
    assert payload["access"] == "rw"
    assert backend_calls == []
