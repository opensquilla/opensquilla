#!/usr/bin/env bash
set -euo pipefail

umask 077

REPO="/home/codex/code/opensquilla-agentic-routing"
INPUT="/home/codex/code/opensquilla/data/draco/mini.jsonl"
CONFIG="/home/codex/code/opensquilla/.local-state/config.toml"
SECRET_FILE="${OPENSQUILLA_OPENROUTER_SECRET_FILE:-/home/codex/.config/opensquilla/secrets/openrouter.key}"
OUTPUT_DIR="${1:-$REPO/reports/draco/draco-mini-b2-nonbyok-cost-audit-$(date +%Y%m%d-%H%M%S)}"

if [[ ! -f "$SECRET_FILE" ]]; then
  echo "Missing OpenRouter credential file: $SECRET_FILE" >&2
  exit 2
fi

mode="$(stat -c '%a' "$SECRET_FILE")"
if [[ "$mode" != "600" && "$mode" != "400" ]]; then
  echo "Unsafe credential permissions ($mode); expected 600 or 400" >&2
  exit 2
fi

IFS= read -r OPENROUTER_API_KEY < "$SECRET_FILE"
if [[ -z "$OPENROUTER_API_KEY" ]]; then
  echo "OpenRouter credential file is empty" >&2
  exit 2
fi
export OPENROUTER_API_KEY

mkdir -p "$OUTPUT_DIR"
cd "$REPO"
export PYTHONPATH=src

exec .venv/bin/python scripts/run_draco_routing_experiment.py \
  --input "$INPUT" \
  --config "$CONFIG" \
  --output-dir "$OUTPUT_DIR" \
  --groups B2 \
  --concurrency 5 \
  --timeout 3600 \
  --runner-mode agent_loop \
  --agent-max-iterations 1 \
  --judge-model google/gemini-3.1-pro-preview \
  --judge-repeats 1 \
  --judge-concurrency 3 \
  --judge-max-attempts 3 \
  --generation-max-attempts 3 \
  --generation-retry-backoff 2 \
  --tool-mode provider_only \
  --experiment-config-set runner.concurrency=5 \
  --experiment-config-set runner.agent_max_iterations=1 \
  --experiment-config-set judge.repeats=1 \
  --experiment-config-set judge.concurrency=3 \
  --experiment-config-set 'tools.mode="provider_only"'
