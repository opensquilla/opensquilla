"""High-level single-instance entry point for the SWE-bench harness.

``solve_instance`` is what the CLI (and the bundled skill through it)
calls: resolve the instance, make sure its image is available, run the
agent, collect the patch, optionally evaluate — and return one
JSON-serializable dict describing the outcome.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from opensquilla.contrib.swebench.agent import OpenSquillaAdapter
from opensquilla.contrib.swebench.config import (
    DATASET_MULTILINGUAL,
    DATASET_VERIFIED,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_EVAL_TIMEOUT,
    DEFAULT_MODEL,
    DEFAULT_SPLIT,
    DEFAULT_THINKING,
    get_artifact_dir,
    get_predictions_path,
)
from opensquilla.contrib.swebench.images import ensure_image
from opensquilla.contrib.swebench.orchestrator import run_one_instance

logger = logging.getLogger(__name__)

DATASET_ALIASES = {
    "verified": DATASET_VERIFIED,
    "multilingual": DATASET_MULTILINGUAL,
}


def resolve_dataset_name(dataset: str) -> str:
    """Map shorthand dataset names to full HuggingFace names."""
    return DATASET_ALIASES.get(dataset.lower(), dataset)


def _default_run_id(instance_id: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"solve-{instance_id}-{stamp}"


def _eval_resolved_status(eval_cwd_run_id: str, instance_id: str) -> bool | None:
    """Best-effort: parse the harness report for the instance's resolved bit.

    The harness writes ``<model>.<run_id>.json`` with ``resolved_ids`` into
    its cwd. Returns None when no report can be found or parsed.
    """
    from opensquilla.contrib.swebench.config import artifacts_root

    eval_dir = artifacts_root() / "eval" / eval_cwd_run_id
    if not eval_dir.exists():
        return None
    for report in sorted(eval_dir.glob("*.json")):
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        resolved_ids = data.get("resolved_ids")
        if isinstance(resolved_ids, list):
            return instance_id in resolved_ids
    return None


def solve_instance(
    instance_id: str,
    dataset: str = "verified",
    split: str = DEFAULT_SPLIT,
    model: str = DEFAULT_MODEL,
    thinking: str = DEFAULT_THINKING,
    timeout: int = DEFAULT_AGENT_TIMEOUT,
    run_id: str | None = None,
    pull: bool = True,
    build: bool = False,
    evaluate: bool = False,
    eval_timeout: int = DEFAULT_EVAL_TIMEOUT,
) -> dict[str, Any]:
    """Run one SWE-bench instance end-to-end and return a result dict.

    The returned dict is stable JSON output for programmatic consumers
    (CLI --json, the bundled skill): instance_id, run_id, state,
    patch_empty, patch_path, artifact_dir, duration_seconds, usage,
    resolved (None unless evaluate=True succeeded), error.
    """
    from opensquilla.contrib.swebench.dataset import load_instances

    dataset_name = resolve_dataset_name(dataset)
    run_id = run_id or _default_run_id(instance_id)

    instances = load_instances(dataset_name, split=split, instance_ids=[instance_id])
    if not instances:
        return {
            "instance_id": instance_id,
            "run_id": run_id,
            "state": "failed",
            "error": f"instance not found in {dataset_name} (split={split})",
            "patch_empty": None,
            "patch_path": None,
            "artifact_dir": None,
            "duration_seconds": None,
            "usage": {},
            "resolved": None,
        }
    instance = instances[0]

    image = ensure_image(instance_id, dataset_name, pull=pull, build=build)
    logger.info("Using image %s", image)

    adapter = OpenSquillaAdapter(model=model, timeout=timeout, thinking=thinking)
    record = run_one_instance(
        instance=instance,
        adapter=adapter,
        model_name=model or "squilla-router",
        run_id=run_id,
        setup_gitignore=dataset_name == DATASET_MULTILINGUAL,
    )

    artifact_dir = get_artifact_dir(run_id, instance_id)
    patch_path = artifact_dir / "git.patch"
    usage: dict[str, Any] = {}
    usage_path = artifact_dir / "usage.json"
    if usage_path.exists():
        try:
            usage = json.loads(usage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    resolved: bool | None = None
    if evaluate and not record.patch_empty:
        from opensquilla.contrib.swebench.evaluate import run_evaluation

        eval_run_id = f"eval-{run_id}"
        code = run_evaluation(
            predictions_path=get_predictions_path(run_id),
            dataset_name=dataset_name,
            run_id=eval_run_id,
            instance_ids=[instance_id],
            max_workers=1,
            timeout=eval_timeout,
        )
        if code == 0:
            resolved = _eval_resolved_status(eval_run_id, instance_id)

    result = {
        "instance_id": instance_id,
        "run_id": run_id,
        "state": record.state.value,
        "patch_empty": record.patch_empty,
        "patch_path": str(patch_path) if patch_path.exists() else None,
        "artifact_dir": str(artifact_dir),
        "duration_seconds": record.duration_seconds,
        "usage": usage,
        "resolved": resolved,
        "error": record.error,
    }
    # Persist the result next to the other per-instance artifacts so
    # non-JSON callers can still find it.
    (artifact_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result
