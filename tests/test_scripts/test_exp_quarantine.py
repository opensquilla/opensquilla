from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="experiment tooling is POSIX-only (fcntl file locking)",
)

ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / "scripts" / "experiments"


def _load_script(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# exp_common contamination helpers
# ---------------------------------------------------------------------------


def test_artifact_basename_normalizes_paths_and_names():
    common = _load_script("exp_common")
    assert common.artifact_basename("batch-a") == "batch-a"
    assert common.artifact_basename("/data/artifacts/batch-a") == "batch-a"
    assert common.artifact_basename("/data/artifacts/batch-a/") == "batch-a"
    assert common.artifact_basename(Path("/data/artifacts/batch-a")) == "batch-a"


def test_load_contaminations_defaults_when_missing(tmp_path):
    common = _load_script("exp_common")
    data = common.load_contaminations(tmp_path)
    assert data["classes"] == {}
    assert data["version"] == 1


def test_contamination_class_for_matches_by_basename(tmp_path):
    common = _load_script("exp_common")
    _write_json(
        tmp_path / "contaminations.json",
        {
            "version": 1,
            "classes": {
                "leak_class": {"artifact_names": ["batch-a", "batch-b"]},
            },
        },
    )
    assert common.contamination_class_for(tmp_path, "batch-a") == "leak_class"
    assert (
        common.contamination_class_for(tmp_path, "/artifacts/batch-b/") == "leak_class"
    )
    assert common.contamination_class_for(tmp_path, "batch-clean") is None
    assert common.contamination_class_for(tmp_path, "") is None


def test_contamination_class_for_tolerates_malformed_registry(tmp_path):
    common = _load_script("exp_common")
    _write_json(
        tmp_path / "contaminations.json",
        {"classes": {"bad": "not-a-dict", "worse": {"artifact_names": "not-a-list"}}},
    )
    assert common.contamination_class_for(tmp_path, "batch-a") is None


# ---------------------------------------------------------------------------
# exp_quarantine CLI
# ---------------------------------------------------------------------------


def _ledger_with_runs(tmp_path: Path) -> Path:
    ledger = tmp_path / "ledger"
    dirty_run = ledger / "runs" / "exp-dirty"
    clean_run = ledger / "runs" / "exp-clean"
    _write_json(
        dirty_run / "artifacts.json",
        {"artifacts": ["/data/artifacts/batch-a", "/data/artifacts/batch-x"]},
    )
    _write_json(dirty_run / "manifest.json", {"exp_id": "exp-dirty"})
    _write_json(
        clean_run / "artifacts.json", {"artifacts": ["/data/artifacts/batch-clean"]}
    )
    _write_json(clean_run / "manifest.json", {"exp_id": "exp-clean"})
    return ledger


def test_register_creates_registry_and_stamps_runs(tmp_path, monkeypatch, capsys):
    ledger = _ledger_with_runs(tmp_path)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    quarantine = _load_script("exp_quarantine")
    names_file = tmp_path / "names.json"
    _write_json(names_file, ["batch-a", "/data/artifacts/batch-b/", "batch-a"])

    rc = quarantine.main(
        [
            "register",
            "--contamination-class",
            "leak_class",
            "--names-file",
            str(names_file),
            "--description",
            "compaction marker leak",
            "--evidence",
            "audit/REPORT.md",
            "--boundary-commit",
            "feedc0de",
            "--boundary-commit",
            "abadcafe",
        ]
    )
    assert rc == 0

    registry = json.loads((ledger / "contaminations.json").read_text(encoding="utf-8"))
    entry = registry["classes"]["leak_class"]
    assert entry["artifact_names"] == ["batch-a", "batch-b"]
    assert entry["boundary_commits"] == ["abadcafe", "feedc0de"]
    assert entry["description"] == "compaction marker leak"
    assert entry["registered_at"]

    stamp = json.loads(
        (ledger / "runs" / "exp-dirty" / "contamination.json").read_text(
            encoding="utf-8"
        )
    )
    assert stamp["classes"]["leak_class"]["matched_artifact_names"] == ["batch-a"]
    assert not (ledger / "runs" / "exp-clean" / "contamination.json").exists()

    events = [
        json.loads(line)
        for line in (ledger / "experiments.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert events[-1]["event"] == "contamination_registered"
    assert events[-1]["artifact_names_new"] == 2
    assert events[-1]["stamped_run_dirs"] == ["exp-dirty"]

    out = capsys.readouterr().out
    assert "registered leak_class: 2 artifact names (2 new)" in out


def test_register_uses_exact_match_not_substring(tmp_path, monkeypatch):
    # A registered name that is a substring of an unrelated, longer batch name
    # in a clean run must NOT stamp that clean run - matching is exact-basename,
    # consistent with contamination_class_for.
    ledger = tmp_path / "ledger"
    unrelated_run = ledger / "runs" / "exp-unrelated"
    _write_json(
        unrelated_run / "artifacts.json",
        {"artifacts": ["/data/artifacts/batch-a-extended-run"]},
    )
    _write_json(unrelated_run / "manifest.json", {"exp_id": "exp-unrelated"})
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    quarantine = _load_script("exp_quarantine")
    names_file = tmp_path / "names.json"
    _write_json(names_file, ["batch-a"])

    rc = quarantine.main(
        [
            "register",
            "--contamination-class",
            "leak_class",
            "--names-file",
            str(names_file),
            "--description",
            "leak",
        ]
    )
    assert rc == 0
    assert not (unrelated_run / "contamination.json").exists()


def test_register_rejects_names_that_normalize_to_empty(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "ledger"
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    quarantine = _load_script("exp_quarantine")
    names_file = tmp_path / "names.json"
    # "/" is non-empty pre-normalization but collapses to "" via
    # artifact_basename - it must not slip into the registry (an empty name
    # previously substring-matched, and would exact-match, every run).
    _write_json(names_file, ["/", "///"])
    rc = quarantine.main(
        [
            "register",
            "--contamination-class",
            "leak_class",
            "--names-file",
            str(names_file),
            "--description",
            "leak",
        ]
    )
    assert rc == 2
    assert "names file is empty" in capsys.readouterr().err


def test_register_is_idempotent_and_merges_new_names(tmp_path, monkeypatch, capsys):
    ledger = _ledger_with_runs(tmp_path)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    quarantine = _load_script("exp_quarantine")
    names_file = tmp_path / "names.json"
    _write_json(names_file, ["batch-a"])
    base_args = [
        "register",
        "--contamination-class",
        "leak_class",
        "--names-file",
        str(names_file),
        "--description",
        "leak",
    ]
    assert quarantine.main(base_args) == 0
    assert quarantine.main(base_args) == 0
    registry = json.loads((ledger / "contaminations.json").read_text(encoding="utf-8"))
    assert registry["classes"]["leak_class"]["artifact_names"] == ["batch-a"]

    _write_json(names_file, ["batch-b"])
    assert quarantine.main(base_args) == 0
    registry = json.loads((ledger / "contaminations.json").read_text(encoding="utf-8"))
    assert registry["classes"]["leak_class"]["artifact_names"] == ["batch-a", "batch-b"]
    out = capsys.readouterr().out
    assert "2 artifact names (1 new)" in out


def test_check_reports_quarantined_and_clean(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "ledger"
    _write_json(
        ledger / "contaminations.json",
        {"version": 1, "classes": {"leak_class": {"artifact_names": ["batch-a"]}}},
    )
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    quarantine = _load_script("exp_quarantine")

    assert quarantine.main(["check", "/data/artifacts/batch-a"]) == 1
    assert "QUARANTINED\tbatch-a\tleak_class" in capsys.readouterr().out
    assert quarantine.main(["check", "batch-clean"]) == 0
    assert "clean\tbatch-clean" in capsys.readouterr().out


def test_register_rejects_bad_names_file(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "ledger"
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    quarantine = _load_script("exp_quarantine")
    names_file = tmp_path / "names.json"
    _write_json(names_file, {"not": "a list"})
    rc = quarantine.main(
        [
            "register",
            "--contamination-class",
            "leak_class",
            "--names-file",
            str(names_file),
            "--description",
            "leak",
        ]
    )
    assert rc == 2
    assert "must be a JSON list of strings" in capsys.readouterr().err


def test_list_summarizes_classes(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "ledger"
    _write_json(
        ledger / "contaminations.json",
        {
            "version": 1,
            "classes": {
                "leak_class": {
                    "artifact_names": ["batch-a", "batch-b"],
                    "boundary_commits": ["feedc0de"],
                    "description": "compaction marker leak",
                }
            },
        },
    )
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    quarantine = _load_script("exp_quarantine")
    assert quarantine.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "leak_class\truns=2\tboundary=feedc0de" in out
    assert "compaction marker leak" in out


# ---------------------------------------------------------------------------
# exp_status quarantined-baseline warning
# ---------------------------------------------------------------------------


def test_run_dir_contamination_classes_reads_stamp(tmp_path):
    common = _load_script("exp_common")
    _write_json(
        tmp_path / "runs" / "exp-dirty" / "contamination.json",
        {"classes": {"leak_class": {"matched_artifact_names": ["batch-a"]}}},
    )
    assert common.run_dir_contamination_classes(tmp_path, "exp-dirty") == ["leak_class"]
    assert common.run_dir_contamination_classes(tmp_path, "exp-clean") == []
    assert common.run_dir_contamination_classes(tmp_path, "") == []
    assert common.run_dir_contamination_classes(tmp_path, "../escape") == []


def test_status_warns_when_baseline_artifact_quarantined(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger"
    _write_json(
        ledger / "contaminations.json",
        {"version": 1, "classes": {"leak_class": {"artifact_names": ["batch-a"]}}},
    )
    _write_json(
        ledger / "runs" / "exp-glm-dirty" / "contamination.json",
        {"classes": {"leak_class": {"matched_artifact_names": ["batch-g"]}}},
    )
    _write_json(
        ledger / "baselines.json",
        {
            "qwen": {
                "current_best": {
                    "label": "qwen-base",
                    "artifact": "/data/artifacts/batch-a",
                    "resolved": 1,
                    "total": 10,
                }
            },
            "glm": {
                "current_best": {
                    "label": "glm-base",
                    "exp_id": "exp-glm-dirty",
                    "resolved": 2,
                    "total": 10,
                }
            },
        },
    )
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    _git_repo(source)
    _git_repo(handoff)
    status_mod = _load_script("exp_status")
    status = status_mod.collect_status(source, handoff)
    quarantine_warnings = sorted(
        item for item in status["warnings"] if "quarantined" in item
    )
    assert quarantine_warnings == [
        "glm baseline is quarantined (leak_class); re-baseline on clean runs",
        "qwen baseline is quarantined (leak_class); re-baseline on clean runs",
    ]


def test_status_no_quarantine_warning_for_clean_baselines(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger"
    _write_json(
        ledger / "contaminations.json",
        {"version": 1, "classes": {"leak_class": {"artifact_names": ["batch-a"]}}},
    )
    _write_json(
        ledger / "baselines.json",
        {
            "qwen": {
                "current_best": {
                    "label": "qwen-base",
                    "artifact": "/data/artifacts/batch-clean",
                    "exp_id": "exp-clean",
                    "resolved": 1,
                    "total": 10,
                }
            }
        },
    )
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    _git_repo(source)
    _git_repo(handoff)
    status_mod = _load_script("exp_status")
    status = status_mod.collect_status(source, handoff)
    assert not [item for item in status["warnings"] if "quarantined" in item]
