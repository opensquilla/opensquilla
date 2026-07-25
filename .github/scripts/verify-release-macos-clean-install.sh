#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: $0 CANDIDATE_DMG LABEL" >&2
  exit 2
fi

candidate_dmg="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
label="$2"
if [[ ! "${label}" =~ ^[A-Za-z0-9._-]{1,80}$ ]]; then
  echo "label must contain only ASCII letters, digits, dot, underscore, or dash" >&2
  exit 2
fi
test -f "${candidate_dmg}"

sandbox="${RUNNER_TEMP}/opensquilla-release-clean-${label}"
mount="${sandbox}/candidate-mount"
install_root="${sandbox}/Applications"
isolated_home="${sandbox}/home"
user_data="${isolated_home}/Library/Application Support/@opensquilla/desktop-electron"
profile="${user_data}/opensquilla"
probe="${GITHUB_WORKSPACE}/.github/scripts/verify-release-profile-preservation.py"
client_probe="${GITHUB_WORKSPACE}/.github/scripts/verify-release-desktop-client.mjs"
marker="CLEAN_INSTALL_SESSION_${label}"
mkdir -p "${mount}" "${install_root}" "${isolated_home}"

cleanup() {
  hdiutil detach "${mount}" -quiet >/dev/null 2>&1 || true
}
trap cleanup EXIT

hdiutil attach -nobrowse -readonly -mountpoint "${mount}" "${candidate_dmg}"
test ! -e "${install_root}/OpenSquilla.app"
ditto "${mount}/OpenSquilla.app" "${install_root}/OpenSquilla.app"
hdiutil detach "${mount}" -quiet

app_binary="${install_root}/OpenSquilla.app/Contents/MacOS/OpenSquilla"
test -x "${app_binary}"
HOME="${isolated_home}" USERPROFILE="${isolated_home}" node "${client_probe}" \
  --executable "${app_binary}" \
  --user-data-dir "${user_data}" \
  --profile-home "${profile}" \
  --probe "${probe}" \
  --label "${label}" \
  --mode clean \
  --use-default-user-data

python - "${install_root}/OpenSquilla.app" <<'PY'
import shutil
import sys

shutil.rmtree(sys.argv[1])
PY
test ! -e "${install_root}/OpenSquilla.app"

python "${probe}" snapshot \
  --home "${profile}" \
  --label "${label}" \
  --new-marker "${marker}" \
  --skip-retained-verification >"${sandbox}/post-uninstall.json"
python - "${sandbox}/post-uninstall.json" <<'PY'
import json
from pathlib import Path
import sys

snapshot = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert snapshot["new_marker_count"] == 1, snapshot
assert len(snapshot["new_marker_session_keys"]) == 1, snapshot
PY
