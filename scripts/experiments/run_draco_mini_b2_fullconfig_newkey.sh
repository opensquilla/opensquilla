#!/usr/bin/env bash
set -euo pipefail

umask 077

REPO="/home/codex/code/opensquilla-agentic-routing"
INPUT="/home/codex/code/opensquilla/data/draco/mini.jsonl"
CONFIG="/home/codex/code/opensquilla/.local-state/config.toml"
EXPERIMENT_CONFIG="$REPO/configs/benchmarks/draco_b2_g12.json"
OPENROUTER_SECRET_FILE="${OPENSQUILLA_OPENROUTER_SECRET_FILE:-/home/codex/.config/opensquilla/secrets/openrouter.key}"
BRAVE_ENV_FILE="${OPENSQUILLA_BRAVE_ENV_FILE:-/home/codex/code/opensquilla/.local-state/brave.env}"
OUTPUT_DIR="${1:-$REPO/reports/draco/draco-mini-b2-fullconfig-newkey-$(date +%Y%m%d-%H%M%S)}"

validate_secret_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "$path" ]]; then
    echo "Missing $label credential file: $path" >&2
    exit 2
  fi
  local mode
  mode="$(stat -c '%a' "$path")"
  if [[ "$mode" != "600" && "$mode" != "400" ]]; then
    echo "Unsafe $label credential permissions ($mode); expected 600 or 400" >&2
    exit 2
  fi
}

validate_secret_file "$OPENROUTER_SECRET_FILE" "OpenRouter"
validate_secret_file "$BRAVE_ENV_FILE" "Brave"

IFS= read -r OPENROUTER_API_KEY < "$OPENROUTER_SECRET_FILE"
if [[ -z "$OPENROUTER_API_KEY" ]]; then
  echo "OpenRouter credential file is empty" >&2
  exit 2
fi
export OPENROUTER_API_KEY

set -a
# shellcheck disable=SC1090
source "$BRAVE_ENV_FILE"
set +a
if [[ -z "${BRAVE_SEARCH_API_KEY:-}" ]]; then
  echo "BRAVE_SEARCH_API_KEY is missing from $BRAVE_ENV_FILE" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
cd "$REPO"
export PYTHONPATH=src

extra_args=()
if [[ "${DRACO_DRY_RUN:-0}" == "1" ]]; then
  extra_args+=(--dry-run)
fi

exec .venv/bin/python scripts/run_draco_routing_experiment.py \
  --input "$INPUT" \
  --config "$CONFIG" \
  --experiment-config "$EXPERIMENT_CONFIG" \
  --output-dir "$OUTPUT_DIR" \
  --groups B2 \
  --max-tasks 0 \
  --concurrency 5 \
  --timeout 3600 \
  --runner-mode agent_loop \
  --agent-max-iterations 12 \
  --judge-model google/gemini-3.1-pro-preview \
  --judge-repeats 3 \
  --judge-concurrency 6 \
  --judge-max-attempts 3 \
  --generation-max-attempts 3 \
  --generation-max-tokens 16384 \
  --generation-retry-backoff 2 \
  --tool-mode local_web_tools \
  --local-web-search-provider brave \
  --local-web-search-api-key-env BRAVE_SEARCH_API_KEY \
  --contamination-blocked-domains hf.co,huggingface.co,datasets-server.huggingface.co,github.com,raw.githubusercontent.com,openrouter.ai,perplexity.ai,research.perplexity.ai \
  --experiment-config-set benchmark_input.enforce_reference_input=false \
  --experiment-config-set runner.concurrency=5 \
  --experiment-config-set judge.concurrency=6 \
  "${extra_args[@]}"
