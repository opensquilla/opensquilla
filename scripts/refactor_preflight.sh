#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/refactor_preflight.sh [--allow-dirty] [--expect-branch BRANCH]

Print the current refactor context before starting or resuming a stage.

Options:
  --allow-dirty          Do not fail if the worktree has uncommitted changes.
  --expect-branch NAME   Fail if the current branch is not NAME.
  --help                Show this help.
USAGE
}

allow_dirty=0
expect_branch=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-dirty)
      allow_dirty=1
      shift
      ;;
    --expect-branch)
      expect_branch="${2:-}"
      if [[ -z "$expect_branch" ]]; then
        echo "ERROR: --expect-branch requires a value" >&2
        exit 2
      fi
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

root="$(git rev-parse --show-toplevel)"
cd "$root"

branch="$(git branch --show-current)"

echo "== OpenSquilla refactor preflight =="
echo "root: $root"
echo "branch: $branch"
printf "head: "
git rev-parse --short HEAD

if [[ -n "$expect_branch" && "$branch" != "$expect_branch" ]]; then
  echo "ERROR: expected branch $expect_branch, found $branch" >&2
  exit 1
fi

echo
echo "== Required Superpowers checkpoints =="
echo "- superpowers:using-git-worktrees"
echo "- superpowers:writing-plans"
echo "- superpowers:test-driven-development"
echo "- superpowers:verification-before-completion"

echo
echo "== Status =="
git status --short --branch

if [[ "$allow_dirty" -eq 0 && -n "$(git status --porcelain)" ]]; then
  echo "ERROR: worktree is dirty; rerun with --allow-dirty only when resuming or planning." >&2
  exit 1
fi

echo
echo "== Recent commits =="
git log --oneline -8

echo
echo "== AGENTS.md scope =="
find . -name AGENTS.md -print | sort

echo
echo "== Refactor control docs =="
for path in docs/refactor/overall-plan.md docs/refactor/stage-template.md; do
  if [[ -f "$path" ]]; then
    echo "present: $path"
  else
    echo "missing: $path"
  fi
done

echo
echo "Preflight complete. Treat prior chat summaries as hints; current git state is authoritative."
