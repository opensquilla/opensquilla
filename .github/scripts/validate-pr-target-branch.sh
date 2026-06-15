#!/usr/bin/env bash
set -euo pipefail

base_ref="${PR_BASE_REF:-${BASE_REF:-${BASE:-}}}"
event_path="${GITHUB_EVENT_PATH:-}"

if [[ -z "${base_ref}" ]]; then
  {
    echo "::error title=Missing PR target::PR_BASE_REF is required."
    echo "Unable to validate the pull request target branch."
  } >&2
  exit 1
fi

if [[ "${base_ref}" == "dev" ]]; then
  echo "Pull request targets dev."
  exit 0
fi

event_label_names() {
  if [[ -n "${PR_LABELS:-}" ]]; then
    tr ',' '\n' <<< "${PR_LABELS}"
    return
  fi

  if [[ -z "${event_path}" || ! -f "${event_path}" ]]; then
    return
  fi

  local python_bin=""
  if command -v python3 >/dev/null 2>&1; then
    python_bin="python3"
  elif command -v python >/dev/null 2>&1; then
    python_bin="python"
  fi

  if [[ -n "${python_bin}" ]]; then
    "${python_bin}" - "${event_path}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as event_file:
    event = json.load(event_file)

for label in event.get("pull_request", {}).get("labels", []):
    name = label.get("name")
    if name:
        print(name)
PY
    return
  fi

  if command -v jq >/dev/null 2>&1; then
    jq -r '.pull_request.labels[]?.name // empty' "${event_path}"
  fi
}

has_allowed_label() {
  local allowed_kind="${1:?allowed kind is required}"
  local label

  while IFS= read -r label; do
    case "${allowed_kind}:${label}" in
      main:allow-main-target | main:release | main:hotfix | main:main-sync | main:release-docs | main:sync-to-main | main:docs-preview)
        return 0
        ;;
      staging:maintainer-staging | staging:collaboration)
        return 0
        ;;
    esac
  done < <(event_label_names)

  return 1
}

is_staging_branch() {
  case "${base_ref}" in
    sandbox-* | integration/* | staging/* | release/*)
      return 0
      ;;
  esac

  return 1
}

if [[ "${base_ref}" == "main" ]] && has_allowed_label main; then
  echo "Pull request targets main with maintainer approval label."
  exit 0
fi

if is_staging_branch || has_allowed_label staging; then
  echo "Pull request targets a staging/collaboration branch."
  echo "This is not a final integration path; final integration should target dev, while release or hotfix work should target main with an approval label."
  exit 0
fi

{
  echo "::error title=Wrong PR target::Ordinary pull requests should target dev."
  echo "Use main only for maintainer-approved release, hotfix, release-docs, or main-sync work."
  echo "Use sandbox-*, integration/*, staging/*, release/*, or a maintainer-staging/collaboration label for maintainer collaboration PRs."
  echo "Retarget this pull request to dev, or ask a maintainer to add an explicit exception label."
} >&2
exit 1
