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


def _handoff_repo(path: Path) -> None:
    _git_repo(path)
    scripts = path / "scripts"
    scripts.mkdir()
    runner = scripts / "run_tool_policy_validation_stdin_keys.sh"
    runner.write_text("#!/usr/bin/env bash\necho runner\n", encoding="utf-8")
    runner.chmod(0o755)
    config = path / "config_runs"
    (config / "qwen").mkdir(parents=True)
    (config / "glm").mkdir(parents=True)
    (config / "qwen" / "config.toml").write_text("[llm]\nmodel='qwen'\n", encoding="utf-8")
    (config / "glm" / "config.toml").write_text("[llm]\nmodel='glm'\n", encoding="utf-8")
    cfg = path / "config"
    cfg.mkdir()
    (cfg / "ml.txt").write_text("a__b-1\n", encoding="utf-8")
    (cfg / "verified.txt").write_text("c__d-2\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "handoff",
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _init_args(source: Path, handoff: Path, exp_id: str = "qwen-ledger-smoke") -> list[str]:
    return [
        "--exp-id",
        exp_id,
        "--question",
        "does ledger work",
        "--condition-label",
        "ledger-smoke",
        "--run-mode",
        "qwen_only",
        "--source-root",
        str(source),
        "--handoff-root",
        str(handoff),
        "--qwen-config",
        str(handoff / "config_runs/qwen/config.toml"),
        "--glm-config",
        str(handoff / "config_runs/glm/config.toml"),
        "--ml-instance-file",
        str(handoff / "config/ml.txt"),
        "--verified-instance-file",
        str(handoff / "config/verified.txt"),
        "--ml-count",
        "1",
        "--verified-count",
        "1",
        "--qwen-workers",
        "10",
        "--glm-workers",
        "10",
        "--eval-workers",
        "10",
        "--env",
        "OPENSQUILLA_FINAL_DIFF_CONTRACT_MODE=warn_model",
    ]


def _write_fake_batch(
    batch: Path,
    manifest: dict,
    report: Path | None = None,
    *,
    overrides: dict[str, str] | None = None,
    infer_rc: int = 0,
    eval_rc: int = 0,
) -> None:
    batch.mkdir(parents=True)
    ml_ids = " ".join(
        line.strip()
        for line in Path(manifest["slice"]["ml"]["snapshot"]).read_text().splitlines()
        if line.strip()
    )
    verified_ids = " ".join(
        line.strip()
        for line in Path(manifest["slice"]["verified"]["snapshot"]).read_text().splitlines()
        if line.strip()
    )
    values = {
        "batch_id": f"{manifest['exp_id']}-batch",
        "opensquilla_source_head": manifest["source"]["head"],
        "handoff_head": manifest["handoff"]["head"],
        "condition_label": manifest["config"]["condition_label"],
        "run_mode": manifest["execution"]["run_mode"],
        "qwen_config_sha256": manifest["config"]["qwen_config"]["sha256"],
        "glm_config_sha256": manifest["config"]["glm_config"]["sha256"],
        "ml_instance_file": manifest["slice"]["ml"]["snapshot"],
        "ml_ids": ml_ids,
        "verified_instance_file": manifest["slice"]["verified"]["snapshot"],
        "verified_ids": verified_ids,
        "qwen_workers": str(manifest["execution"]["qwen_workers"]),
        "glm_workers": str(manifest["execution"]["glm_workers"]),
        "eval_workers": str(manifest["execution"]["eval_workers"]),
    }
    values.update(overrides or {})
    (batch / "manifest.txt").write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    if report is not None:
        (batch / "run-eval.report_paths.txt").write_text(str(report) + "\n", encoding="utf-8")
    (batch / "qwen.infer.exit_code").write_text(f"{infer_rc}\n", encoding="utf-8")
    (batch / "run-eval.exit_code").write_text(f"{eval_rc}\n", encoding="utf-8")


def _write_fake_instance_metadata(
    artifacts_root: Path,
    run_id: str,
    instance_id: str,
    env: dict[str, str],
) -> None:
    instance_dir = artifacts_root / run_id / instance_id
    instance_dir.mkdir(parents=True)
    (instance_dir / "metadata.json").write_text(
        json.dumps(
            {
                "agent": {
                    "controls": {
                        "progress_watchdog_env": env,
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_validate_exp_id_and_hash(tmp_path: Path) -> None:
    common = _load_script("exp_common")
    file = tmp_path / "x.txt"
    file.write_text("x\n", encoding="utf-8")

    assert common.validate_exp_id("abc-123.x_y") == "abc-123.x_y"
    assert common.sha256_file(file) == common.sha256_file(file)
    try:
        common.validate_exp_id("Bad ID")
    except common.LedgerError:
        pass
    else:
        raise AssertionError("invalid exp_id was accepted")


def test_init_writes_manifest_snapshots_and_redacts_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    init = _load_script("exp_init")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))

    rc = init.main(
        [
            *_init_args(source, handoff),
            "--env",
            "DASHSCOPE_API_KEY=secret-value",
        ]
    )

    assert rc == 0
    run_dir = ledger / "runs/qwen-ledger-smoke"
    manifest = json.loads((run_dir / "manifest.json").read_text())
    command = (run_dir / "command.sh").read_text()
    assert manifest["source"]["dirty_count"] == 0
    assert manifest["config"]["env"]["DASHSCOPE_API_KEY"]["redacted"] is True
    assert "secret-value" not in command
    assert (run_dir / "config_snapshot/qwen/config.toml").is_file()
    assert (run_dir / "instance_snapshot/ml/ml.txt").is_file()
    assert f"QWEN_CONFIG_DIR='{run_dir}/config_snapshot/qwen'" in command
    assert f"ML_INSTANCE_FILE='{run_dir}/instance_snapshot/ml/ml.txt'" in command
    assert (ledger / "experiments.jsonl").read_text().strip()


def test_init_rejects_dirty_source_and_config_directory(tmp_path: Path, monkeypatch) -> None:
    init = _load_script("exp_init")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    _git_repo(source)
    _handoff_repo(handoff)
    (source / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))

    assert init.main(_init_args(source, handoff, "dirty-source")) == 2
    subprocess.run(["git", "add", "dirty.txt"], cwd=source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "clean",
        ],
        cwd=source,
        check=True,
        capture_output=True,
    )
    args = _init_args(source, handoff, "bad-config")
    qwen_index = args.index("--qwen-config") + 1
    args[qwen_index] = str(handoff / "config_runs/qwen")
    assert init.main(args) == 2


def test_init_dry_run_does_not_create_run_dir(tmp_path: Path, monkeypatch) -> None:
    init = _load_script("exp_init")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))

    rc = init.main([*_init_args(source, handoff, "dry-run-exp"), "--dry-run"])

    assert rc == 0
    assert not (ledger / "runs/dry-run-exp").exists()


