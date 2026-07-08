from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_script():
    script_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "experiments"
        / "check_docker_image_lock.py"
    )
    spec = importlib.util.spec_from_file_location("check_docker_image_lock", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_lock(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tag": "eval-lock-v1",
                "records": [
                    {
                        "instance_id": "demo__repo-1",
                        "image_ref": "sweb.eval.x86_64.demo__repo-1:eval-lock-v1",
                        "image_id": "sha256:expected1",
                    },
                    {
                        "instance_id": "demo__repo-2",
                        "image_ref": "sweb.eval.x86_64.demo__repo-2:eval-lock-v1",
                        "image_id": "sha256:expected2",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_check_docker_image_lock_accepts_matching_lock(monkeypatch, tmp_path, capsys) -> None:
    script = _load_script()
    lock = tmp_path / "images.lock.json"
    _write_lock(lock)
    instances = tmp_path / "instances.txt"
    instances.write_text("demo__repo-1\ndemo__repo-2\n", encoding="utf-8")

    def fake_run(args, **kwargs):
        image_ref = args[2]
        if image_ref.endswith("demo__repo-1:eval-lock-v1"):
            return subprocess.CompletedProcess(args, 0, stdout="sha256:expected1\n", stderr="")
        if image_ref.endswith("demo__repo-2:eval-lock-v1"):
            return subprocess.CompletedProcess(args, 0, stdout="sha256:expected2\n", stderr="")
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="missing")

    monkeypatch.setattr(script.subprocess, "run", fake_run)

    rc = script.main(["--lock", str(lock), "--instance-file", str(instances)])

    assert rc == 0
    assert "checked=2" in capsys.readouterr().out


def test_check_docker_image_lock_fails_on_digest_mismatch(monkeypatch, tmp_path, capsys) -> None:
    script = _load_script()
    lock = tmp_path / "images.lock.json"
    _write_lock(lock)
    instances = tmp_path / "instances.txt"
    instances.write_text("demo__repo-1\n", encoding="utf-8")

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="sha256:wrong\n", stderr="")

    monkeypatch.setattr(script.subprocess, "run", fake_run)

    rc = script.main(["--lock", str(lock), "--instance-file", str(instances)])

    assert rc == 1
    assert "digest_mismatch" in capsys.readouterr().err


def test_check_docker_image_lock_fails_on_missing_lock_record(tmp_path, capsys) -> None:
    script = _load_script()
    lock = tmp_path / "images.lock.json"
    _write_lock(lock)
    instances = tmp_path / "instances.txt"
    instances.write_text("demo__repo-3\n", encoding="utf-8")

    rc = script.main(["--lock", str(lock), "--instance-file", str(instances)])

    assert rc == 1
    assert "missing_lock_record" in capsys.readouterr().err
