#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/refactor_stage_close.sh [--allow-dirty]

Check that a refactor stage is ready to report or merge. This script verifies
worktree status, the latest commit trailer, and prints the latest commit hash.

Options:
  --allow-dirty   Report dirty files instead of failing.
  --help          Show this help.
USAGE
}

allow_dirty=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-dirty)
      allow_dirty=1
      shift
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

echo "== Stage close check =="
git status --short --branch

if [[ -n "$(git status --porcelain)" ]]; then
  if [[ "$allow_dirty" -eq 0 ]]; then
    echo "ERROR: worktree is dirty. Commit or stash stage changes first." >&2
    exit 1
  fi
  echo "WARNING: worktree is dirty; continuing because --allow-dirty was set." >&2
fi

head="$(git rev-parse --short HEAD)"
message="$(git log -1 --pretty=%B)"

echo
echo "head: $head"
echo
echo "== Latest commit message =="
printf '%s\n' "$message"

trailer_count="$(printf '%s\n' "$message" | grep -c '^Co-authored-by: Codex <noreply@openai.com>$' || true)"
if [[ "$trailer_count" != "1" ]]; then
  echo "ERROR: latest commit must contain the Codex co-author trailer exactly once." >&2
  exit 1
fi

echo
echo "Stage close check complete."