def test_status_reports_baseline_and_stale_active(tmp_path: Path, monkeypatch, capsys) -> None:
    status = _load_script("exp_status")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    _git_repo(source)
    _handoff_repo(handoff)
    ledger.mkdir(parents=True)
    (ledger / "current.json").write_text(
        json.dumps({"active_experiment": "missing-exp", "warnings": ["known warning"]}),
        encoding="utf-8",
    )
    (ledger / "baselines.json").write_text(
        json.dumps(
            {
                "qwen": {
                    "current_best": {
                        "label": "repo-coding",
                        "resolved": 4,
                        "total": 10,
                        "empty": 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))

    rc = status.main(["--source-root", str(source), "--handoff-root", str(handoff)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "Qwen baseline: repo-coding = 4/10 empty=0" in out
    assert "active experiment manifest missing" in out
    # An active experiment with no live processes/containers must warn about stale state.
    assert "stale active state" in out


def test_run_records_failure_and_clears_active(tmp_path: Path, monkeypatch) -> None:
    init = _load_script("exp_init")
    run = _load_script("exp_run")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    assert init.main(_init_args(source, handoff, "run-fails")) == 0
    command = ledger / "runs/run-fails/command.sh"
    command.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="utf-8")
    command.chmod(0o755)

    assert run.main(["--exp-id", "run-fails"]) == 7

    live_status = json.loads((ledger / "runs/run-fails/live_status.json").read_text())
    current = json.loads((ledger / "current.json").read_text())
    assert live_status["status"] == "finished"
    assert live_status["return_code"] == 7
    assert current["active_experiment"] is None
    assert current["last_return_code"] == 7


def test_run_rejects_changed_snapshot_hash(tmp_path: Path, monkeypatch) -> None:
    init = _load_script("exp_init")
    run = _load_script("exp_run")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    assert init.main(_init_args(source, handoff, "bad-snapshot")) == 0
    snapshot = ledger / "runs/bad-snapshot/config_snapshot/qwen/config.toml"
    snapshot.write_text("[llm]\nmodel='changed'\n", encoding="utf-8")

    assert run.main(["--exp-id", "bad-snapshot"]) == 2


def test_finalize_writes_metrics_and_updates_baseline(tmp_path: Path, monkeypatch) -> None:
    init = _load_script("exp_init")
    finalize = _load_script("exp_finalize")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    batch = tmp_path / "batch"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    assert init.main(_init_args(source, handoff, "finalize-smoke")) == 0
    run_dir = ledger / "runs/finalize-smoke"
    manifest = json.loads((run_dir / "manifest.json").read_text())

    report = tmp_path / "eval.json"
    report.write_text(
        json.dumps(
            {
                "total_instances": 2,
                "submitted_instances": 2,
                "completed_instances": 2,
                "resolved_instances": 1,
                "unresolved_instances": 1,
                "empty_patch_instances": 0,
                "error_instances": 0,
                "resolved_ids": ["a__b-1"],
            }
        ),
        encoding="utf-8",
    )
    _write_fake_batch(
        batch,
        manifest,
        report,
        overrides={"qwen_ml_run_id": "qwen-run", "qwen_verified_run_id": "qwen-verified-run"},
    )
    _write_fake_instance_metadata(
        batch.parent,
        "qwen-run",
        "a__b-1",
        {"OPENSQUILLA_FINAL_DIFF_CONTRACT_MODE": "warn_model"},
    )
    _write_fake_instance_metadata(
        batch.parent,
        "qwen-verified-run",
        "c__d-2",
        {"OPENSQUILLA_FINAL_DIFF_CONTRACT_MODE": "warn_model"},
    )

    rc = finalize.main(
        [
            "--exp-id",
            "finalize-smoke",
            "--batch-dir",
            str(batch),
            "--decision",
            "adopted",
            "--decision-reason",
            "test baseline",
            "--baseline-model",
            "qwen",
            "--mechanism",
            "repo_coding_qwen",
        ]
    )

    assert rc == 0
    metrics = json.loads((run_dir / "metrics.json").read_text())
    baselines = json.loads((ledger / "baselines.json").read_text())
    mechanisms = json.loads((ledger / "mechanisms.json").read_text())
    assert metrics["resolved_instances"] == 1
    assert baselines["qwen"]["current_best"]["resolved"] == 1
    assert mechanisms["repo_coding_qwen"]["status"] == "adopted"


def test_finalize_rejects_mismatched_batch(tmp_path: Path, monkeypatch) -> None:
    init = _load_script("exp_init")
    finalize = _load_script("exp_finalize")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    batch = tmp_path / "batch"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    assert init.main(_init_args(source, handoff, "mismatch")) == 0
    manifest = json.loads((ledger / "runs/mismatch/manifest.json").read_text())
    report = tmp_path / "eval.json"
    report.write_text(
        json.dumps({"total_instances": 1, "resolved_instances": 1}),
        encoding="utf-8",
    )
    _write_fake_batch(batch, manifest, report, overrides={"condition_label": "wrong"})

    assert (
        finalize.main(
            [
                "--exp-id",
                "mismatch",
                "--batch-dir",
                str(batch),
                "--decision",
                "adopted",
                "--decision-reason",
                "must fail",
                "--baseline-model",
                "qwen",
            ]
        )
        == 2
    )


def test_finalize_rejects_missing_manifest_env_delivery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    init = _load_script("exp_init")
    finalize = _load_script("exp_finalize")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    batch = tmp_path / "artifacts" / "batch"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    assert (
        init.main(
            [
                *_init_args(source, handoff, "missing-env-delivery"),
                "--env",
                "OPENSQUILLA_FINALIZE_EVIDENCE_GATE=on",
            ]
        )
        == 0
    )
    manifest = json.loads((ledger / "runs/missing-env-delivery/manifest.json").read_text())
    report = tmp_path / "eval.json"
    report.write_text(
        json.dumps({"total_instances": 1, "resolved_instances": 1}),
        encoding="utf-8",
    )
    run_id = "qwen-run"
    _write_fake_batch(
        batch,
        manifest,
        report,
        overrides={"qwen_ml_run_id": run_id, "ml_ids": "a__b-1"},
    )
    _write_fake_instance_metadata(
        batch.parent,
        run_id,
        "a__b-1",
        {"OPENSQUILLA_FINAL_DIFF_CONTRACT_MODE": "warn_model"},
    )

    assert (
        finalize.main(
            [
                "--exp-id",
                "missing-env-delivery",
                "--batch-dir",
                str(batch),
                "--decision",
                "rejected",
                "--decision-reason",
                "must fail because treatment env was not delivered",
            ]
        )
        == 2
    )
    assert (
        finalize.main(
            [
                "--exp-id",
                "missing-env-delivery",
                "--batch-dir",
                str(batch),
                "--decision",
                "invalid",
                "--decision-reason",
                "missing runtime env delivery",
            ]
        )
        == 0
    )


def test_finalize_rejects_env_delivery_with_no_resolvable_run_dirs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A pinned env var that can never be checked (no run dirs) must block, not pass."""
    init = _load_script("exp_init")
    finalize = _load_script("exp_finalize")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    batch = tmp_path / "batch"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    assert init.main(_init_args(source, handoff, "no-run-dirs")) == 0
    manifest = json.loads((ledger / "runs/no-run-dirs/manifest.json").read_text())
    report = tmp_path / "eval.json"
    report.write_text(
        json.dumps({"total_instances": 1, "resolved_instances": 1}),
        encoding="utf-8",
    )
    # No qwen_ml_run_id/qwen_verified_run_id override: _agent_run_dirs cannot
    # resolve any run directory, so env delivery can never be verified.
    _write_fake_batch(batch, manifest, report)

    assert (
        finalize.main(
            [
                "--exp-id",
                "no-run-dirs",
                "--batch-dir",
                str(batch),
                "--decision",
                "rejected",
                "--decision-reason",
                "must fail because run dirs could not be resolved",
            ]
        )
        == 2
    )
    assert (
        finalize.main(
            [
                "--exp-id",
                "no-run-dirs",
                "--batch-dir",
                str(batch),
                "--decision",
                "invalid",
                "--decision-reason",
                "no resolvable run dirs",
            ]
        )
        == 0
    )


def test_finalize_rejects_adopting_quarantined_batch_as_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    init = _load_script("exp_init")
    finalize = _load_script("exp_finalize")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    batch = tmp_path / "quarantined-batch"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    ledger.mkdir(parents=True)
    (ledger / "contaminations.json").write_text(
        json.dumps(
            {
                "version": 1,
                "classes": {
                    "leak_class": {"artifact_names": ["quarantined-batch"]}
                },
            }
        ),
        encoding="utf-8",
    )
    assert init.main(_init_args(source, handoff, "quarantined-adopt")) == 0
    manifest = json.loads((ledger / "runs/quarantined-adopt/manifest.json").read_text())
    report = tmp_path / "eval.json"
    report.write_text(
        json.dumps({"total_instances": 1, "resolved_instances": 1}),
        encoding="utf-8",
    )
    _write_fake_batch(
        batch,
        manifest,
        report,
        overrides={"qwen_ml_run_id": "qwen-run", "qwen_verified_run_id": "qwen-verified-run"},
    )
    _write_fake_instance_metadata(
        batch.parent,
        "qwen-run",
        "a__b-1",
        {"OPENSQUILLA_FINAL_DIFF_CONTRACT_MODE": "warn_model"},
    )
    _write_fake_instance_metadata(
        batch.parent,
        "qwen-verified-run",
        "c__d-2",
        {"OPENSQUILLA_FINAL_DIFF_CONTRACT_MODE": "warn_model"},
    )

    rc = finalize.main(
        [
            "--exp-id",
            "quarantined-adopt",
            "--batch-dir",
            str(batch),
            "--decision",
            "adopted",
            "--decision-reason",
            "must fail because batch is quarantined",
            "--baseline-model",
            "qwen",
        ]
    )
    assert rc == 2
    assert not (ledger / "baselines.json").exists()


def test_finalize_requires_invalid_or_stopped_for_nonzero_infer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    init = _load_script("exp_init")
    finalize = _load_script("exp_finalize")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    batch = tmp_path / "batch"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    assert init.main(_init_args(source, handoff, "nonzero-infer")) == 0
    manifest = json.loads((ledger / "runs/nonzero-infer/manifest.json").read_text())
    report = tmp_path / "eval.json"
    report.write_text(
        json.dumps({"total_instances": 1, "resolved_instances": 1}),
        encoding="utf-8",
    )
    _write_fake_batch(batch, manifest, report, infer_rc=1)

    assert (
        finalize.main(
            [
                "--exp-id",
                "nonzero-infer",
                "--batch-dir",
                str(batch),
                "--decision",
                "rejected",
                "--decision-reason",
                "infer failed",
            ]
        )
        == 2
    )
    assert (
        finalize.main(
            [
                "--exp-id",
                "nonzero-infer",
                "--batch-dir",
                str(batch),
                "--decision",
                "invalid",
                "--decision-reason",
                "infer failed",
            ]
        )
        == 0
    )


def test_finalize_flags_nonzero_nonstandard_exit_code(tmp_path: Path, monkeypatch) -> None:
    init = _load_script("exp_init")
    finalize = _load_script("exp_finalize")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    batch = tmp_path / "batch"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    assert init.main(_init_args(source, handoff, "nonstd-exit")) == 0
    manifest = json.loads((ledger / "runs/nonstd-exit/manifest.json").read_text())
    report = tmp_path / "eval.json"
    report.write_text(
        json.dumps({"total_instances": 1, "resolved_instances": 1}),
        encoding="utf-8",
    )
    _write_fake_batch(batch, manifest, report)
    # A nonzero exit file whose name matches neither the eval nor infer pattern must
    # still block a scored decision (regression guard for the silent-ignore hole).
    (batch / "containers.exit_code").write_text("3\n", encoding="utf-8")

    assert (
        finalize.main(
            [
                "--exp-id",
                "nonstd-exit",
                "--batch-dir",
                str(batch),
                "--decision",
                "adopted",
                "--decision-reason",
                "should be blocked",
                "--baseline-model",
                "qwen",
            ]
        )
        == 2
    )
    assert (
        finalize.main(
            [
                "--exp-id",
                "nonstd-exit",
                "--batch-dir",
                str(batch),
                "--decision",
                "invalid",
                "--decision-reason",
                "nonzero container exit",
            ]
        )
        == 0
    )
    metrics = json.loads((ledger / "runs/nonstd-exit/metrics.json").read_text())
    assert metrics["nonzero_other_exit_codes"] == {"containers.exit_code": 3}


def test_finalize_rejects_changed_instance_content(tmp_path: Path, monkeypatch) -> None:
    init = _load_script("exp_init")
    finalize = _load_script("exp_finalize")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    batch = tmp_path / "batch"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    assert init.main(_init_args(source, handoff, "changed-instances")) == 0
    manifest = json.loads((ledger / "runs/changed-instances/manifest.json").read_text())
    report = tmp_path / "eval.json"
    report.write_text(
        json.dumps({"total_instances": 1, "resolved_instances": 1}),
        encoding="utf-8",
    )
    _write_fake_batch(batch, manifest, report)
    # Tamper with the instance snapshot the batch references: path still matches the
    # manifest, but content (and slice size) no longer do -> must be rejected.
    snapshot = Path(manifest["slice"]["ml"]["snapshot"])
    snapshot.write_text("a__b-1\nx__y-9\n", encoding="utf-8")

    assert (
        finalize.main(
            [
                "--exp-id",
                "changed-instances",
                "--batch-dir",
                str(batch),
                "--decision",
                "adopted",
                "--decision-reason",
                "content drifted",
                "--baseline-model",
                "qwen",
            ]
        )
        == 2
    )


def test_verify_slice_content_flags_count_mismatch(tmp_path: Path) -> None:
    finalize = _load_script("exp_finalize")
    instance_file = tmp_path / "ml.txt"
    instance_file.write_text("a__b-1\nc__d-2\n", encoding="utf-8")
    payload = {
        "source": str(instance_file),
        "sha256": "",  # skip sha check, isolate the count check
        "count": 5,
    }
    errors: list[str] = []
    finalize._verify_slice_content(errors, "ml_instance_file", str(instance_file), payload)
    assert any("instance count 2 != manifest 5" in item for item in errors)


def test_verify_slice_content_flags_superset_count_mismatch(tmp_path: Path) -> None:
    finalize = _load_script("exp_finalize")
    instance_file = tmp_path / "ml.txt"
    instance_file.write_text("a__b-1\nc__d-2\nc__d-3\n", encoding="utf-8")
    payload = {
        "source": str(instance_file),
        "sha256": "",  # skip sha check, isolate the count check
        "count": 2,
    }
    errors: list[str] = []
    finalize._verify_slice_content(errors, "ml_instance_file", str(instance_file), payload)
    assert any("instance count 3 != manifest 2" in item for item in errors)


def test_verify_slice_content_allows_zero_count_snapshot_file(tmp_path: Path) -> None:
    finalize = _load_script("exp_finalize")
    instance_file = tmp_path / "verified.txt"
    instance_file.write_text("a__b-1\nc__d-2\n", encoding="utf-8")
    payload = {
        "source": str(instance_file),
        "sha256": "",  # skip sha check, isolate zero-count behavior
        "count": 0,
    }
    errors: list[str] = []
    finalize._verify_slice_content(
        errors,
        "verified_instance_file",
        str(instance_file),
        payload,
    )
    assert errors == []


def test_agent_run_dirs_empty_batch_dir_returns_no_dirs() -> None:
    finalize = _load_script("exp_finalize")
    artifacts = {
        "batch_dir": "",
        "batch_manifest": {
            "run_mode": "qwen_only",
            "ml_ids": "a__b-1",
            "qwen_ml_run_id": "qwen-run",
        },
    }
    assert finalize._agent_run_dirs(artifacts) == []


def test_run_rejects_changed_runner(tmp_path: Path, monkeypatch) -> None:
    init = _load_script("exp_init")
    run = _load_script("exp_run")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    assert init.main(_init_args(source, handoff, "changed-runner")) == 0
    runner = handoff / "scripts/run_tool_policy_validation_stdin_keys.sh"
    runner.write_text("#!/usr/bin/env bash\necho tampered\n", encoding="utf-8")

    assert run.main(["--exp-id", "changed-runner"]) == 2


def test_finalize_requires_invalid_or_stopped_without_eval(tmp_path: Path, monkeypatch) -> None:
    init = _load_script("exp_init")
    finalize = _load_script("exp_finalize")
    ledger = tmp_path / "ledger"
    source = tmp_path / "source"
    handoff = tmp_path / "handoff"
    batch = tmp_path / "batch"
    _git_repo(source)
    _handoff_repo(handoff)
    monkeypatch.setenv("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", str(ledger))
    assert init.main(_init_args(source, handoff, "missing-eval")) == 0
    manifest = json.loads((ledger / "runs/missing-eval/manifest.json").read_text())
    _write_fake_batch(batch, manifest, None)

    assert (
        finalize.main(
            [
                "--exp-id",
                "missing-eval",
                "--batch-dir",
                str(batch),
                "--decision",
                "rejected",
                "--decision-reason",
                "bad",
            ]
        )
        == 2
    )
    assert (
        finalize.main(
            [
                "--exp-id",
                "missing-eval",
                "--batch-dir",
                str(batch),
                "--decision",
                "stopped",
                "--decision-reason",
                "interrupted",
            ]
        )
        == 0
    )
