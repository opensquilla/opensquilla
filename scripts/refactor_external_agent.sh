#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/refactor_external_agent.sh --slot NAME --branch BRANCH --prompt FILE [options]

Runs a refactor worker as an independent Codex CLI process in its own git
worktree. This bypasses same-thread spawn_agent limits while keeping branch
ownership and cleanup explicit.

Required:
  --slot NAME       Stable worktree slot name, e.g. provider-catalog.
  --branch BRANCH   Child branch to create or reuse.
  --prompt FILE     Prompt file for codex exec. Use '-' to read from stdin.

Options:
  --base REF        Base ref for a new branch. Defaults to current HEAD.
  --worktree DIR    Worktree path. Defaults to ../opensquilla-refactor-agent-NAME.
  --model MODEL     Codex model. Defaults to CLI/config default.
  --background      Start the worker in the background and print the PID/logs.
                    Use this from a persistent shell; Codex tool sessions should
                    keep workers in foreground sessions and poll them.
  --force-existing  Allow reusing an existing clean worktree for the branch.
  -h, --help        Show this help.

Examples:
  scripts/refactor_external_agent.sh \
    --slot provider-catalog \
    --branch codex/refactor-provider-status-catalog-batch \
    --prompt /tmp/provider-catalog-agent.md \
    --background

After a child branch is merged, remove its worktree with:
  git worktree remove ../opensquilla-refactor-agent-provider-catalog
  git worktree prune
USAGE
}

slot=""
branch=""
prompt=""
base=""
worktree=""
model=""
background=0
force_existing=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slot)
      slot="${2:-}"
      shift 2
      ;;
    --branch)
      branch="${2:-}"
      shift 2
      ;;
    --prompt)
      prompt="${2:-}"
      shift 2
      ;;
    --base)
      base="${2:-}"
      shift 2
      ;;
    --worktree)
      worktree="${2:-}"
      shift 2
      ;;
    --model)
      model="${2:-}"
      shift 2
      ;;
    --background)
      background=1
      shift
      ;;
    --force-existing)
      force_existing=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$slot" || -z "$branch" || -z "$prompt" ]]; then
  usage >&2
  exit 2
fi

if [[ "$slot" == *"/"* || "$slot" == *".."* || "$slot" =~ [[:space:]] ]]; then
  echo "--slot must be a simple stable name without slashes, spaces, or '..'" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [[ -z "$base" ]]; then
  base="HEAD"
fi

if [[ -z "$worktree" ]]; then
  worktree="../opensquilla-refactor-agent-$slot"
fi

if [[ "$prompt" != "-" && ! -f "$prompt" ]]; then
  echo "Prompt file not found: $prompt" >&2
  exit 2
fi

if [[ -e "$worktree" ]]; then
  if [[ ! -d "$worktree/.git" && ! -f "$worktree/.git" ]]; then
    echo "Refusing to reuse non-git path: $worktree" >&2
    exit 2
  fi
  current_branch="$(git -C "$worktree" branch --show-current)"
  if [[ "$current_branch" != "$branch" ]]; then
    echo "Existing worktree is on $current_branch, expected $branch: $worktree" >&2
    exit 2
  fi
  if [[ "$force_existing" -ne 1 ]]; then
    echo "Worktree already exists. Pass --force-existing after checking it is intentional: $worktree" >&2
    exit 2
  fi
else
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    git worktree add "$worktree" "$branch"
  else
    git worktree add -b "$branch" "$worktree" "$base"
  fi
fi

if [[ -n "$(git -C "$worktree" status --short)" ]]; then
  echo "Refusing to start worker in dirty worktree: $worktree" >&2
  git -C "$worktree" status --short
  exit 1
fi

git_common_dir="$(git rev-parse --git-common-dir)"
log_dir="$git_common_dir/refactor-agents"
mkdir -p "$log_dir"

timestamp="$(date +%Y%m%dT%H%M%S%z)"
log_file="$log_dir/$timestamp-$slot.log"
last_message_file="$log_dir/$timestamp-$slot.last.md"

cmd=(codex exec --ephemeral -C "$worktree" --dangerously-bypass-approvals-and-sandbox --output-last-message "$last_message_file")
if [[ -n "$model" ]]; then
  cmd+=(--model "$model")
fi
cmd+=(-)

echo "slot=$slot"
echo "branch=$branch"
echo "worktree=$worktree"
echo "log=$log_file"
echo "last_message=$last_message_file"

if [[ "$background" -eq 1 ]]; then
  if [[ "$prompt" == "-" ]]; then
    echo "Cannot use --background with --prompt -; provide a prompt file." >&2
    exit 2
  fi
  nohup "${cmd[@]}" < "$prompt" > "$log_file" 2>&1 &
  pid=$!
  echo "$pid" > "$log_dir/$slot.pid"
  echo "pid=$pid"
else
  if [[ "$prompt" == "-" ]]; then
    "${cmd[@]}" 2>&1 | tee "$log_file"
  else
    "${cmd[@]}" < "$prompt" 2>&1 | tee "$log_file"
  fi
fi
