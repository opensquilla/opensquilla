#!/usr/bin/env python3
"""Run an OpenSquilla experiment from an existing ledger manifest."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from exp_common import (
    LedgerError,
    append_jsonl,
    atomic_write_json,
    exp_dir,
    git_info,
    ledger_lock,
    ledger_root_from_env,
    now_iso,
    read_json,
    read_json_strict,
    sha256_file,
    validate_exp_id,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exp-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_experiment(args.exp_id)
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def run_experiment(exp_id: str) -> int:
    exp_id = validate_exp_id(exp_id)
    ledger_root = ledger_root_from_env()
    run_dir = exp_dir(ledger_root, exp_id)
    manifest_path = run_dir / "manifest.json"
    manifest = read_json_strict(manifest_path, label="experiment manifest")
    _verify_manifest_inputs(manifest)
    command_path = Path(manifest["execution"]["command_path"])
    if not command_path.is_file():
        raise LedgerError(f"missing command.sh: {command_path}")

    started_at = now_iso()
    with ledger_lock(ledger_root):
        atomic_write_json(
            run_dir / "live_status.json",
            {"status": "running", "started_at": started_at, "exp_id": exp_id},
        )
        current = read_json(ledger_root / "current.json")
        current.update(
            {
                "updated_at": started_at,
                "active_experiment": exp_id,
                "active_run_dir": str(run_dir),
            }
        )
        atomic_write_json(ledger_root / "current.json", current)
        append_jsonl(
            ledger_root / "experiments.jsonl",
            {"time": started_at, "exp_id": exp_id, "event": "started", "run_dir": str(run_dir)},
        )

    status = "finished"
    return_code = 0
    failure = ""
    try:
        proc = subprocess.run([str(command_path)], cwd=run_dir, check=False)
        return_code = proc.returncode
    except KeyboardInterrupt:
        status = "interrupted"
        return_code = 130
        failure = "keyboard_interrupt"
    except Exception as exc:  # pragma: no cover - defensive ledger cleanup path
        status = "failed"
        return_code = 2
        failure = str(exc)
    finally:
        _record_completion(
            ledger_root=ledger_root,
            run_dir=run_dir,
            exp_id=exp_id,
            started_at=started_at,
            status=status,
            return_code=return_code,
            failure=failure,
        )
    return return_code


def _record_completion(
    *,
    ledger_root: Path,
    run_dir: Path,
    exp_id: str,
    started_at: str,
    status: str,
    return_code: int,
    failure: str,
) -> None:
    finished_at = now_iso()
    payload: dict[str, Any] = {
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "return_code": return_code,
        "exp_id": exp_id,
    }
    if failure:
        payload["failure"] = failure
    with ledger_lock(ledger_root):
        atomic_write_json(run_dir / "live_status.json", payload)
        current = read_json(ledger_root / "current.json")
        if current.get("active_experiment") == exp_id:
            current["active_experiment"] = None
        current.update(
            {
                "updated_at": finished_at,
                "last_experiment": exp_id,
                "last_return_code": return_code,
                "last_status": status,
            }
        )
        atomic_write_json(ledger_root / "current.json", current)
        append_jsonl(
            ledger_root / "experiments.jsonl",
            {
                "time": finished_at,
                "exp_id": exp_id,
                "event": status,
                "return_code": return_code,
            },
        )


def _verify_manifest_inputs(manifest: dict[str, Any]) -> None:
    source = manifest.get("source", {})
    current_source = git_info(Path(source["path"]))
    if current_source.dirty_count:
        raise LedgerError("source repo is dirty; refusing to run experiment")
    if current_source.head != source.get("head"):
        raise LedgerError("source HEAD changed since manifest creation")
    for section in ("qwen_config", "glm_config"):
        payload = manifest.get("config", {}).get(section, {})
        _verify_payload_hash(section, payload)
    for section in ("ml", "verified"):
        payload = manifest.get("slice", {}).get(section, {})
        _verify_payload_hash(f"{section} instance file", payload)
    _verify_runner(manifest.get("config", {}).get("runner", {}))


def _verify_runner(runner: dict[str, Any]) -> None:
    expected = str(runner.get("sha256") or "")
    path_str = str(runner.get("path") or "")
    if not expected or not path_str:
        return
    path = Path(path_str)
    if not path.is_file():
        raise LedgerError(f"handoff runner missing: {path}")
    if sha256_file(path) != expected:
        raise LedgerError("handoff runner changed since manifest creation")


def _verify_payload_hash(label: str, payload: dict[str, Any]) -> None:
    expected = payload.get("sha256")
    if not expected:
        return
    checked = False
    for key in ("snapshot", "source"):
        path_str = str(payload.get(key) or "")
        if not path_str:
            continue
        path = Path(path_str)
        if path.is_file():
            checked = True
            if sha256_file(path) != expected:
                raise LedgerError(f"{label} {key} hash changed since manifest creation")
    if not checked:
        raise LedgerError(f"{label} source and snapshot are both missing")


if __name__ == "__main__":
    raise SystemExit(main())
