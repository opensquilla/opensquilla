"""Single-task orchestration for code-task (host mode, single-threaded).

Pipeline: resolve task -> clone repo + task branch -> probe env -> render
prompt -> run host agent -> collect change -> verify (red/green/regression)
-> assemble TaskResult. No thread pool, no resume: one call solves one task.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opensquilla.contrib.codetask import config, envprobe, workspace
from opensquilla.contrib.codetask.adapter import LocalAdapter
from opensquilla.contrib.codetask.inputs import TaskSpec, render_task_md, resolve_task
from opensquilla.contrib.codetask.types import TaskResult, TaskState
from opensquilla.contrib.codetask.verification import verify

logger = logging.getLogger(__name__)

TRUSTED_HOST_WARNING = (
    "code-task runs an agent on the HOST that may install dependencies and "
    "execute repository code. This is NOT an OS sandbox. Only run it against "
    "repositories you trust."
)


def _default_run_id(slug: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"codetask-{slug}-{stamp}"


def solve(
    *,
    repo: str,
    issue: int | None = None,
    task: str | None = None,
    task_file: str | None = None,
    base_ref: str | None = None,
    shallow: bool = False,
    model: str = "",
    thinking: str = "",
    timeout: int = config.DEFAULT_AGENT_TIMEOUT,
    verification_mode: str = "red-green",
    run_id: str | None = None,
) -> TaskResult:
    """Run one code-task end-to-end and return a structured TaskResult."""
    # 1. Resolve the task text first (cheap), so a bad task fails before cloning.
    #    Issue mode may need the clone to resolve the repo, so clone first when
    #    --issue is used.
    spec: TaskSpec
    run_id = run_id or _default_run_id("task")

    if issue is not None:
        prepared = workspace.prepare_repo(
            run_id, repo, base_ref=base_ref, shallow=shallow, slug="task"
        )
        spec = resolve_task(issue_number=issue, repo_dir=prepared.path)
        # Re-slug the run/branch off the resolved issue title for readability.
        run_id_final = run_id
    else:
        spec = resolve_task(task_text=task, task_file=task_file)
        run_id_final = run_id or _default_run_id(spec.slug)
        prepared = workspace.prepare_repo(
            run_id_final, repo, base_ref=base_ref, shallow=shallow, slug=spec.slug
        )

    rid = run_id_final
    artifact_dir = config.run_dir(rid)
    scratch = config.scratch_dir(rid)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # 2. Persist task.md.
    task_md = render_task_md(
        spec, repo=repo, base_ref=prepared.base_ref, commit=prepared.base_commit
    )
    config.artifact_path(rid, "task.md").write_text(task_md)

    # 3. Probe environment + render prompt.
    probe = envprobe.probe(prepared.path)
    is_edit = verification_mode == "build" and _repo_has_app(prepared.path)
    prompt = _render_prompt(task_md, probe.as_hints(), scratch, verification_mode, is_edit)
    config.artifact_path(rid, "prompt.txt").write_text(prompt)

    result = TaskResult(
        task_slug=spec.slug,
        run_id=rid,
        state=TaskState.FAILED,
        repo=repo,
        base_ref=prepared.base_ref,
        branch=prepared.branch,
        source=spec.source,
        artifact_dir=str(artifact_dir),
    )
    result.verification_kind = "build" if verification_mode == "build" else "red_green"

    # 4. Run the agent on the host.
    adapter = LocalAdapter(model=model, thinking=thinking, timeout=timeout)
    try:
        outcome = adapter.run(
            prompt, repo=prepared.path, scratch_dir=scratch, artifact_dir=artifact_dir
        )
    except RuntimeError as exc:
        result.error = str(exc)
        _persist(result)
        return result

    result.usage = outcome.usage
    result.duration_seconds = outcome.duration_seconds

    # 5. Collect the change from the task branch.
    files_changed, diffstat, patch = workspace.collect_change(prepared.path, prepared.base_commit)
    result.files_changed = files_changed
    result.diffstat = diffstat
    result.commits = workspace.count_commits(prepared.path, prepared.base_commit)
    if patch.strip():
        patch_path = config.artifact_path(rid, "change.patch")
        patch_path.write_text(patch)
        result.patch_path = str(patch_path)

    # Persist the agent's verification manifest into the run dir for the
    # record (scratch lives under the system temp dir so the sandbox can
    # write it; the run dir is the durable home for artifacts). Done before
    # the timeout return so a manifest emitted before a timeout is kept.
    _archive_manifest(scratch, rid)

    if outcome.timeout:
        result.state = TaskState.ENVIRONMENT_BLOCKED
        result.error = "agent timed out before finishing"
        _persist(result)
        return result

    # 6. Verify, runner-authoritative. Build mode runs a fixed build
    #    checklist (from-scratch apps have no red->green test loop);
    #    red-green mode runs the agent's acceptance tests + regression.
    if verification_mode == "build":
        from opensquilla.contrib.codetask.build_verify import verify_build

        bout = verify_build(prepared.path)
        result.state = bout.state
        result.build = bout.build
        result.verified = bout.state == TaskState.VERIFIED
        if bout.detail and not result.error:
            result.error = bout.detail
    else:
        vout = verify(
            repo=prepared.path,
            base_commit=prepared.base_commit,
            scratch_dir=scratch,
        )
        result.state = vout.state
        result.acceptance = vout.acceptance
        result.regression = vout.regression
        result.assumptions = vout.assumptions
        result.verified = vout.state == TaskState.VERIFIED
        if vout.detail and not result.error:
            result.error = vout.detail

    # Build mode: promote a VERIFIED change back onto the stable LOCAL source
    # repo so follow-up edits iterate on the same app (URLs are not touched).
    if verification_mode == "build" and result.state == TaskState.VERIFIED and patch.strip():
        _is_local = ("://" not in repo) and not repo.startswith("git@")
        _src = Path(repo).expanduser()
        if _is_local and _src.exists() and (_src.resolve() / ".git").is_dir():
            ok, info = workspace.persist_to_source(
                _src.resolve(), prepared.base_commit, patch, f"code-task: {spec.slug}"
            )
            result.persisted = ok
            if ok:
                result.source_repo = str(_src.resolve())
            elif not result.error:
                result.error = f"verified but not persisted to source: {info}"

    _persist(result)
    return result


def _archive_manifest(scratch: Path, run_id: str) -> None:
    """Copy the agent's verification.json from scratch into the run dir."""
    src = scratch / config.VERIFICATION_MANIFEST_NAME
    if not src.is_file():
        return
    try:
        config.artifact_path(run_id, config.VERIFICATION_MANIFEST_NAME).write_text(src.read_text())
    except OSError:
        pass


def _repo_has_app(repo: Path) -> bool:
    """True if the cloned repo already contains a JS app (edit, not scaffold)."""
    return (repo / "package.json").is_file() and (repo / "src").is_dir()


def _render_prompt(
    task_md: str,
    hints: str,
    scratch: Path,
    verification_mode: str = "red-green",
    is_edit: bool = False,
) -> str:
    template = config.prompt_template_path(verification_mode, is_edit).read_text()
    hints_block = f"\n{hints}\n" if hints else ""
    return template.format(
        task=task_md,
        env_hints=hints_block,
        scratch_dir=str(scratch),
        manifest_name=config.VERIFICATION_MANIFEST_NAME,
    )


def _result_to_dict(result: TaskResult) -> dict[str, Any]:
    data = asdict(result)
    data["state"] = result.state.value
    return data


def _persist(result: TaskResult) -> None:
    config.artifact_path(result.run_id, "result.json").write_text(
        json.dumps(_result_to_dict(result), indent=2, ensure_ascii=False)
    )
