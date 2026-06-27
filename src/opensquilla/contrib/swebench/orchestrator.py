"""Orchestrator: wires all components together for SWE-bench evaluation.

Responsibilities:
- Single-instance execution (run_one_instance)
- Batch execution with resume support (run_batch)
- State persistence to state.jsonl
- Artifact management (prompt, logs, patch, metadata)
"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opensquilla.contrib.swebench.agent import OpenSquillaAdapter
from opensquilla.contrib.swebench.config import (
    get_artifact_dir,
    get_predictions_path,
    get_state_path,
)
from opensquilla.contrib.swebench.patch import clean_patch, collect_patch, is_empty_patch
from opensquilla.contrib.swebench.prediction import append_prediction, format_prediction
from opensquilla.contrib.swebench.prompt import build_prompt
from opensquilla.contrib.swebench.types import AgentResult, InstanceRecord, InstanceState
from opensquilla.contrib.swebench.workspace import SWEBenchWorkspace

logger = logging.getLogger(__name__)


def _save_metadata(
    artifact_dir: Path, record: InstanceRecord, agent_result: AgentResult | None
) -> None:
    """Save instance metadata to artifact_dir/metadata.json."""
    data: dict[str, Any] = {
        "instance_id": record.instance_id,
        "state": record.state.value,
        "model": record.model,
        "run_id": record.run_id,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "duration_seconds": record.duration_seconds,
        "patch_empty": record.patch_empty,
        "error": record.error,
    }
    if agent_result:
        data["agent"] = {
            "success": agent_result.success,
            "finish_reason": agent_result.finish_reason,
            "exit_code": agent_result.exit_code,
            "duration_seconds": agent_result.duration_seconds,
            "session_id": agent_result.session_id,
            "usage": agent_result.usage,
        }
    (artifact_dir / "metadata.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _append_state(state_path: Path, record: InstanceRecord) -> None:
    """Append an instance record to state.jsonl."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "instance_id": record.instance_id,
        "state": record.state.value,
        "model": record.model,
        "run_id": record.run_id,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "duration_seconds": record.duration_seconds,
        "patch_empty": record.patch_empty,
        "error": record.error,
    }
    with open(state_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_completed_ids(state_path: Path) -> set[str]:
    """Load instance IDs that have already completed (for resume)."""
    completed: set[str] = set()
    if not state_path.exists():
        return completed
    with open(state_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("state") in (
                    InstanceState.PATCH_COLLECTED.value,
                    InstanceState.EVAL_DONE.value,
                ):
                    completed.add(entry["instance_id"])
            except json.JSONDecodeError:
                continue
    return completed


def run_one_instance(
    instance: dict,
    adapter: OpenSquillaAdapter,
    model_name: str,
    run_id: str,
    setup_gitignore: bool = False,
    file_lock=None,
) -> InstanceRecord:
    """Run a single SWE-bench instance end-to-end.

    1. Create artifact dir
    2. Start workspace + prepare
    3. Build prompt, save to artifacts
    4. Send task to OpenSquilla
    5. Collect patch from workspace (runner-side, not agent-side)
    6. Clean patch, save to artifacts
    7. Append prediction to predictions.jsonl
    8. Save metadata, update state
    9. Cleanup workspace

    Returns:
        InstanceRecord with final state.
    """
    instance_id = instance["instance_id"]
    base_commit = instance["base_commit"]
    artifact_dir = get_artifact_dir(run_id, instance_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = get_predictions_path(run_id)
    state_path = get_state_path(run_id)

    record = InstanceRecord(
        instance_id=instance_id,
        state=InstanceState.RUNNING,
        model=model_name,
        run_id=run_id,
        started_at=datetime.now(UTC).isoformat(),
    )

    workspace: SWEBenchWorkspace | None = None
    agent_id = f"swe-{instance_id}".replace(".", "-")
    agent_result = None

    try:
        # 1. Create isolated agent (own workspace, sessions, memory)
        adapter.create_agent(agent_id)

        # 2. Start Docker workspace. Construction probes docker, so it stays
        # inside the guarded block — a missing/hung docker must still be
        # recorded as a failed instance.
        workspace = SWEBenchWorkspace(instance_id)
        container_name = workspace.start()
        workspace.prepare_instance(base_commit, setup_gitignore=setup_gitignore)

        # 3. Build and save prompt
        prompt = build_prompt(instance)
        (artifact_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

        # 4. Run agent
        logger.info("Sending task to OpenSquilla for %s (agent=%s)...", instance_id, agent_id)
        agent_result = adapter.send_task(
            prompt, agent_id=agent_id, container_name=container_name, artifact_dir=artifact_dir
        )
        logger.info(
            "Agent finished: success=%s finish=%s duration=%.1fs",
            agent_result.success,
            agent_result.finish_reason,
            agent_result.duration_seconds,
        )

        # 5. Collect patch (runner-side, regardless of agent success)
        raw_patch = collect_patch(workspace, base_commit)
        cleaned = clean_patch(raw_patch)
        patch_empty = is_empty_patch(cleaned)

        # Save raw and cleaned patch
        (artifact_dir / "git.patch").write_text(
            cleaned if not patch_empty else "", encoding="utf-8"
        )
        if raw_patch != cleaned:
            (artifact_dir / "git.patch.raw").write_text(raw_patch, encoding="utf-8")

        # 6. Backup session log before deleting agent
        adapter.backup_session(agent_id, artifact_dir)

        # 7. Write prediction
        prediction = format_prediction(instance_id, cleaned, model_name)
        if file_lock:
            with file_lock:
                append_prediction(prediction, predictions_path)
        else:
            append_prediction(prediction, predictions_path)

        # 8. Update record
        record.state = InstanceState.PATCH_COLLECTED
        record.patch_empty = patch_empty
        if agent_result.timeout:
            record.state = InstanceState.TIMEOUT
        elif not agent_result.success and patch_empty:
            record.state = InstanceState.FAILED
            record.error = f"agent_finish_reason={agent_result.finish_reason}"

    except Exception as e:
        logger.error("Instance %s failed: %s", instance_id, e)
        record.state = InstanceState.FAILED
        record.error = str(e)

    finally:
        # Always cleanup: delete agent first, then Docker container
        adapter.delete_agent(agent_id)
        if workspace is not None:
            workspace.cleanup()
        record.finished_at = datetime.now(UTC).isoformat()
        if record.started_at and record.finished_at:
            start = datetime.fromisoformat(record.started_at)
            end = datetime.fromisoformat(record.finished_at)
            record.duration_seconds = round((end - start).total_seconds(), 1)

        # Save metadata (per-instance dir, no lock needed) and shared state files
        _save_metadata(artifact_dir, record, agent_result)
        if file_lock:
            with file_lock:
                _append_state(state_path, record)
        else:
            _append_state(state_path, record)

    return record


def run_batch(
    instances: list[dict],
    adapter: OpenSquillaAdapter,
    model_name: str,
    run_id: str,
    setup_gitignore: bool = False,
    resume: bool = True,
    max_workers: int = 1,
) -> list[InstanceRecord]:
    """Run a batch of SWE-bench instances, optionally in parallel.

    Args:
        instances: List of instance dicts from dataset.
        adapter: OpenSquilla adapter.
        model_name: Model identifier for predictions.
        run_id: Unique run identifier.
        setup_gitignore: Whether to inject gitignore (for Multilingual).
        resume: If True, skip instances that already completed.
        max_workers: Number of parallel workers (1 = sequential).

    Returns:
        List of InstanceRecord for all processed instances.
    """
    state_path = get_state_path(run_id)
    completed_ids = _load_completed_ids(state_path) if resume else set()

    if completed_ids:
        logger.info("Resuming: %d instances already completed.", len(completed_ids))

    # Filter out already-completed instances
    to_run = []
    for i, instance in enumerate(instances):
        instance_id = instance["instance_id"]
        if instance_id in completed_ids:
            logger.info(
                "[%d/%d] Skipping %s (already completed)", i + 1, len(instances), instance_id
            )
        else:
            to_run.append(instance)

    total = len(to_run)
    if total == 0:
        logger.info("No instances to run.")
        return []

    logger.info("Running %d instances with %d worker(s).", total, max_workers)

    records = []

    if max_workers <= 1:
        # Sequential execution (original behavior)
        for i, instance in enumerate(to_run):
            logger.info("[%d/%d] Running %s...", i + 1, total, instance["instance_id"])
            record = run_one_instance(
                instance=instance,
                adapter=adapter,
                model_name=model_name,
                run_id=run_id,
                setup_gitignore=setup_gitignore,
            )
            records.append(record)
            logger.info(
                "[%d/%d] %s → %s (%.1fs, patch_empty=%s)",
                i + 1,
                total,
                instance["instance_id"],
                record.state.value,
                record.duration_seconds or 0,
                record.patch_empty,
            )
    else:
        # Parallel execution
        file_lock = threading.Lock()
        completed_count = 0
        count_lock = threading.Lock()

        def _run_and_log(instance: dict) -> InstanceRecord:
            nonlocal completed_count
            instance_id = instance["instance_id"]
            logger.info("Running %s...", instance_id)
            record = run_one_instance(
                instance=instance,
                adapter=adapter,
                model_name=model_name,
                run_id=run_id,
                setup_gitignore=setup_gitignore,
                file_lock=file_lock,
            )
            with count_lock:
                completed_count += 1
                logger.info(
                    "[%d/%d] %s → %s (%.1fs, patch_empty=%s)",
                    completed_count,
                    total,
                    instance_id,
                    record.state.value,
                    record.duration_seconds or 0,
                    record.patch_empty,
                )
            return record

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run_and_log, inst): inst["instance_id"] for inst in to_run}
            for future in as_completed(futures):
                instance_id = futures[future]
                try:
                    record = future.result()
                    records.append(record)
                except Exception as e:
                    logger.error("Instance %s raised exception: %s", instance_id, e)

    # Summary
    states: dict[str, int] = {}
    for r in records:
        states[r.state.value] = states.get(r.state.value, 0) + 1
    logger.info("Batch complete: %s", states)

    return records
