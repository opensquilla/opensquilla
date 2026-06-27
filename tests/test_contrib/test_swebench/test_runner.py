"""Unit tests for opensquilla.contrib.swebench.runner (no docker, no datasets)."""

import sys
import types

from opensquilla.contrib.swebench import runner


def test_resolve_dataset_name_aliases():
    assert runner.resolve_dataset_name("verified") == "princeton-nlp/SWE-bench_Verified"
    assert runner.resolve_dataset_name("Verified") == "princeton-nlp/SWE-bench_Verified"
    assert runner.resolve_dataset_name("multilingual") == "SWE-bench/SWE-bench_Multilingual"
    assert runner.resolve_dataset_name("org/Custom_DS") == "org/Custom_DS"


def test_default_run_id_shape():
    run_id = runner._default_run_id("django__django-16429")
    assert run_id.startswith("solve-django__django-16429-")


def _stub_dataset_module(monkeypatch, instances):
    mod = types.ModuleType("opensquilla.contrib.swebench.dataset")

    def load_instances(dataset_name, split="test", instance_ids=None, instance_file=None):
        return instances

    mod.load_instances = load_instances
    monkeypatch.setitem(sys.modules, "opensquilla.contrib.swebench.dataset", mod)


def test_solve_instance_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSQUILLA_SWEBENCH_ARTIFACTS_DIR", str(tmp_path))
    _stub_dataset_module(monkeypatch, [])
    result = runner.solve_instance("nope__nope-1", dataset="verified", pull=False)
    assert result["state"] == "failed"
    assert "not found" in result["error"]
    assert result["resolved"] is None


def test_eval_resolved_status_parses_report(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSQUILLA_SWEBENCH_ARTIFACTS_DIR", str(tmp_path))
    eval_dir = tmp_path / "eval" / "eval-run-1"
    eval_dir.mkdir(parents=True)
    (eval_dir / "model.eval-run-1.json").write_text(
        '{"resolved_ids": ["django__django-16429"], "unresolved_ids": []}'
    )
    assert runner._eval_resolved_status("eval-run-1", "django__django-16429") is True
    assert runner._eval_resolved_status("eval-run-1", "other__other-1") is False


def test_eval_resolved_status_missing_report(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSQUILLA_SWEBENCH_ARTIFACTS_DIR", str(tmp_path))
    assert runner._eval_resolved_status("no-such-run", "django__django-16429") is None
