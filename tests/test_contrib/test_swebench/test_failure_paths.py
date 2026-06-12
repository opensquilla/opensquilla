"""Failure-path regression tests (docker missing, workspace init crash).

These guard the fixes from the Phase-1 review: docker probes must not
hang or crash workspace construction, a failed construction must still
be recorded, and container cleanup must only touch untracked files.
"""

import json
import subprocess

from opensquilla.contrib.swebench import agent as agent_mod
from opensquilla.contrib.swebench import orchestrator, workspace
from opensquilla.contrib.swebench.types import InstanceState


class _StubAdapter:
    def create_agent(self, agent_id):
        pass

    def delete_agent(self, agent_id):
        pass

    def backup_session(self, agent_id, dest):
        pass


def test_resolve_image_survives_missing_docker(monkeypatch):
    def no_docker(cmd, **kwargs):
        raise FileNotFoundError("docker not installed")

    monkeypatch.setattr(workspace.subprocess, "run", no_docker)
    name = workspace.SWEBenchWorkspace._resolve_image("django__django-16429")
    assert name == "sweb.eval.x86_64.django__django-16429:latest"


def test_resolve_image_survives_inspect_timeout(monkeypatch):
    def hangs(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(workspace.subprocess, "run", hangs)
    name = workspace.SWEBenchWorkspace._resolve_image("django__django-16429")
    assert name == "sweb.eval.x86_64.django__django-16429:latest"


def test_run_one_instance_records_workspace_init_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSQUILLA_SWEBENCH_ARTIFACTS_DIR", str(tmp_path))

    class ExplodingWorkspace:
        def __init__(self, instance_id):
            raise RuntimeError("docker daemon unreachable")

    monkeypatch.setattr(orchestrator, "SWEBenchWorkspace", ExplodingWorkspace)

    record = orchestrator.run_one_instance(
        instance={"instance_id": "demo__demo-1", "base_commit": "abc123"},
        adapter=_StubAdapter(),
        model_name="test-model",
        run_id="failrun",
    )

    assert record.state == InstanceState.FAILED
    assert "docker daemon unreachable" in (record.error or "")
    metadata = json.loads((tmp_path / "failrun" / "demo__demo-1" / "metadata.json").read_text())
    assert metadata["state"] == "failed"
    state_lines = (tmp_path / "failrun" / "state.jsonl").read_text().strip().splitlines()
    assert len(state_lines) == 1


def test_cleanup_only_removes_untracked_files(monkeypatch):
    captured: dict = {}

    def capture(cmd, **kwargs):
        captured["script"] = cmd[-1]

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(agent_mod.subprocess, "run", capture)
    agent_mod._cleanup_opensquilla_metadata("some-container")
    script = captured["script"]
    assert "git ls-files --error-unmatch" in script
    assert "rm -rf" in script


def test_cleanup_swallows_timeout(monkeypatch):
    def hangs(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(agent_mod.subprocess, "run", hangs)
    # Must not raise.
    agent_mod._cleanup_opensquilla_metadata("some-container")
