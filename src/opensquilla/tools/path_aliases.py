"""Generalised path alias for sandbox / model-hallucinated workspace paths.

The LLM may emit absolute paths that "look like" a workspace but don't
match the gateway's configured ``workspace_root`` byte-for-byte. Three
typical sources observed in production:

* ``/workspace/...`` — the canonical cwd that ``execute_code`` sandboxes
  expose to the model. The LLM sees this in stdout and reuses it in
  subsequent ``read_file`` / ``write_file`` / ``publish_artifact`` calls.
* ``<default-home>/.opensquilla/workspace/...`` — the default workspace
  pattern. LLMs trained on OpenSquilla docs may emit this even when the
  gateway has overridden ``workspace_dir`` in config.toml.
* ``<other-home>/.opensquilla/workspace/...`` — same prior on alternate
  deployments.

Rather than maintain a growing list of known prefixes, we recognise
the **shape**: any absolute path with a segment literally named
``workspace`` is treated as workspace-rooted, and everything **after
the last such segment** becomes the workspace-relative tail. The tail
is then resolved against the real ``workspace_root``.

Examples (with ``workspace_root = <configured-workspace>``):

* ``<default-home>/.opensquilla/workspace/abstract.tex``
  → tail ``abstract.tex`` → ``<configured-workspace>/abstract.tex``
* ``<other-home>/.opensquilla/workspace/papers/intro.tex``
  → tail ``papers/intro.tex`` → ``<configured-workspace>/papers/intro.tex``
* ``/workspace/foo`` → ``<configured-workspace>/foo``
* ``<configured-workspace>/x.tex`` (the real path)
  → tail ``x.tex`` → identical resolved path (idempotent, harmless)
* ``/etc/passwd`` — no ``workspace`` segment, ``None`` returned, the
  caller's pre-existing sensitive-path / workspace-strict checks run
  unchanged.

The alias only fires when ``workspace_root`` is configured and the
input is absolute. Relative paths are left for the caller's existing
"join under workspace_root" logic.
"""

from __future__ import annotations

from pathlib import Path, PurePath

_WORKSPACE_SEGMENT = "workspace"


def _is_rooted_path(raw_path: PurePath) -> bool:
    return raw_path.is_absolute() or bool(raw_path.root)


def resolve_workspace_alias(raw_path: PurePath, workspace_root: Path | None) -> Path | None:
    """Translate an LLM-supplied absolute path to the real workspace.

    Returns ``None`` when:
      * ``workspace_root`` is unset (no alias resolution possible).
      * ``raw_path`` is not absolute (caller's relative-path branch
        handles it).
      * ``raw_path`` has no path segment literally named ``workspace``.

    Otherwise returns ``workspace_root / <tail-after-last-workspace-segment>``
    as a resolved ``strict=False`` Path. Idempotent for paths already
    rooted at ``workspace_root``.
    """

    if workspace_root is None or not _is_rooted_path(raw_path):
        return None

    parts = raw_path.parts
    # Use the rightmost workspace boundary so paths shaped like
    # ``/<some-prefix>/workspace/<intended-relative-tail>`` map the tail
    # back into the configured host workspace.
    last_idx = -1
    for i, segment in enumerate(parts):
        if segment == _WORKSPACE_SEGMENT:
            last_idx = i
    if last_idx < 0:
        return None

    tail_parts = parts[last_idx + 1:]
    return (workspace_root.joinpath(*tail_parts)).resolve(strict=False)
