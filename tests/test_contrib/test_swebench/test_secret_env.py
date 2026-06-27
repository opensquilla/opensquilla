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
        content = open(path).read()
        assert "OPENROUTER_API_KEY=sk-or-test-123" in content
    finally:
        os.unlink(path)


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
            assert "sk-or-supersecret" in open(env_path).read()
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
