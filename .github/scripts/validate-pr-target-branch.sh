#!/usr/bin/env bash
set -euo pipefail

base_ref="${PR_BASE_REF:-${BASE_REF:-${BASE:-}}}"
event_path="${GITHUB_EVENT_PATH:-}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
classifier="${script_dir}/classify-ci-changes.sh"
temp_files=()
trap 'rm -f "${temp_files[@]}"' EXIT

changed_files_path=""

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

set_pr_changed_files_path() {
  if [[ -n "${PR_CHANGED_FILES_PATH:-}" ]]; then
    if [[ -f "${PR_CHANGED_FILES_PATH}" ]]; then
      changed_files_path="${PR_CHANGED_FILES_PATH}"
      return 0
    fi
    echo "::error title=Missing PR files::PR_CHANGED_FILES_PATH does not exist." >&2
    return 1
  fi

  if [[ -z "${GITHUB_REPOSITORY:-}" || -z "${PR_NUMBER:-}" ]]; then
    return 1
  fi

  if ! command -v gh >/dev/null 2>&1; then
    echo "::error title=Missing GitHub CLI::gh is required to inspect pull request files." >&2
    return 1
  fi

  local changed_files
  changed_files="$(mktemp)"
  temp_files+=("${changed_files}")

  if ! gh api --paginate "repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}/files" --jq '.[].filename' > "${changed_files}"; then
    echo "::error title=Unable to inspect PR files::Could not read changed files for pull request ${PR_NUMBER}." >&2
    return 1
  fi

  changed_files_path="${changed_files}"
}

event_label_names() {
  if [[ -n "${PR_LABELS:-}" ]]; then
    tr ',' '\n' <<< "${PR_LABELS}"
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

main_docs_only=false
if [[ "${base_ref}" == "main" ]]; then
  if set_pr_changed_files_path; then
    classifier_output="$(mktemp)"
    temp_files+=("${classifier_output}")
    GITHUB_OUTPUT="${classifier_output}" bash "${classifier}" "${changed_files_path}"
    if grep -qx "docs_only=true" "${classifier_output}"; then
      main_docs_only=true
    fi
  fi
fi

main_allowed_by_label=false
if [[ "${base_ref}" == "main" && -n "${event_path}" && -f "${event_path}" ]]; then
  while IFS= read -r label; do
    case "${label}" in
      allow-main-target | release | hotfix | sync-to-main | docs-preview)
        main_allowed_by_label=true
        break
        ;;
    esac
  done < <(event_label_names)
fi

if [[ "${main_docs_only}" == "true" ]]; then
  echo "Pull request targets main with documentation-only changes."
  exit 0
fi

if [[ "${main_allowed_by_label}" == "true" ]]; then
  echo "Pull request targets main with maintainer approval label."
  exit 0
fi

{
  echo "::error title=Wrong PR target::Ordinary pull requests should target dev."
  echo "Use main only for documentation-only changes or maintainer-approved release, hotfix, sync, or documentation-preview work."
  echo "Retarget this pull request to dev, or ask a maintainer to add allow-main-target."
} >&2
exit 1
