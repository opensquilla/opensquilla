"""Pre-turn step: enforce coding mode when the operator toggle is ON.

Coding mode is an UNCONDITIONAL operator toggle, not an intent classifier.
While it is ON, every turn gets a directive that steers code changes through
the code-task plugin (``opensquilla code-task solve``) instead of letting the
agent clone and hand-edit repositories itself (which skips the runner-verified
red→green proof). No per-message detection is performed: the directive is
injected on every turn while coding mode is on, and not at all while it is off.
"""

from __future__ import annotations

import structlog

from opensquilla.engine.pipeline import TurnContext

log = structlog.get_logger(__name__)

_CODING_MODE_DIRECTIVE = (
    "\n\n[CODING MODE — ACTIVE]\n"
    "The operator has enabled coding mode for this session. For ANY request "
    "that changes code in a real repository the user names by a filesystem "
    "path or a git URL (fix a bug, add/implement a feature, edit a file, "
    "resolve a GitHub issue), you MUST do the work by running\n"
    "    opensquilla code-task solve --repo <url-or-path> "
    '(--issue N | --task "<text>" | --task-file <path>) --yes\n'
    "Do NOT clone the repository yourself and do NOT hand-edit its files in "
    "this session: in-session edits skip code-task's isolation and the "
    "runner-verified red→green proof, so they are not equivalent and are not "
    "allowed while coding mode is on. Read-only requests (showing structure, "
    "explaining code) and ordinary conversation are answered normally."
)


def _coding_mode_on(ctx: TurnContext) -> bool:
    skills_cfg = getattr(ctx.config, "skills", None) if getattr(ctx, "config", None) else None
    return bool(getattr(skills_cfg, "coding_mode", False))


async def enforce_coding_mode(ctx: TurnContext) -> TurnContext:
    """Inject the coding-mode directive + pin code-task while the toggle is on."""
    if not _coding_mode_on(ctx):
        return ctx

    sp = getattr(ctx, "system_prompt", None)
    if sp is not None:
        # Append to the uncached suffix slot so upstream cache breakpoints stay
        # stable across turns (same shape handling as meta_resolution).
        if isinstance(sp, str):
            base, suffix = sp, ""
        else:
            base, suffix = sp
        new_suffix = f"{suffix}{_CODING_MODE_DIRECTIVE}" if suffix else _CODING_MODE_DIRECTIVE
        ctx.system_prompt = (base, new_suffix)

    # Pin code-task so a relevance filter (when filter_enabled) cannot drop its
    # description from <available_skills>; filter_skills honors this metadata.
    ctx.metadata["pinned_skills"] = list({*ctx.metadata.get("pinned_skills", []), "code-task"})
    ctx.metadata["coding_mode"] = True
    log.info("coding_mode.enforced")
    return ctx
