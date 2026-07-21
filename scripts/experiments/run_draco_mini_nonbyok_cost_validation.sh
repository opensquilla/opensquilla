#!/usr/bin/env bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${OPENSQUILLA_REPO:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

echo "Delegating to the strict B2 launcher with canary and account reconciliation." >&2
exec "$REPO/scripts/experiments/run_draco_mini_b2_fullconfig_newkey.sh" "$@"
