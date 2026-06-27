"""Unit tests for opensquilla.contrib.swebench.images (docker mocked)."""

import subprocess

import pytest

from opensquilla.contrib.swebench import images


class FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_run(plan: dict[str, int]):
    """Build a subprocess.run replacement keyed on argv[0:2] patterns.

    plan maps a space-joined argv prefix to a returncode; unmatched
    invocations fail the test.
    """
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):
        calls.append(list(cmd))
        for prefix, code in plan.items():
            if " ".join(cmd).startswith(prefix):
                return FakeCompleted(code)
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    runner.calls = calls
    return runner


def test_local_image_short_circuits(monkeypatch):
    fake = _fake_run({"docker image inspect": 0})
    monkeypatch.setattr(images.subprocess, "run", fake)
    name = images.ensure_image("django__django-16429", "princeton-nlp/SWE-bench_Verified")
    assert name == "sweb.eval.x86_64.django__django-16429:latest"
    # No pull should have happened.
    assert not any(c[1] == "pull" for c in fake.calls)


def test_pull_fallback_when_local_missing(monkeypatch):
    fake = _fake_run({"docker image inspect": 1, "docker pull": 0})
    monkeypatch.setattr(images.subprocess, "run", fake)
    name = images.ensure_image("django__django-16429", "princeton-nlp/SWE-bench_Verified")
    assert name == "swebench/sweb.eval.x86_64.django_1776_django-16429:latest"
    assert any(c[1] == "pull" for c in fake.calls)


def test_pull_disabled_raises(monkeypatch):
    fake = _fake_run({"docker image inspect": 1})
    monkeypatch.setattr(images.subprocess, "run", fake)
    with pytest.raises(images.ImageNotFoundError) as exc:
        images.ensure_image(
            "django__django-16429",
            "princeton-nlp/SWE-bench_Verified",
            pull=False,
        )
    assert "local lookup" in str(exc.value)


def test_all_strategies_fail_raises_with_guidance(monkeypatch):
    fake = _fake_run({"docker image inspect": 1, "docker pull": 1})
    monkeypatch.setattr(images.subprocess, "run", fake)
    with pytest.raises(images.ImageNotFoundError) as exc:
        images.ensure_image("django__django-16429", "princeton-nlp/SWE-bench_Verified")
    assert "docker pull" in str(exc.value)
    assert "prepare_images" in str(exc.value)


def test_pull_timeout_returns_none(monkeypatch):
    def timeout_run(cmd, **kwargs):
        if cmd[1] == "pull":
            raise subprocess.TimeoutExpired(cmd, 1)
        return FakeCompleted(1)

    monkeypatch.setattr(images.subprocess, "run", timeout_run)
    assert images.pull_image("django__django-16429") is None


def test_build_invokes_harness_and_rechecks_local(monkeypatch):
    state = {"built": False}

    def runner(cmd, **kwargs):
        joined = " ".join(str(c) for c in cmd)
        if "docker image inspect" in joined:
            return FakeCompleted(0 if state["built"] else 1)
        if "swebench.harness.prepare_images" in joined:
            state["built"] = True
            return FakeCompleted(0)
        if "docker pull" in joined:
            return FakeCompleted(1)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr(images.subprocess, "run", runner)
    name = images.ensure_image(
        "django__django-16429",
        "princeton-nlp/SWE-bench_Verified",
        pull=True,
        build=True,
    )
    assert name.startswith("sweb.eval.x86_64.")


def test_image_exists_locally_survives_missing_docker(monkeypatch):
    def no_docker(cmd, **kwargs):
        raise FileNotFoundError("docker not installed")

    monkeypatch.setattr(images.subprocess, "run", no_docker)
    assert images.image_exists_locally("sweb.eval.x86_64.x:latest") is False


def test_ensure_image_missing_docker_raises_image_not_found(monkeypatch):
    def no_docker(cmd, **kwargs):
        raise FileNotFoundError("docker not installed")

    monkeypatch.setattr(images.subprocess, "run", no_docker)
    with pytest.raises(images.ImageNotFoundError):
        images.ensure_image(
            "django__django-16429",
            "princeton-nlp/SWE-bench_Verified",
        )


def test_pull_image_survives_missing_docker(monkeypatch):
    def no_docker(cmd, **kwargs):
        raise FileNotFoundError("docker not installed")

    monkeypatch.setattr(images.subprocess, "run", no_docker)
    assert images.pull_image("django__django-16429") is None


def test_build_image_survives_missing_docker(monkeypatch):
    def no_docker(cmd, **kwargs):
        raise FileNotFoundError("no interpreter")

    monkeypatch.setattr(images.subprocess, "run", no_docker)
    assert images.build_image("django__django-16429", "princeton-nlp/SWE-bench_Verified") is None
