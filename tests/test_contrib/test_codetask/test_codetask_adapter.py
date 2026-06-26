"""Unit tests for opensquilla.contrib.codetask.adapter (subprocess mocked)."""

import subprocess as sp
import sys

import pytest

from opensquilla.contrib.codetask import adapter
from opensquilla.contrib.codetask.adapter import LocalAdapter


class FakePopen:
    """Minimal Popen stand-in for the adapter's communicate()-based flow."""

    def __init__(self, cmd, stdout="", returncode=0, stderr="", timeout=False, **kwargs):
        self.args = cmd
        self.pid = 4242
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._timeout = timeout
        self._calls = 0
        self.killed = False

    def communicate(self, timeout=None):
        self._calls += 1
        # Time out only on the first call (the bounded wait); the post-kill
        # drain call returns normally.
        if self._timeout and self._calls == 1:
            raise sp.TimeoutExpired(self.args, timeout or 1)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


def _install_popen(monkeypatch, captured, **popen_kw):
    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        captured["new_session"] = kwargs.get("start_new_session")
        captured["env"] = kwargs.get("env")
        captured["code"] = cmd[2]
        return FakePopen(cmd, **popen_kw)

    monkeypatch.setattr(adapter.subprocess, "Popen", fake_popen)


@pytest.mark.skipif(sys.platform == "win32", reason="code-task Windows support is WIP")
def test_argv_has_host_containment_flags(monkeypatch, tmp_path):
    captured = {}
    _install_popen(monkeypatch, captured, stdout='{"status": "ok", "text": "done", "usage": {}}')
    repo = tmp_path / "repo"
    repo.mkdir()
    out = LocalAdapter(model="m", timeout=10).run(
        "fix it", repo=repo, scratch_dir=tmp_path / "s", artifact_dir=tmp_path / "art"
    )
    assert out.success is True
    code = captured["code"]
    for flag in (
        "--workspace",
        "--workspace-strict",
        "--workspace-lockdown",
        "--scratch-dir",
        "--stateless",
        "--permissions",
    ):
        assert flag in code
    assert captured["cwd"] == str(repo)
    # Descendant-killable process group (codex review #6).
    assert captured["new_session"] is True


def test_api_key_never_in_argv(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret-xyz")
    captured = {}
    _install_popen(monkeypatch, captured, stdout='{"status": "ok", "text": "done"}')
    repo = tmp_path / "repo"
    repo.mkdir()
    LocalAdapter().run("x", repo=repo, scratch_dir=tmp_path / "s", artifact_dir=tmp_path / "a")
    assert all("sk-or-secret-xyz" not in part for part in captured["cmd"])


def test_timeout_kills_group_and_reports_timeout(monkeypatch, tmp_path):
    captured = {}
    _install_popen(monkeypatch, captured, timeout=True)
    killed = {"group": False}
    monkeypatch.setattr(
        adapter, "_kill_process_group", lambda proc: killed.__setitem__("group", True)
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    out = LocalAdapter(timeout=1).run(
        "x", repo=repo, scratch_dir=tmp_path / "s", artifact_dir=tmp_path / "a"
    )
    assert out.timeout is True
    assert out.finish_reason == "timeout"
    assert killed["group"] is True


def test_run_clears_stale_scratch_manifest(monkeypatch, tmp_path):
    # A leftover verification.json from a prior run reusing this run_id must
    # be wiped before the agent runs, so the runner cannot read a stale
    # manifest (codex review).
    captured = {}
    _install_popen(monkeypatch, captured, stdout='{"status": "ok", "text": "done"}')
    repo = tmp_path / "repo"
    repo.mkdir()
    scratch = tmp_path / "s"
    scratch.mkdir()
    stale = scratch / "verification.json"
    stale.write_text('{"testable": true, "stale": true}')

    LocalAdapter().run("x", repo=repo, scratch_dir=scratch, artifact_dir=tmp_path / "a")

    # The stale manifest is gone (scratch was recreated clean).
    assert not stale.exists()
    assert scratch.is_dir()


def test_run_points_agent_at_codetask_config(monkeypatch, tmp_path):
    # The agent subprocess must load code-task's own config (deny list + router)
    # via OPENSQUILLA_GATEWAY_CONFIG_PATH, while still inheriting the parent env.
    from opensquilla.contrib.codetask.config import agent_config_path

    captured = {}
    _install_popen(monkeypatch, captured, stdout='{"status": "ok", "text": "done"}')
    repo = tmp_path / "repo"
    repo.mkdir()
    LocalAdapter().run(
        "x", repo=repo, scratch_dir=tmp_path / "s", artifact_dir=tmp_path / "a"
    )
    env = captured["env"]
    assert env is not None
    # The agent now loads a PER-RUN config (derived from code-task's base config)
    # so its tool-result store is isolated to this run instead of the shared
    # global media root -- avoids the quadratic global-store rescan / spin.
    per_run_cfg = tmp_path / "a" / "agent-config.toml"
    assert env["OPENSQUILLA_GATEWAY_CONFIG_PATH"] == str(per_run_cfg)
    import tomllib

    cfg_text = per_run_cfg.read_text(encoding="utf-8")
    parsed = tomllib.loads(cfg_text)
    base = tomllib.loads(agent_config_path().read_text(encoding="utf-8"))
    # every base section survives the merge (deny list + router preserved)...
    for section in base:
        assert section in parsed, section
    # ...and media_root is pinned under THIS run's scratch (absolute).
    assert parsed["attachments"]["media_root"] == str(
        (tmp_path / "s").resolve() / "media"
    )
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.paths import media_root_from_config

    conf = GatewayConfig.load(str(per_run_cfg))
    assert media_root_from_config(conf) == (tmp_path / "s").resolve() / "media"
    assert "PATH" in env  # inherits parent env (OPENROUTER_API_KEY passes through)


def test_per_run_config_merges_existing_attachments(monkeypatch, tmp_path):
    """If the base agent config ever gains an [attachments] table, the per-run
    config must OVERRIDE media_root (merge), not append a duplicate table that
    breaks tomllib parsing."""
    import tomllib

    from opensquilla.contrib.codetask import adapter as adapter_mod

    base = tmp_path / "base.toml"
    base.write_text(
        '[attachments]\nmedia_root = "/old/global"\npersist_transcripts = true\n'
        "[tools]\ndeny = [\"x\"]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(adapter_mod, "agent_config_path", lambda: base)

    captured = {}
    _install_popen(monkeypatch, captured, stdout='{"status": "ok", "text": "done"}')
    repo = tmp_path / "repo"
    repo.mkdir()
    adapter_mod.LocalAdapter().run(
        "x", repo=repo, scratch_dir=tmp_path / "s", artifact_dir=tmp_path / "a"
    )
    cfg = tomllib.loads((tmp_path / "a" / "agent-config.toml").read_text("utf-8"))
    # overridden, not duplicated; sibling key + other sections preserved
    assert cfg["attachments"]["media_root"] == str((tmp_path / "s").resolve() / "media")
    assert cfg["attachments"]["persist_transcripts"] is True
    assert cfg["tools"]["deny"] == ["x"]
