#!/usr/bin/env python3
"""Shared helpers for the OpenSquilla experiment ledger."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_LEDGER_ROOT = Path("./.experiments-ledger")
RUNNER_RELATIVE_PATH = Path("scripts/run_tool_policy_validation_stdin_keys.sh")

# Docker needles for run supervision; overridable per run via the top-level
# manifest keys ``container_name_prefix`` and ``eval_image_needle``.
CONTAINER_NAME_PREFIX = "opensquilla-swe-"
EVAL_IMAGE_NEEDLE = "sweb.eval."

# Default provider secret env var required per model family; overridable via
# the ``--required-secret-env`` CLI flag on exp_init.
DEFAULT_REQUIRED_SECRET_ENV = {
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "OPENROUTER_API_KEY",
}

EXP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|credential)", re.I)
TRACKED_ENV_PREFIXES = ("OPENSQUILLA_",)


class LedgerError(RuntimeError):
    """Raised for user-correctable ledger command failures."""


@dataclass(frozen=True)
class GitInfo:
    path: str
    branch: str
    head: str
    short_head: str
    dirty_count: int
    dirty_summary: list[str]


def now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def ledger_root_from_env() -> Path:
    return Path(
        os.environ.get(
            "OPENSQUILLA_EXPERIMENT_LEDGER_ROOT",
            os.environ.get("OPENSQUILLA_SWE_EXPERIMENT_LEDGER_ROOT", DEFAULT_LEDGER_ROOT),
        )
    )


def validate_exp_id(exp_id: str) -> str:
    if not EXP_ID_RE.fullmatch(exp_id):
        raise LedgerError("exp_id must match [a-z0-9][a-z0-9._-]*")
    return exp_id


def ensure_ledger_layout(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def ledger_lock(root: Path) -> Iterator[None]:
    ensure_ledger_layout(root)
    lock_path = root / ".lock"
    with lock_path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return {} if default is None else dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if default is None else dict(default)
    return data if isinstance(data, dict) else ({} if default is None else dict(default))


def read_json_strict(path: Path, *, label: str = "JSON file") -> dict[str, Any]:
    if not path.exists():
        raise LedgerError(f"missing {label}: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise LedgerError(f"{label} must contain a JSON object: {path}")
    return data


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


def git_info(path: Path, *, max_dirty_lines: int = 20) -> GitInfo:
    if not path.exists():
        raise LedgerError(f"path does not exist: {path}")
    head = _git_stdout(path, ["rev-parse", "HEAD"])
    short_head = _git_stdout(path, ["rev-parse", "--short", "HEAD"])
    branch_proc = run_command(["git", "branch", "--show-current"], cwd=path)
    branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""
    dirty_proc = run_command(["git", "status", "--short"], cwd=path)
    if dirty_proc.returncode != 0:
        raise LedgerError(f"git status failed for {path}: {dirty_proc.stderr.strip()}")
    dirty_lines = [line for line in dirty_proc.stdout.splitlines() if line.strip()]
    return GitInfo(
        path=str(path),
        branch=branch,
        head=head,
        short_head=short_head,
        dirty_count=len(dirty_lines),
        dirty_summary=dirty_lines[:max_dirty_lines],
    )


def _git_stdout(path: Path, args: list[str]) -> str:
    proc = run_command(["git", *args], cwd=path)
    if proc.returncode != 0:
        raise LedgerError(f"git {' '.join(args)} failed for {path}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def copy_snapshot(src: Path, dst_dir: Path) -> dict[str, str]:
    if not src.is_file():
        raise LedgerError(f"snapshot source must be a file: {src}")
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    shutil.copy2(src, dst)
    return {"source": str(src), "snapshot": str(dst), "sha256": sha256_file(src)}


def parse_key_value_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def parse_env_overrides(items: list[str]) -> dict[str, dict[str, Any]]:
    parsed: dict[str, dict[str, Any]] = {}
    for item in items:
        if "=" not in item:
            raise LedgerError(f"--env must use KEY=VALUE form: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise LedgerError("--env key cannot be empty")
        parsed[key] = redact_env_value(key, value)
    return parsed


def redact_env_value(key: str, value: str | None = None) -> dict[str, Any]:
    if SECRET_KEY_RE.search(key):
        return {"required": True, "provided_at_init": bool(value), "redacted": True}
    if key.startswith(TRACKED_ENV_PREFIXES):
        return {"value": value or "", "redacted": False}
    return {"value": value or "", "redacted": False}


def env_exports_for_command(env: dict[str, dict[str, Any]]) -> list[str]:
    exports: list[str] = []
    for key, meta in sorted(env.items()):
        if meta.get("redacted"):
            continue
        value = str(meta.get("value", ""))
        exports.append(f"export {key}={sh_quote(value)}")
    return exports


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def required_secret_env(
    run_mode: str, mapping: dict[str, str] | None = None
) -> dict[str, dict[str, Any]]:
    if mapping is None:
        mapping = DEFAULT_REQUIRED_SECRET_ENV
    required: dict[str, dict[str, Any]] = {}
    if run_mode != "glm_only":
        key = mapping["qwen"]
        required[key] = redact_env_value(key)
    if run_mode != "qwen_only":
        key = mapping["glm"]
        required[key] = redact_env_value(key)
    return required


def read_first_existing_report(paths_file: Path) -> list[str]:
    if not paths_file.exists():
        return []
    reports = []
    for line in paths_file.read_text(encoding="utf-8", errors="replace").splitlines():
        candidate = line.strip()
        if candidate and Path(candidate).is_file():
            reports.append(candidate)
    return reports


def collect_eval_metrics(report_paths: list[str]) -> dict[str, Any]:
    totals = {
        "total_instances": 0,
        "submitted_instances": 0,
        "completed_instances": 0,
        "resolved_instances": 0,
        "unresolved_instances": 0,
        "empty_patch_instances": 0,
        "error_instances": 0,
    }
    resolved_ids: list[str] = []
    empty_patch_ids: list[str] = []
    error_ids: list[str] = []
    reports: list[dict[str, Any]] = []
    for path_str in report_paths:
        path = Path(path_str)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for key in totals:
            value = data.get(key)
            if isinstance(value, int):
                totals[key] += value
        resolved_ids.extend(_string_list(data.get("resolved_ids")))
        empty_patch_ids.extend(_string_list(data.get("empty_patch_ids")))
        error_ids.extend(_string_list(data.get("error_ids")))
        reports.append({"path": str(path), "schema_version": data.get("schema_version", "")})
    return {
        **totals,
        "resolved_ids": sorted(set(resolved_ids)),
        "empty_patch_ids": sorted(set(empty_patch_ids)),
        "error_ids": sorted(set(error_ids)),
        "report_count": len(reports),
        "reports": reports,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def active_processes() -> list[dict[str, Any]]:
    proc = run_command(["ps", "-eo", "pid=,args="])
    if proc.returncode != 0:
        return []
    needles = (
        "run_tool_policy_validation",
        "run_infer.py",
        "run_eval.py",
        "swebench.harness.run_evaluation",
    )
    rows = []
    self_pid = os.getpid()
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, args = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == self_pid:
            continue
        if any(needle in args for needle in needles):
            rows.append({"pid": pid, "args": args[:500]})
    return rows


def active_swe_containers(manifest: dict[str, Any] | None = None) -> list[str]:
    config = manifest if isinstance(manifest, dict) else {}
    container_prefix = str(config.get("container_name_prefix") or CONTAINER_NAME_PREFIX)
    eval_image_needle = str(config.get("eval_image_needle") or EVAL_IMAGE_NEEDLE)
    proc = run_command(["docker", "ps", "--format", "{{.Names}}"])
    if proc.returncode != 0:
        return []
    return [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.startswith(container_prefix) or line.startswith(eval_image_needle)
    ]


def status_label_from_dirty(info: GitInfo) -> str:
    return "clean" if info.dirty_count == 0 else f"dirty {info.dirty_count}"


def exp_dir(root: Path, exp_id: str) -> Path:
    return root / "runs" / validate_exp_id(exp_id)


# ---------------------------------------------------------------------------
# Contamination registry (quarantined runs)
# ---------------------------------------------------------------------------
#
# ``contaminations.json`` at the ledger root maps a contamination class (e.g.
# ``tool_result_compaction_defect``) to the artifact batch names whose
# results are confounded by an infra defect. Baseline and A/B tooling must
# exclude quarantined artifacts; ``exp_status`` warns when a recorded
# baseline references one.

CONTAMINATIONS_FILENAME = "contaminations.json"


def contaminations_path(root: Path) -> Path:
    return root / CONTAMINATIONS_FILENAME


def load_contaminations(root: Path) -> dict[str, Any]:
    data = read_json(contaminations_path(root), default={})
    classes = data.get("classes")
    if not isinstance(classes, dict):
        data["classes"] = {}
    data.setdefault("version", 1)
    return data


def artifact_basename(artifact: str | Path) -> str:
    """Normalize an artifact path or batch name to its bare batch name."""
    return str(artifact).rstrip("/").rsplit("/", 1)[-1]


def contamination_class_for(
    root: Path,
    artifact: str | Path,
    contaminations: dict[str, Any] | None = None,
) -> str | None:
    """Return the contamination class covering ``artifact``, or None if clean."""
    name = artifact_basename(artifact)
    if not name:
        return None
    data = contaminations if contaminations is not None else load_contaminations(root)
    classes = data.get("classes")
    if not isinstance(classes, dict):
        return None
    for class_name, payload in sorted(classes.items()):
        if not isinstance(payload, dict):
            continue
        names = payload.get("artifact_names")
        if isinstance(names, list) and name in names:
            return class_name
    return None


def run_dir_contamination_classes(root: Path, exp_id: str) -> list[str]:
    """Return contamination classes stamped on a ledger run dir (empty if clean)."""
    if not exp_id or not EXP_ID_RE.fullmatch(exp_id):
        return []
    stamp = read_json(root / "runs" / exp_id / "contamination.json")
    classes = stamp.get("classes")
    if not isinstance(classes, dict):
        return []
    return sorted(name for name in classes if isinstance(name, str))
