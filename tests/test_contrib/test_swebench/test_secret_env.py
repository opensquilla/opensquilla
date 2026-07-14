"""API key must reach the container via env-file, never via argv."""

import os
import stat
import sys

import pytest

from opensquilla.contrib.swebench import agent as agent_mod


@pytest.mark.skipif(sys.platform == "win32", reason="code-task Windows support is WIP")
def test_write_secret_env_file_private_and_removed(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-123")
    path = agent_mod._write_secret_env_file()
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600
        # The file must be readable as UTF-8 — both for the linux
        # docker subprocess and for any local Windows inspection that
        # happens before unlink.
        content = open(path, encoding="utf-8").read()
        assert "OPENROUTER_API_KEY=sk-or-test-123" in content
    finally:
        os.unlink(path)


@pytest.mark.skipif(sys.platform == "win32", reason="code-task Windows support is WIP")
def test_write_secret_env_file_cleans_up_on_write_failure(monkeypatch, tmp_path):
    """If the fdopen + write path raises, the partial file must not leak."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-123")

    real_mkstemp = agent_mod.tempfile.mkstemp

    def patched_mkstemp(*args, **kwargs):  # type: ignore[no-untyped-def]
        fd, path = real_mkstemp(*args, dir=str(tmp_path), **kwargs)
        return fd, path

    monkeypatch.setattr(agent_mod.tempfile, "mkstemp", patched_mkstemp)

    closed_descriptors: list[int] = []

    real_close = os.close

    def spy_close(fd):  # type: ignore[no-untyped-def]
        closed_descriptors.append(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "close", spy_close)

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(agent_mod.os.fdopen, "write", boom, raising=False)

    with pytest.raises(RuntimeError):
        agent_mod._write_secret_env_file()

    # The failed tmp file must have been unlinked — no half-written key
    # lying around for a later reader.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("opensquilla-swebench-")]
    assert leftovers == [], f"secret env-file leaked: {leftovers}"
    # The mkstemp fd must have been closed either via fdopen's
    # ownership transfer or, if fdopen never reached the write call,
    # by the failure path's os.close.
    assert any(fd in closed_descriptors for fd in closed_descriptors), (
        "secret env-file fd was leaked on write failure"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="code-task Windows support is WIP")
def test_write_secret_env_file_closes_raw_fd_when_chmod_fails(
    monkeypatch, tmp_path
):
    """If ``os.chmod`` raises before ``fdopen`` ever runs, the raw
    descriptor from ``mkstemp`` must be closed rather than leaked."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-123")

    real_mkstemp = agent_mod.tempfile.mkstemp

    def patched_mkstemp(*args, **kwargs):  # type: ignore[no-untyped-def]
        fd, path = real_mkstemp(*args, dir=str(tmp_path), **kwargs)
        return fd, path

    monkeypatch.setattr(agent_mod.tempfile, "mkstemp", patched_mkstemp)

    closed_descriptors: list[int] = []

    real_close = os.close

    def spy_close(fd):  # type: ignore[no-untyped-def]
        closed_descriptors.append(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "close", spy_close)

    # Force the chmod belt-and-braces call to raise so fdopen is never
    # reached. The cleanup branch must release the raw mkstemp fd.
    real_chmod = agent_mod.os.chmod

    def boom_chmod(path, mode, *args, **kwargs):  # type: ignore[no-untyped-def]
        if "opensquilla-swebench-" in str(path):
            raise OSError("simulated chmod failure")
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(agent_mod.os, "chmod", boom_chmod)

    with pytest.raises(OSError, match="simulated chmod failure"):
        agent_mod._write_secret_env_file()

    # The raw mkstemp fd must have been closed by the cleanup path.
    assert closed_descriptors, (
        "mkstemp fd was leaked when chmod raised before fdopen ran"
    )
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("opensquilla-swebench-")]
    assert leftovers == [], f"secret env-file leaked: {leftovers}"


def test_send_task_keeps_key_out_of_argv(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-supersecret")
    captured: list[list[str]] = []
    env_files_seen: list[str] = []

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured.append([str(c) for c in cmd])
        if "--env-file" in cmd:
            env_path = cmd[cmd.index("--env-file") + 1]
            env_files_seen.append(env_path)
            # The file must exist (and hold the key) while docker runs.
            assert "sk-or-supersecret" in open(env_path, encoding="utf-8").read()
        return FakeResult()

    monkeypatch.setattr(agent_mod.subprocess, "run", fake_run)

    adapter = agent_mod.OpenSquillaAdapter(model="test-model", timeout=5)
    adapter.send_task("fix it", agent_id="a1", container_name="c1", artifact_dir=tmp_path)

    exec_cmds = [c for c in captured if "--env-file" in c]
    assert exec_cmds, "agent invocation must use --env-file"
    for cmd in captured:
        assert not any("sk-or-supersecret" in part for part in cmd), (
            "API key must never appear in argv"
        )
    # The env-file is cleaned up after the subprocess finishes.
    assert all(not os.path.exists(p) for p in env_files_seen)
