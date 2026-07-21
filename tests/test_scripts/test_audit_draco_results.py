from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from opensquilla.eval.draco_artifact_integrity import seal_result_row

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "audit_draco_results.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_draco_results_under_test", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = _load_audit_module()


def _valid_row(group: str, task_hash: str, fingerprint: str) -> dict[str, object]:
    row: dict[str, object] = {
        "group": group,
        "task_id": "task-1",
        "task_input_sha256": task_hash,
        "run_compatibility_fingerprint": fingerprint,
        "error": None,
        "final_text": "answer",
        "quality_total": 80.0,
        "judge": {"score_status": "complete", "judge_error_count": 0},
        "ensemble_trace": {},
    }
    if group in audit.FIXED_MODELS:
        row["provider_spec"] = {"model": audit.FIXED_MODELS[group]}
        row["usage"] = {"model": audit.FIXED_MODELS[group]}
    return row


def test_audit_excludes_incompatible_duplicate_shard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = {"id": "task-1", "prompt": "prompt", "rubric": {"criteria": ["a"]}}
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(json.dumps(task) + "\n", encoding="utf-8")
    task_hash = audit.canonical_json_sha256(task)
    fingerprints = {group: f"sha256:{group.lower()}" for group in audit.GROUPS}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"run_compatibility": {"fingerprints": fingerprints}}),
        encoding="utf-8",
    )
    rows = [
        _valid_row(group, task_hash, fingerprints[group]) for group in audit.GROUPS
    ]
    rows.append(_valid_row("B1", task_hash, "sha256:incompatible"))
    result_path = tmp_path / "results.jsonl"
    result_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "audit"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--input",
            str(input_path),
            "--result",
            str(result_path),
            "--output-dir",
            str(output_dir),
            "--expected-manifest",
            str(manifest_path),
        ],
    )

    assert audit.main() == 0

    report = json.loads((output_dir / "draco_audit.json").read_text(encoding="utf-8"))
    assert report["complete"] is True
    assert report["raw_duplicate_attempts"] == 1
    assert report["all_attempt_invalid_reason_counts"][
        "run_compatibility_fingerprint_mismatch"
    ] == 1
    final_rows = audit.read_jsonl(output_dir / "draco_audit.final.jsonl")
    assert len(final_rows) == 6
    b1 = next(row for row in final_rows if row["group"] == "B1")
    assert b1["run_compatibility_fingerprint"] == fingerprints["B1"]


def test_expected_manifest_without_fingerprints_fails(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="lacks run_compatibility"):
        audit.load_expected_fingerprints(path)


def test_audit_supports_single_group_and_max_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks = [
        {"id": "task-1", "prompt": "first"},
        {"id": "task-2", "prompt": "second"},
    ]
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(
        "\n".join(json.dumps(task) for task in tasks) + "\n",
        encoding="utf-8",
    )
    fingerprint = "sha256:b2"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"run_compatibility": {"fingerprints": {"B2": fingerprint}}}
        ),
        encoding="utf-8",
    )
    result_path = tmp_path / "result.jsonl"
    result_path.write_text(
        json.dumps(
            _valid_row(
                "B2",
                audit.canonical_json_sha256(tasks[0]),
                fingerprint,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "audit"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--input",
            str(input_path),
            "--result",
            str(result_path),
            "--output-dir",
            str(output_dir),
            "--expected-manifest",
            str(manifest_path),
            "--groups",
            "B2",
            "--max-tasks",
            "1",
        ],
    )

    assert audit.main() == 0
    report = json.loads((output_dir / "draco_audit.json").read_text())
    assert report["groups"] == ["B2"]
    assert report["input_task_count"] == 1
    assert report["expected_unique"] == 1


def test_required_result_evidence_rejects_a_mutated_sealed_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = {"id": "task-1", "prompt": "prompt"}
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(json.dumps(task) + "\n", encoding="utf-8")
    fingerprint = "sha256:b2"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"run_compatibility": {"fingerprints": {"B2": fingerprint}}}
        ),
        encoding="utf-8",
    )
    sealed = seal_result_row(
        _valid_row(
            "B2",
            audit.canonical_json_sha256(task),
            fingerprint,
        )
    )
    sealed["final_text"] = "mutated after sealing"
    result_path = tmp_path / "result.jsonl"
    result_path.write_text(json.dumps(sealed) + "\n", encoding="utf-8")
    output_dir = tmp_path / "audit"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--input",
            str(input_path),
            "--result",
            str(result_path),
            "--output-dir",
            str(output_dir),
            "--expected-manifest",
            str(manifest_path),
            "--groups",
            "B2",
            "--require-result-evidence",
        ],
    )

    assert audit.main() == 2
    report = json.loads((output_dir / "draco_audit.json").read_text())
    assert report["complete"] is False
    assert report["result_evidence_enforced"] is True
    assert report["all_attempt_invalid_reason_counts"] == {
        "invalid_result_evidence": 1
    }
