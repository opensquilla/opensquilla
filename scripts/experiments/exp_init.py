#!/usr/bin/env python3
"""Create a reproducible OpenSquilla experiment manifest."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Any

from exp_common import (
    DEFAULT_REQUIRED_SECRET_ENV,
    RUNNER_RELATIVE_PATH,
    LedgerError,
    append_jsonl,
    atomic_write_json,
    atomic_write_text,
    copy_snapshot,
    env_exports_for_command,
    exp_dir,
    git_info,
    ledger_lock,
    ledger_root_from_env,
    now_iso,
    parse_env_overrides,
    required_secret_env,
    sh_quote,
    sha256_file,
    validate_exp_id,
)

RUN_MODES = {"qwen_only", "glm_only", "both"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exp-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--hypothesis", default="")
    parser.add_argument("--condition-label", required=True)
    parser.add_argument("--run-mode", required=True, choices=sorted(RUN_MODES))
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--handoff-root", type=Path, required=True)
    parser.add_argument("--qwen-config", type=Path, required=True)
    parser.add_argument("--glm-config", type=Path, required=True)
    parser.add_argument("--ml-instance-file", type=Path, required=True)
    parser.add_argument("--verified-instance-file", type=Path, required=True)
    parser.add_argument("--ml-count", type=int, required=True)
    parser.add_argument("--verified-count", type=int, required=True)
    parser.add_argument("--qwen-workers", type=int, required=True)
    parser.add_argument("--glm-workers", type=int, required=True)
    parser.add_argument("--eval-workers", type=int, required=True)
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument(
        "--required-secret-env",
        action="append",
        default=[],
        metavar="MODEL=ENV_VAR",
        help="Override the required provider secret env var for a model (qwen=..., glm=...).",
    )
    parser.add_argument("--decision-gate", action="append", default=[])
    parser.add_argument("--allow-handoff-dirty", action="store_true")
    parser.add_argument("--resume-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        create_experiment(args)
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def create_experiment(args: argparse.Namespace) -> None:
    exp_id = validate_exp_id(args.exp_id)
    ledger_root = ledger_root_from_env()
    run_dir = exp_dir(ledger_root, exp_id)
    with ledger_lock(ledger_root):
        if run_dir.exists() and not args.resume_existing and not args.dry_run:
            raise LedgerError(f"experiment already exists: {run_dir}")

        source = git_info(args.source_root)
        handoff = git_info(args.handoff_root)
        if source.dirty_count:
            raise LedgerError("source repo is dirty; refusing to create experiment manifest")
        if handoff.dirty_count and not args.allow_handoff_dirty:
            raise LedgerError("handoff repo is dirty; pass --allow-handoff-dirty to record it")

        qwen_config = _require_config_file(args.qwen_config, "qwen")
        glm_config = _require_config_file(args.glm_config, "glm")
        ml_file = _require_file(args.ml_instance_file, "ml instance file")
        verified_file = _require_file(args.verified_instance_file, "verified instance file")
        runner = args.handoff_root / RUNNER_RELATIVE_PATH
        _require_file(runner, "handoff runner")

        config_snapshot_dir = run_dir / "config_snapshot"
        instance_snapshot_dir = run_dir / "instance_snapshot"
        if args.dry_run:
            qwen_snapshot = _snapshot_preview(qwen_config)
            glm_snapshot = _snapshot_preview(glm_config)
            ml_snapshot = _snapshot_preview(ml_file)
            verified_snapshot = _snapshot_preview(verified_file)
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            qwen_snapshot = copy_snapshot(qwen_config, config_snapshot_dir / "qwen")
            glm_snapshot = copy_snapshot(glm_config, config_snapshot_dir / "glm")
            ml_snapshot = copy_snapshot(ml_file, instance_snapshot_dir / "ml")
            verified_snapshot = copy_snapshot(verified_file, instance_snapshot_dir / "verified")

        env = required_secret_env(
            args.run_mode, _required_secret_env_overrides(args.required_secret_env)
        )
        env.update(parse_env_overrides(args.env))
        created_at = now_iso()
        manifest = {
            "exp_id": exp_id,
            "status": "planned",
            "question": args.question,
            "hypothesis": args.hypothesis,
            "source": source.__dict__,
            "handoff": {
                **handoff.__dict__,
                "dirty_allowed": bool(args.allow_handoff_dirty),
            },
            "model": _model_metadata(args.run_mode, env),
            "config": {
                "condition_label": args.condition_label,
                "qwen_config": qwen_snapshot,
                "glm_config": glm_snapshot,
                "runner": {"path": str(runner), "sha256": sha256_file(runner)},
                "env": env,
            },
            "slice": {
                "ml": {**ml_snapshot, "count": args.ml_count},
                "verified": {**verified_snapshot, "count": args.verified_count},
            },
            "execution": {
                "run_mode": args.run_mode,
                "qwen_workers": args.qwen_workers,
                "glm_workers": args.glm_workers,
                "eval_workers": args.eval_workers,
                "command_path": str(run_dir / "command.sh"),
            },
            "artifacts": {},
            "decision_gate": {"items": args.decision_gate},
            "created_at": created_at,
            "evidence_level": "manifested",
        }

        command = render_command(args, manifest)
        if not args.dry_run:
            atomic_write_json(run_dir / "manifest.json", manifest)
            atomic_write_text(run_dir / "command.sh", command)
            _make_executable(run_dir / "command.sh")
            atomic_write_json(
                run_dir / "preflight.json",
                {
                    "created_at": created_at,
                    "source_dirty_count": source.dirty_count,
                    "handoff_dirty_count": handoff.dirty_count,
                    "config_hashes": {
                        "qwen": qwen_snapshot["sha256"],
                        "glm": glm_snapshot["sha256"],
                    },
                },
            )
            append_jsonl(
                ledger_root / "experiments.jsonl",
                {
                    "time": created_at,
                    "exp_id": exp_id,
                    "event": "created",
                    "run_dir": str(run_dir),
                    "condition_label": args.condition_label,
                },
            )
        print(json.dumps({"exp_id": exp_id, "run_dir": str(run_dir)}, indent=2))


def _required_secret_env_overrides(items: list[str]) -> dict[str, str]:
    mapping = dict(DEFAULT_REQUIRED_SECRET_ENV)
    for item in items:
        model, sep, name = item.partition("=")
        model = model.strip()
        name = name.strip()
        if not sep or model not in DEFAULT_REQUIRED_SECRET_ENV or not name:
            raise LedgerError(
                "--required-secret-env must use MODEL=ENV_VAR with MODEL in "
                + "/".join(sorted(DEFAULT_REQUIRED_SECRET_ENV))
            )
        mapping[model] = name
    return mapping


def _require_config_file(path: Path, label: str) -> Path:
    if path.is_dir():
        raise LedgerError(f"{label} config must be a config.toml file, got directory: {path}")
    return _require_file(path, f"{label} config")


def _require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise LedgerError(f"missing {label}: {path}")
    return path


def _snapshot_preview(path: Path) -> dict[str, str]:
    return {"source": str(path), "snapshot": "", "sha256": sha256_file(path)}


def _model_metadata(run_mode: str, env: dict[str, dict[str, Any]]) -> dict[str, Any]:
    # Thinking levels reflect the pinned env treatment when present; the
    # defaults mirror what an unpinned run actually gets (the batch runner's
    # GLM_THINKING:-xhigh fallback, the qwen config.toml thinking_level).
    return {
        "run_mode": run_mode,
        "qwen": {
            "enabled": run_mode != "glm_only",
            "provider": "dashscope",
            "model": "qwen3.6-flash",
            "thinking": _pinned_env_value(env, "QWEN_THINKING", "high"),
            "cache": "on",
        },
        "glm": {
            "enabled": run_mode != "qwen_only",
            "provider": "openrouter",
            "model": "z-ai/glm-5.1",
            "thinking": _pinned_env_value(env, "GLM_THINKING", "xhigh"),
        },
    }


def _pinned_env_value(env: dict[str, dict[str, Any]], key: str, default: str) -> str:
    meta = env.get(key)
    if not isinstance(meta, dict) or meta.get("redacted"):
        return default
    value = meta.get("value")
    return value if value else default


def render_command(args: argparse.Namespace, manifest: dict[str, Any]) -> str:
    qwen_config_dir = Path(_snapshot_or_source(manifest["config"]["qwen_config"])).parent
    glm_config_dir = Path(_snapshot_or_source(manifest["config"]["glm_config"])).parent
    ml_instance_file = _snapshot_or_source(manifest["slice"]["ml"])
    verified_instance_file = _snapshot_or_source(manifest["slice"]["verified"])
    env_exports = [
        f"export OPENSQUILLA_SOURCE_REPO={sh_quote(str(args.source_root))}",
        f"export RUN_MODE={sh_quote(args.run_mode)}",
        f"export CONDITION_LABEL={sh_quote(args.condition_label)}",
        f"export QWEN_CONFIG_DIR={sh_quote(str(qwen_config_dir))}",
        f"export GLM_CONFIG_DIR={sh_quote(str(glm_config_dir))}",
        f"export ML_INSTANCE_FILE={sh_quote(ml_instance_file)}",
        f"export VERIFIED_INSTANCE_FILE={sh_quote(verified_instance_file)}",
        f"export ML_COUNT={args.ml_count}",
        f"export VERIFIED_COUNT={args.verified_count}",
        f"export QWEN_WORKERS={args.qwen_workers}",
        f"export GLM_WORKERS={args.glm_workers}",
        f"export EVAL_WORKERS={args.eval_workers}",
    ]
    env_exports.extend(env_exports_for_command(manifest["config"]["env"]))
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "# Secrets are intentionally not embedded. Provide provider keys via",
            "# environment variables or stdin as expected by the handoff runner.",
            f"cd {sh_quote(str(args.handoff_root))}",
            *env_exports,
            f"{sh_quote(str(args.handoff_root / RUNNER_RELATIVE_PATH))}",
            "",
        ]
    )


def _snapshot_or_source(payload: dict[str, Any]) -> str:
    snapshot = str(payload.get("snapshot") or "")
    return snapshot or str(payload["source"])


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    raise SystemExit(main())
