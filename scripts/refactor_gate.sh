#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/refactor_gate.sh [--skip-pytest] [--skip-gateway] [--wheel]

Run the standard OpenSquilla refactor quality gate.

Options:
  --skip-pytest    Skip the full pytest run.
  --skip-gateway   Skip the gateway start/status/stop/status smoke.
  --wheel          Also run uv build --wheel for PR/release readiness.
  --help           Show this help.
USAGE
}

skip_pytest=0
skip_gateway=0
run_wheel=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-pytest)
      skip_pytest=1
      shift
      ;;
    --skip-gateway)
      skip_gateway=1
      shift
      ;;
    --wheel)
      run_wheel=1
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

echo "== ruff =="
uv run --extra dev ruff check src tests

echo
echo "== mypy =="
uv run --extra dev mypy src/opensquilla --show-error-codes

echo
echo "== whitespace =="
git diff --check

if [[ "$skip_pytest" -eq 0 ]]; then
  echo
  echo "== pytest =="
  uv run --extra dev pytest
else
  echo
  echo "== pytest skipped =="
fi

if [[ "$skip_gateway" -eq 0 ]]; then
  echo
  echo "== gateway smoke =="
  tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/opensquilla-smoke.XXXXXX")"
  port="$(
    python - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
  )"
  export OPENSQUILLA_STATE_DIR="$tmp_root/state"
  export OPENSQUILLA_GATEWAY_WORKSPACE_DIR="$tmp_root/workspace"
  mkdir -p "$OPENSQUILLA_STATE_DIR" "$OPENSQUILLA_GATEWAY_WORKSPACE_DIR"
  cleanup() {
    uv run opensquilla gateway stop --listen 127.0.0.1 --port "$port" --timeout 10 --json >/dev/null 2>&1 || true
  }
  trap cleanup EXIT
  printf 'PORT=%s\nSTATE=%s\nWORKSPACE=%s\n' "$port" "$OPENSQUILLA_STATE_DIR" "$OPENSQUILLA_GATEWAY_WORKSPACE_DIR"
  uv run opensquilla gateway start --listen 127.0.0.1 --port "$port" --timeout 60 --json
  uv run opensquilla gateway status --listen 127.0.0.1 --port "$port" --json
  uv run opensquilla gateway stop --listen 127.0.0.1 --port "$port" --timeout 10 --json
  uv run opensquilla gateway status --listen 127.0.0.1 --port "$port" --json
  trap - EXIT
else
  echo
  echo "== gateway smoke skipped =="
fi

if [[ "$run_wheel" -eq 1 ]]; then
  echo
  echo "== wheel =="
  uv build --wheel
fi

echo
echo "Refactor gate complete."
