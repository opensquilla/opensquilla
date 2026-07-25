#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 5 ]]; then
  echo "usage: $0 CANDIDATE_DMG LABEL OLD_TAG OLD_ASSET LAYOUT [--verify-config-reset] [--verify-cli-import] [--verify-inspect-failure]" >&2
  exit 2
fi

candidate_dmg="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
label="$2"
old_tag="$3"
old_asset="$4"
layout="$5"
shift 5
verify_config_reset=0
verify_cli_import=0
verify_inspect_failure=0
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --verify-config-reset) verify_config_reset=1 ;;
    --verify-cli-import) verify_cli_import=1 ;;
    --verify-inspect-failure) verify_inspect_failure=1 ;;
    *)
      echo "unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done
if [[ ! "${label}" =~ ^[A-Za-z0-9._-]{1,80}$ ]]; then
  echo "label must contain only ASCII letters, digits, dot, underscore, or dash" >&2
  exit 2
fi
if [[ ! "${old_tag}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(rc[0-9]+)?$ ]]; then
  echo "old tag must be a released vX.Y.Z or vX.Y.ZrcN tag" >&2
  exit 2
fi
if [[ ! "${old_asset}" =~ ^OpenSquilla-[A-Za-z0-9.-]+-mac-arm64\.dmg$ ]]; then
  echo "old asset is not a canonical macOS Desktop DMG name" >&2
  exit 2
fi
if [[ "${layout}" != "pre-rc3" && "${layout}" != "modern" ]]; then
  echo "layout must be pre-rc3 or modern" >&2
  exit 2
fi

sandbox="${RUNNER_TEMP}/opensquilla-release-preservation-${label}"
old_dir="${sandbox}/old"
old_mount="${sandbox}/old-mount"
candidate_mount="${sandbox}/candidate-mount"
install_root="${sandbox}/Applications"
isolated_home="${sandbox}/home"
user_data="${isolated_home}/Library/Application Support/@opensquilla/desktop-electron"
profile="${user_data}/opensquilla"
probe="${GITHUB_WORKSPACE}/.github/scripts/verify-release-profile-preservation.py"
client_probe="${GITHUB_WORKSPACE}/.github/scripts/verify-release-desktop-client.mjs"
released_session_seed="${GITHUB_WORKSPACE}/.github/scripts/seed-released-desktop-session.mjs"
retained_marker="HISTORICAL_RELEASE_SESSION_${label}"
mkdir -p \
  "${old_dir}" \
  "${old_mount}" \
  "${candidate_mount}" \
  "${install_root}" \
  "${user_data}" \
  "${isolated_home}"

cleanup() {
  hdiutil detach "${candidate_mount}" -quiet >/dev/null 2>&1 || true
  hdiutil detach "${old_mount}" -quiet >/dev/null 2>&1 || true
  if [[ -n "${app_pid:-}" ]]; then
    kill "${app_pid}" >/dev/null 2>&1 || true
    wait "${app_pid}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

gh release download "${old_tag}" \
  --repo opensquilla/opensquilla \
  --pattern "${old_asset}" \
  --dir "${old_dir}"
old_dmg="${old_dir}/${old_asset}"
test -f "${old_dmg}"
test -f "${candidate_dmg}"

hdiutil attach -nobrowse -readonly -mountpoint "${old_mount}" "${old_dmg}"
ditto "${old_mount}/OpenSquilla.app" "${install_root}/OpenSquilla.app"
hdiutil detach "${old_mount}" -quiet

python "${probe}" seed \
  --home "${profile}" \
  --label "${label}" \
  --layout "${layout}" \
  --source-tag "${old_tag}" \
  --profile-only

old_gateway_binary="$(find \
  "${install_root}/OpenSquilla.app/Contents/Resources/runtime/gateway" \
  -type f -name opensquilla-gateway -perm -111 -print -quit)"
test -x "${old_gateway_binary}"
node "${released_session_seed}" \
  --gateway "${old_gateway_binary}" \
  --profile-home "${profile}" \
  --layout "${layout}" \
  --label "${label}"
python "${probe}" verify \
  --home "${profile}" \
  --label "${label}" \
  --retained-marker "${retained_marker}"

hdiutil attach -nobrowse -readonly -mountpoint "${candidate_mount}" "${candidate_dmg}"
mv "${install_root}/OpenSquilla.app" "${install_root}/OpenSquilla.old.app"
ditto "${candidate_mount}/OpenSquilla.app" "${install_root}/OpenSquilla.app"
hdiutil detach "${candidate_mount}" -quiet
python "${probe}" verify \
  --home "${profile}" \
  --label "${label}" \
  --retained-marker "${retained_marker}"

app_binary="${install_root}/OpenSquilla.app/Contents/MacOS/OpenSquilla"
test -x "${app_binary}"
if [[ "${verify_inspect_failure}" == "1" ]]; then
  HOME="${isolated_home}" USERPROFILE="${isolated_home}" node "${client_probe}" \
    --executable "${app_binary}" \
    --user-data-dir "${user_data}" \
    --profile-home "${profile}" \
    --probe "${probe}" \
    --label "${label}" \
    --mode upgrade \
    --use-default-user-data \
    --force-inspect-failure \
    --retained-marker "${retained_marker}"
fi

HOME="${isolated_home}" USERPROFILE="${isolated_home}" node "${client_probe}" \
  --executable "${app_binary}" \
  --user-data-dir "${user_data}" \
  --profile-home "${profile}" \
  --probe "${probe}" \
  --label "${label}" \
  --mode upgrade \
  --use-default-user-data \
  --retained-marker "${retained_marker}"

gateway_binary="$(find \
  "${install_root}/OpenSquilla.app/Contents/Resources/runtime/gateway" \
  -type f -name opensquilla-gateway -perm -111 -print -quit)"
test -x "${gateway_binary}"
OPENSQUILLA_RECOVERY_OFFLINE=1 "${gateway_binary}" recovery inspect \
  --home "${profile}" --json >"${sandbox}/candidate-inspect.json"
python - "${profile}" "${sandbox}/candidate-inspect.json" <<'PY'
import json
from pathlib import Path
import sys

home = Path(sys.argv[1]).resolve()
report = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert report["outcome"] in {"ready", "attention"}, report
assert Path(report["primary_home"]).resolve() == home, report
assert Path(report["effective_workspace"]).resolve() == home / "workspace", report
configured_state = [
    candidate
    for candidate in report["candidates"]
    if candidate["kind"] == "state" and candidate["configured"] and candidate["valid"]
]
assert len(configured_state) == 1, report
assert Path(configured_state[0]["path"]).resolve() == home / "state", report
PY
python "${probe}" verify \
  --home "${profile}" \
  --label "${label}" \
  --retained-marker "${retained_marker}"

if [[ "${verify_config_reset}" == "1" ]]; then
  reset_label="${label}-config-reset"
  reset_user_data="${sandbox}/config-reset-user-data/OpenSquilla"
  reset_profile="${reset_user_data}/opensquilla"
  python "${probe}" seed \
    --home "${reset_profile}" \
    --label "${reset_label}" \
    --layout modern \
    --source-tag v0.5.0
  python - "${reset_profile}/config.toml" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).write_text("state_dir = [\n", encoding="utf-8")
PY
  node "${client_probe}" \
    --executable "${app_binary}" \
    --user-data-dir "${reset_user_data}" \
    --profile-home "${reset_profile}" \
    --probe "${probe}" \
    --label "${reset_label}" \
    --mode upgrade \
    --allow-config-change
  python "${probe}" verify \
    --home "${reset_profile}" \
    --label "${reset_label}" \
    --allow-config-change
fi

if [[ "${verify_cli_import}" == "1" ]]; then
  cli_label="${label}-cli031"
  cli_source="${sandbox}/cli-home/.opensquilla"
  cli_user_data="${sandbox}/cli-import-user-data/OpenSquilla"
  cli_target="${cli_user_data}/opensquilla"
  mkdir -p "${cli_user_data}" "${sandbox}/cli-lock-root"
  python "${probe}" seed \
    --home "${cli_source}" \
    --label "${cli_label}" \
    --layout modern \
    --source-tag v0.3.1
  OPENSQUILLA_STATE_DIR="${cli_target}" \
    OPENSQUILLA_GATEWAY_CONFIG_PATH="${cli_target}/config.toml" \
    OPENSQUILLA_RECOVERY_OFFLINE=1 \
    OPENSQUILLA_TEST_PROFILE_LOCK_ROOT=1 \
    OPENSQUILLA_USER_STATE_DIR="${sandbox}/cli-lock-root" \
    "${gateway_binary}" migrate opensquilla \
      --source "${cli_source}" \
      --kind cli-home \
      --apply \
      --json >"${sandbox}/cli-import.json"
  python - "${sandbox}/cli-import.json" <<'PY'
import json
from pathlib import Path
import sys

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert report["apply"] is True, report
assert not [item for item in report["items"] if item["status"] == "error"], report
assert report["preflight"]["session_count"] == 1, report
PY
  node "${client_probe}" \
    --executable "${app_binary}" \
    --user-data-dir "${cli_user_data}" \
    --profile-home "${cli_target}" \
    --probe "${probe}" \
    --label "${cli_label}" \
    --mode upgrade \
    --allow-config-change
  python "${probe}" verify \
    --home "${cli_target}" \
    --label "${cli_label}" \
    --allow-config-change
  python "${probe}" verify --home "${cli_source}" --label "${cli_label}"
fi

python - "${install_root}/OpenSquilla.app" "${install_root}/OpenSquilla.old.app" <<'PY'
import shutil
import sys

for app_path in sys.argv[1:]:
    shutil.rmtree(app_path)
PY
test ! -e "${install_root}/OpenSquilla.app"
test ! -e "${install_root}/OpenSquilla.old.app"
python "${probe}" verify \
  --home "${profile}" \
  --label "${label}" \
  --retained-marker "${retained_marker}"
