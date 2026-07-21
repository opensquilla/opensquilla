from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from opensquilla.eval.draco_artifact_integrity import (
    seal_result_row,
    trace_row_from_result,
    verify_result_row_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
PREPARE_CANARY = ROOT / "scripts" / "experiments" / "prepare_draco_b2_canary.py"
SEAL_ARTIFACTS = ROOT / "scripts" / "experiments" / "seal_draco_b2_artifacts.py"
CAPTURE_RUNTIME = (
    ROOT / "scripts" / "experiments" / "capture_draco_runtime_environment.py"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_full_result_hash_and_exact_trace_projection_fail_on_mutation() -> None:
    row = seal_result_row(
        {
            "row_index": 1,
            "group": "B2",
            "task_id": "task-1",
            "final_text": "answer",
            "execution": {"generation_attempts": [{"attempt": 1}]},
            "usage": {"billed_cost": 0.25},
        }
    )
    assert verify_result_row_evidence(row) is True
    trace = trace_row_from_result(row)
    assert trace == trace_row_from_result(row)

    changed_result = {**row, "final_text": "different"}
    assert verify_result_row_evidence(changed_result) is False
    changed_trace = json.loads(json.dumps(trace))
    changed_trace["execution"]["generation_attempts"][0]["attempt"] = 2
    assert changed_trace != trace_row_from_result(row)


def test_canary_is_disjoint_and_only_changes_scheduling_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(PREPARE_CANARY, "prepare_draco_canary_test")
    benchmark = tmp_path / "mini.jsonl"
    benchmark.write_text(
        json.dumps({"id": "formal-task", "prompt": "formal prompt"}) + "\n",
        encoding="utf-8",
    )
    base = {
        "profile_id": "frozen",
        "benchmark_input": {"task_count": 1},
        "runner": {"mode": "agent_loop", "concurrency": 5},
        "judge": {"model": "judge", "repeats": 3, "concurrency": 6},
        "ensemble": {"members": ["unchanged"]},
    }
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")
    output_input = tmp_path / "canary.jsonl"
    output_config = tmp_path / "canary-config.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(PREPARE_CANARY),
            "--base-config",
            str(base_path),
            "--benchmark-input",
            str(benchmark),
            "--output-input",
            str(output_input),
            "--output-config",
            str(output_config),
        ],
    )

    assert module.main() == 0
    canary = json.loads(output_input.read_text(encoding="utf-8"))
    config = json.loads(output_config.read_text(encoding="utf-8"))
    assert canary["id"] != "formal-task"
    assert canary["prompt"] != "formal prompt"
    assert "web_search" in canary["prompt"] and "web_fetch" in canary["prompt"]
    assert config["runner"] == {"mode": "agent_loop", "concurrency": 1}
    assert config["judge"] == {
        "model": "judge",
        "repeats": 3,
        "concurrency": 1,
    }
    assert config["ensemble"] == base["ensemble"]
    assert os.stat(output_input).st_mode & 0o777 == 0o600
    assert os.stat(output_config).st_mode & 0o777 == 0o600


def test_artifact_snapshot_detects_post_audit_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(SEAL_ARTIFACTS, "seal_draco_artifacts_test")
    artifact = tmp_path / "result.jsonl"
    artifact.write_text("sealed\n", encoding="utf-8")
    artifact.chmod(0o600)
    snapshot = tmp_path / "snapshot.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SEAL_ARTIFACTS),
            "snapshot",
            str(snapshot),
            "--root",
            str(tmp_path),
            "--file",
            str(artifact),
        ],
    )
    assert module.main() == 0
    module.verify_snapshot(snapshot)

    artifact.write_text("mutated\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after audit"):
        module.verify_snapshot(snapshot)


def test_recursive_snapshot_is_closed_and_portable_after_archiving(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(SEAL_ARTIFACTS, "seal_draco_artifacts_recursive_test")
    source = tmp_path / "source"
    nested = source / "strict-structure-audit"
    nested.mkdir(parents=True)
    result = source / "result.jsonl"
    report = nested / "report.json"
    result.write_text("sealed\n", encoding="utf-8")
    report.write_text("{}\n", encoding="utf-8")
    result.chmod(0o600)
    report.chmod(0o600)
    snapshot = source / "artifact-snapshot.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SEAL_ARTIFACTS),
            "snapshot",
            str(snapshot),
            "--root",
            str(source),
            "--recursive",
            "--allow-after",
            "FORMAL_RUN_SUCCESS.json",
        ],
    )
    assert module.main() == 0
    module.verify_snapshot(snapshot)

    extra = source / "unexpected.jsonl"
    extra.write_text("pollution\n", encoding="utf-8")
    extra.chmod(0o600)
    with pytest.raises(ValueError, match="artifact set changed"):
        module.verify_snapshot(snapshot)
    extra.unlink()

    archived = tmp_path / "archived"
    shutil.copytree(source, archived)
    archived_snapshot = archived / snapshot.name
    module.verify_snapshot(archived_snapshot)
    (archived / "result.jsonl").write_text("mutated copy\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after audit"):
        module.verify_snapshot(archived_snapshot)


def test_runtime_environment_capture_is_verifiable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(CAPTURE_RUNTIME, "capture_draco_runtime_test")
    evidence = tmp_path / "runtime-environment.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(CAPTURE_RUNTIME),
            "capture",
            str(evidence),
            "--repo",
            str(ROOT),
        ],
    )
    assert module.main() == 0
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(CAPTURE_RUNTIME),
            "verify",
            str(evidence),
            "--repo",
            str(ROOT),
        ],
    )
    assert module.main() == 0

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["environment_sha256"] = "0" * 64
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="runtime changed"):
        module.main()
