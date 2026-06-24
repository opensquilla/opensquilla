"""Pre-turn step: enforce coding mode when the operator toggle is ON.

Coding mode is an UNCONDITIONAL operator toggle, not an intent classifier.
While it is ON, every turn gets a directive that steers code changes through
the code-task plugin (``opensquilla code-task solve``) instead of letting the
agent clone and hand-edit repositories itself (which skips the runner-verified
red->green proof). No per-message detection is performed: the directive is
injected on every turn while coding mode is on, and not at all while it is off.

The directive does NOT tell the agent to run a BARE ``opensquilla``: the gateway
shell tools inherit the gateway process PATH, which frequently does NOT contain
the CLI's bin (the gateway is commonly started via an absolute interpreter
path). A bare command then fails to resolve, and the agent tends to
"self-install" and degrade to hand-editing. So the directive injects a
PATH-independent invocation resolved from the running interpreter (see
``resolve_code_task_command``), and falls back to a fail-loud directive when
code-task cannot be run at all.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import structlog

from opensquilla.engine.pipeline import TurnContext

log = structlog.get_logger(__name__)

_CODE_TASK_PREFLIGHT_TIMEOUT = 15.0


def _runs_code_task(argv: list[str]) -> bool:
    """True iff ``<argv> code-task --help`` exits 0 — i.e. the invocation works."""
    try:
        proc = subprocess.run(
            [*argv, "code-task", "--help"],
            capture_output=True,
            timeout=_CODE_TASK_PREFLIGHT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


_resolved_command: str | None = None
_resolution_succeeded = False


def _reset_resolution_cache() -> None:
    """Test helper: drop the memoized resolution."""
    global _resolved_command, _resolution_succeeded
    _resolved_command = None
    _resolution_succeeded = False


def resolve_code_task_command() -> str | None:
    """Resolve a PATH-independent, runnable ``code-task`` command prefix.

    Returns a shell-ready prefix ending at ``code-task`` (the caller appends
    ``solve ...``), e.g. ``/opt/env/bin/opensquilla code-task`` or
    ``/opt/env/bin/python -P -m opensquilla.cli.main code-task``; or ``None`` if
    code-task cannot be run here.

    A SUCCESSFUL resolution is memoized for the process lifetime (the
    interpreter / install layout is fixed while the gateway runs). A FAILURE is
    NOT cached, so a transient preflight timeout cannot permanently flip coding
    mode into the 'unavailable' directive until a restart.
    """
    global _resolved_command, _resolution_succeeded
    if _resolution_succeeded:
        return _resolved_command
    cmd = _resolve_code_task_command_uncached()
    if cmd is not None:
        _resolved_command = cmd
        _resolution_succeeded = True
    return cmd


def _resolve_code_task_command_uncached() -> str | None:
    # 1) The console script next to the running interpreter (venv / pip install).
    adjacent = Path(sys.executable).with_name("opensquilla")
    if (
        adjacent.is_file()
        and os.access(adjacent, os.X_OK)
        and _runs_code_task([str(adjacent)])
    ):
        return f"{shlex.quote(str(adjacent))} code-task"
    # 2) Module invocation via the EXACT interpreter the gateway runs on. ``-P``
    #    (Python 3.11+) keeps a cwd ``opensquilla`` package from shadowing the
    #    import once the agent cd's into a target repo.
    if _runs_code_task([sys.executable, "-P", "-m", "opensquilla.cli.main"]):
        return f"{shlex.quote(sys.executable)} -P -m opensquilla.cli.main code-task"
    # 3) Whatever ``opensquilla`` is on PATH — but only if it actually runs.
    on_path = shutil.which("opensquilla")
    if on_path and _runs_code_task([on_path]):
        return f"{shlex.quote(on_path)} code-task"
    return None


_CODING_MODE_DIRECTIVE_TEMPLATE = (
    "\n\n[CODING MODE — ACTIVE]\n"
    "The operator has enabled coding mode for this session. For ANY request "
    "that changes code in a real repository the user names by a filesystem "
    "path or a git URL (fix a bug, add/implement a feature, edit a file, "
    "resolve a GitHub issue), you MUST do the work by running\n"
    "    __CODE_TASK_CMD__ solve --repo <url-or-path> "
    '(--issue N | --task "<text>" | --task-file <path>) --yes\n'
    "Use that command EXACTLY as written above — it is resolved to run in THIS "
    "environment regardless of PATH. Do NOT replace it with a bare "
    "`opensquilla`, do NOT `pip install` OpenSquilla, and if that command fails "
    "to run, STOP and report that code-task / the environment is broken instead "
    "of working around it by hand.\n"
    "For building an app or UI from scratch (e.g. an Electron + React "
    "desktop app), add --verification-mode build so code-task verifies the "
    "app compiles and packages instead of running red->green tests.\n"
    "BUILD-FROM-SCRATCH — ASK BRIEFLY WHEN THE REQUEST IS ONLY A CATEGORY: "
    "decide by whether you know WHAT THE APP SHOULD DO, not just what kind it "
    "is. If the request gives only a broad app type or goal with no concrete "
    "features, target user, or scope (e.g. 'make me an English-learning app', "
    "'build a drawing app', 'make me an app'), ASK 1-2 focused questions — most "
    "usefully its core features/screens and who it is for — and STOP this turn "
    "(do NOT call code-task until the user answers). If the request already "
    "names concrete features, scope, or target users, do NOT ask — build it, "
    "choosing sensible defaults for the rest and briefly stating your "
    "assumptions. NEVER ask about platform, framework, or styling; just default "
    "those. Keep it to at most 2 questions and never interrogate. (Concrete bug "
    "fixes or feature changes in a named repo never need this.)\n"
    "For a follow-up change to an app you already built (e.g. add a section "
    "or change the color), point --repo at that app's repo and keep "
    "--verification-mode build; code-task edits the existing app in place and "
    "applies the verified change back to the repo so the next edit builds on it.\n"
    "code-task runs for MANY minutes (often 20-40), so it is a long-running "
    "task: ALWAYS launch it with background_process and then await it with "
    'process(action="wait", session_id=...). Do NOT run code-task with a '
    "blocking exec_command — exec_command is hard-capped at 600s (10 min) no "
    "matter what timeout you pass, so it would kill code-task mid-run and "
    "waste the attempt. Do not poll process(action=\"poll\") in a loop "
    "either — just wait for the result.\n"
    "code-task works in an ISOLATED run directory, NOT in the --repo source you "
    "pass it: that source stays EMPTY until a run finishes and VERIFIES, then "
    "the change is committed back. So do NOT judge progress by the source "
    "repo's files and do NOT conclude it is 'stuck' because the source looks "
    "empty. Let process(action=\"wait\") return the result — do NOT kill the "
    "run, do NOT 'clean and retry', and do NOT launch the same task again while "
    "one is still running. Decide success ONLY from the returned result (its "
    "state and build.installer_path, which point into the run directory); the "
    "run prints its run directory on startup and writes live progress to "
    "<run_dir>/status.json.\n"
    "Do NOT clone the repository yourself and do NOT hand-edit its files in "
    "this session: the file-editing tools (write_file, edit_file, apply_patch, "
    "execute_code, git_commit, create_*) are DISABLED while coding mode is on, and "
    "in-session edits skip code-task's isolation and the "
    "runner-verified red→green proof, so they are not equivalent and are not "
    "allowed while coding mode is on. Read-only requests (showing structure, "
    "explaining code) and ordinary conversation are answered normally."
)

_CODING_MODE_UNAVAILABLE_DIRECTIVE = (
    "\n\n[CODING MODE — ACTIVE, but code-task is UNAVAILABLE]\n"
    "The operator enabled coding mode, which requires every code change to go "
    "through the code-task plugin — but `opensquilla code-task` cannot be run "
    "in this environment (the OpenSquilla CLI is not installed or not runnable "
    "here). For ANY request that would change code, STOP and tell the user that "
    "code-task is unavailable and the environment must be fixed (install "
    "OpenSquilla so `opensquilla code-task` runs — e.g. `bash "
    "scripts/install_source.sh`, which uses uv to provision Python 3.12). "
    "Do NOT try to `pip install` OpenSquilla yourself, do NOT clone the "
    "repository, and do NOT hand-edit files via the shell as a workaround — the "
    "in-session file-editing tools are disabled and a manual workaround skips "
    "code-task's isolation and verification. Do NOT run any installation or repair commands yourself (no `pip install`, no `bash scripts/install_source.sh`, no building OpenSquilla) — surface the problem to the user/operator and let THEM fix the environment. Read-only requests (showing "
    "structure, explaining code) and ordinary conversation are answered "
    "normally."
)


def _build_coding_mode_directive() -> str:
    """The coding-mode directive with a resolved, runnable code-task command,
    or a fail-loud directive when code-task cannot be run in this environment."""
    cmd = resolve_code_task_command()
    if cmd is None:
        return _CODING_MODE_UNAVAILABLE_DIRECTIVE
    return _CODING_MODE_DIRECTIVE_TEMPLATE.replace("__CODE_TASK_CMD__", cmd)


def _coding_mode_on(ctx: TurnContext) -> bool:
    skills_cfg = getattr(ctx.config, "skills", None) if getattr(ctx, "config", None) else None
    return bool(getattr(skills_cfg, "coding_mode", False))


async def enforce_coding_mode(ctx: TurnContext) -> TurnContext:
    """Inject the coding-mode directive + pin code-task while the toggle is on."""
    if not _coding_mode_on(ctx):
        return ctx

    # Resolve the code-task invocation off the event loop (cached after first).
    directive = await asyncio.to_thread(_build_coding_mode_directive)

    sp = getattr(ctx, "system_prompt", None)
    if sp is not None:
        # Append to the uncached suffix slot so upstream cache breakpoints stay
        # stable across turns (same shape handling as meta_resolution).
        if isinstance(sp, str):
            base, suffix = sp, ""
        else:
            base, suffix = sp
        new_suffix = f"{suffix}{directive}" if suffix else directive
        ctx.system_prompt = (base, new_suffix)

    # Pin code-task so a relevance filter (when filter_enabled) cannot drop its
    # description from <available_skills>; filter_skills honors this metadata.
    ctx.metadata["pinned_skills"] = list({*ctx.metadata.get("pinned_skills", []), "code-task"})
    ctx.metadata["coding_mode"] = True
    log.info("coding_mode.enforced")
    return ctx
