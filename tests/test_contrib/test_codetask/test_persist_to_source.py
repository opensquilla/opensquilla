"""persist_to_source: promote a verified build edit back to the stable repo."""

from __future__ import annotations

import subprocess

from opensquilla.contrib.codetask import workspace


def _git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)


def _init_repo(tmp_path):
    repo = tmp_path / "app"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "e@e")
    _git(repo, "config", "user.name", "e")
    (repo / "a.txt").write_text("hello\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, base


def test_applies_and_commits(tmp_path):
    repo, base = _init_repo(tmp_path)
    # produce a real patch (hello -> blue) then reset so the repo is clean@base
    (repo / "a.txt").write_text("blue\n")
    patch = _git(repo, "diff", "--binary", base).stdout
    _git(repo, "checkout", "--", "a.txt")
    assert not workspace.is_dirty(repo)

    ok, info = workspace.persist_to_source(repo, base, patch, "test edit")
    assert ok, info
    assert (repo / "a.txt").read_text() == "blue\n"
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() != base  # HEAD advanced


def test_rejects_dirty_source(tmp_path):
    repo, base = _init_repo(tmp_path)
    (repo / "a.txt").write_text("uncommitted\n")
    ok, info = workspace.persist_to_source(repo, base, "x", "m")
    assert not ok and "uncommitted" in info


def test_rejects_head_drift(tmp_path):
    repo, base = _init_repo(tmp_path)
    ok, info = workspace.persist_to_source(repo, "0" * 40, "x", "m")
    assert not ok and "moved" in info


def test_rejects_non_git(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    ok, info = workspace.persist_to_source(d, "x", "y", "m")
    assert not ok and "not a git repo" in info


def test_rejects_empty_patch(tmp_path):
    repo, base = _init_repo(tmp_path)
    ok, info = workspace.persist_to_source(repo, base, "   ", "m")
    assert not ok and "no change" in info


def test_bad_patch_does_not_commit(tmp_path):
    repo, base = _init_repo(tmp_path)
    ok, info = workspace.persist_to_source(repo, base, "garbage not a diff\n", "m")
    assert not ok and "apply failed" in info
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == base  # unchanged


def test_applies_to_empty_source_creates_first_commit(tmp_path):
    """An empty/unborn source repo (base_commit == "") accepts an all-new-files
    patch and gets its first commit — the build-from-scratch persist path."""
    # Build an "all new files" patch the way collect_change does for empty base:
    # stage files in a scratch repo and diff the index against the empty tree.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _git(scratch, "init", "-q")
    _git(scratch, "config", "user.email", "e@e")
    _git(scratch, "config", "user.name", "e")
    (scratch / "a.txt").write_text("blue\n")
    (scratch / "src").mkdir()
    (scratch / "src" / "index.ts").write_text("export const x = 1\n")
    _git(scratch, "add", "-A")
    empty_tree = _git(scratch, "hash-object", "-t", "tree", "/dev/null").stdout.strip()
    patch = _git(scratch, "diff", "--cached", "--binary", empty_tree).stdout
    assert patch.strip()

    # The unborn source repo: initialized, no commits.
    repo = tmp_path / "emptyapp"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "e@e")
    _git(repo, "config", "user.name", "e")
    assert not workspace.is_dirty(repo)

    ok, info = workspace.persist_to_source(repo, "", patch, "scaffold app")
    assert ok, info
    assert (repo / "a.txt").read_text() == "blue\n"
    assert (repo / "src" / "index.ts").exists()
    assert _git(repo, "rev-parse", "HEAD").stdout.strip()  # first commit created
