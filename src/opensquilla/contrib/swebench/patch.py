"""Patch collection, cleaning, and empty-patch detection.

Responsible for:
1. Collecting git diff from a workspace
2. Removing noise (setup files, binary diffs)
3. Detecting empty patches
"""

import logging

from opensquilla.contrib.swebench.config import SETUP_FILES_TO_REMOVE
from opensquilla.contrib.swebench.workspace import SWEBenchWorkspace

logger = logging.getLogger(__name__)


def collect_patch(workspace: SWEBenchWorkspace, base_commit: str) -> str:
    """Collect raw patch from the workspace container.

    This is the single source of truth for patch extraction.
    Called by the runner, NOT by the agent.
    """
    return workspace.get_git_diff(base_commit)


def _has_non_ascii(s: str) -> bool:
    """Check if a string contains any non-ASCII characters."""
    return any(ord(c) > 127 for c in s)


def clean_patch(patch: str) -> str:
    """Remove noise from a raw patch.

    - Strips modifications to setup files (pyproject.toml, tox.ini, setup.py)
      and dependency lock files (package-lock.json, yarn.lock, Cargo.lock, etc.)
    - Strips binary diff sections
    - Strips diffs whose filenames contain non-ASCII bytes (these cause git apply
      / SWE-bench harness UnicodeDecodeError and skip the whole instance)
    - Strips trailing whitespace
    """
    if not patch or not patch.strip():
        return ""

    cleaned_hunks: list[str] = []
    current_hunk: list[str] = []
    skip_current = False

    for line in patch.splitlines(keepends=True):
        # Detect start of a new file diff
        if line.startswith("diff --git"):
            # Flush previous hunk
            if current_hunk and not skip_current:
                cleaned_hunks.extend(current_hunk)
            current_hunk = [line]
            skip_current = False

            # Check if this file should be removed
            for setup_file in SETUP_FILES_TO_REMOVE:
                if f"a/{setup_file}" in line or f"b/{setup_file}" in line:
                    skip_current = True
                    logger.debug("Stripping setup file from patch: %s", setup_file)
                    break

            # Check for non-ASCII filename (git apply / harness can't handle these)
            if not skip_current and _has_non_ascii(line):
                skip_current = True
                logger.debug("Stripping non-ASCII filename diff from patch")

            # Check for binary diff
            if "Binary files" in line:
                skip_current = True
        else:
            current_hunk.append(line)

            # Also detect binary markers mid-hunk
            if line.startswith("Binary files") or line.startswith("GIT binary patch"):
                skip_current = True

    # Flush last hunk
    if current_hunk and not skip_current:
        cleaned_hunks.extend(current_hunk)

    result = "".join(cleaned_hunks).rstrip()
    # Ensure patch ends with newline so `patch` command can apply it
    if result:
        result += "\n"
    return result


def is_empty_patch(patch: str) -> bool:
    """Check if a patch is empty or contains no meaningful changes."""
    if not patch or not patch.strip():
        return True

    # A patch with only diff headers but no actual +/- lines is empty
    has_changes = False
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            has_changes = True
            break
        if line.startswith("-") and not line.startswith("---"):
            has_changes = True
            break

    return not has_changes
