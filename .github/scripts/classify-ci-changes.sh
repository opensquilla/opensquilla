#!/usr/bin/env bash
set -euo pipefail

changed_files="${1:?usage: classify-ci-changes.sh <changed-files-list>}"
output_file="${GITHUB_OUTPUT:?GITHUB_OUTPUT must be set}"

docs_only=true
runtime_changed=false
test_changed=false
ci_changed=false
dependency_changed=false
release_changed=false
seen_file=false

mark_runtime_changed() {
  docs_only=false
  runtime_changed=true
}

mark_test_changed() {
  docs_only=false
  test_changed=true
}

mark_ci_changed() {
  docs_only=false
  ci_changed=true
}

mark_dependency_changed() {
  mark_runtime_changed
  dependency_changed=true
  release_changed=true
}

mark_release_changed() {
  docs_only=false
  release_changed=true
}

while IFS= read -r path || [[ -n "${path}" ]]; do
  path="${path%$'\r'}"
  [[ -z "${path}" ]] && continue
  seen_file=true

  case "${path}" in
    .ci/run-all)
      docs_only=false
      runtime_changed=true
      test_changed=true
      ci_changed=true
      dependency_changed=true
      release_changed=true
      ;;
    pyproject.toml | uv.lock)
      mark_dependency_changed
      ;;
    .github/workflows/wheelhouse-release.yml)
      mark_ci_changed
      mark_release_changed
      ;;
    .github/workflows/*)
      mark_ci_changed
      ;;
    .github/scripts/*)
      mark_ci_changed
      ;;
    tests/test_scripts/test_build_wheelhouse_zip.py | tests/test_install_scripts.py | tests/test_root_start_scripts.py | tests/test_release_consistency.py | tests/test_public_release_hygiene.py)
      mark_test_changed
      mark_release_changed
      ;;
    tests/*)
      mark_test_changed
      ;;
    scripts/build_wheelhouse_zip.py | scripts/install_source.sh | scripts/install_source.ps1)
      mark_runtime_changed
      mark_release_changed
      ;;
    install.sh | install.ps1 | start.sh | start.ps1 | README.release.md | RELEASES.md)
      mark_release_changed
      ;;
    src/* | scripts/* | migrations/*)
      mark_runtime_changed
      ;;
    docs/* | README.md | README.*.md | CHANGELOG.md | CODE_OF_CONDUCT.md | CONTRIBUTING.md | MIGRATION.md | SECURITY.md | SUPPORT.md | THIRD_PARTY_NOTICES.md | META_SKILL_GUIDE.md | .github/pull_request_template.md | .github/ISSUE_TEMPLATE/*)
      ;;
    *)
      mark_runtime_changed
      ;;
  esac
done < "${changed_files}"

if [[ "${seen_file}" == "false" ]]; then
  docs_only=false
  runtime_changed=true
  test_changed=true
  ci_changed=true
  dependency_changed=true
  release_changed=true
fi

{
  printf 'docs_only=%s\n' "${docs_only}"
  printf 'runtime_changed=%s\n' "${runtime_changed}"
  printf 'test_changed=%s\n' "${test_changed}"
  printf 'ci_changed=%s\n' "${ci_changed}"
  printf 'dependency_changed=%s\n' "${dependency_changed}"
  printf 'release_changed=%s\n' "${release_changed}"
} >> "${output_file}"
