#!/usr/bin/env bash
set -euo pipefail

umask 077

echo "This legacy retry supervisor is disabled: it cannot provide whole-window cost reconciliation." >&2
echo "Use a new accounted launcher instead of resuming historical shards." >&2
exit 2

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo="${DRACO_REPO:-$(cd "$script_dir/.." && pwd)}"
gateway_config="${DRACO_GATEWAY_CONFIG:-$(dirname "$repo")/opensquilla/.local-state/config.toml}"
out="${DRACO_OUTPUT_DIR:?DRACO_OUTPUT_DIR is required; legacy batches are incompatible}"
input="${DRACO_INPUT:?DRACO_INPUT is required}"
original="${DRACO_ORIGINAL_RESULT:?DRACO_ORIGINAL_RESULT is required}"
resume="${DRACO_RESUME_RESULT:?DRACO_RESUME_RESULT is required}"
expected_manifest="${DRACO_EXPECTED_MANIFEST:?DRACO_EXPECTED_MANIFEST is required}"
main_pid="${DRACO_MAIN_PID:?DRACO_MAIN_PID is required}"
max_wait_seconds="${DRACO_MAX_WAIT_SECONDS:-86400}"

if [[ ! -f "$expected_manifest" ]] || ! jq -e '
  . as $manifest
  | .run_compatibility.schema == "opensquilla.draco.run-compatibility/v1"
  and (["B0", "B1", "B2", "B3", "B4", "G1"]
       | all(. as $group | ($manifest.run_compatibility.fingerprints[$group] | type == "string")))
' "$expected_manifest" >/dev/null; then
  echo "DRACO_EXPECTED_MANIFEST is missing or lacks current compatibility fingerprints" >&2
  exit 2
fi

# shellcheck source=lib/load_draco_benchmark_credentials.sh
source "$repo/scripts/lib/load_draco_benchmark_credentials.sh"
load_draco_benchmark_credentials

waited=0
while kill -0 "$main_pid" 2>/dev/null; do
  cmdline="$(tr '\0' ' ' < "/proc/$main_pid/cmdline" 2>/dev/null || true)"
  if [[ "$cmdline" != *"run_draco_routing_experiment"* || "$cmdline" != *"$out"* ]]; then
    echo "PID $main_pid does not match the expected DRACO output directory" >&2
    exit 2
  fi
  if (( waited >= max_wait_seconds )); then
    echo "Timed out waiting for DRACO PID $main_pid after ${max_wait_seconds}s" >&2
    exit 2
  fi
  sleep 10
  waited=$((waited + 10))
done

cd "$repo"
set +e
.venv/bin/python scripts/audit_draco_results.py \
  --input "$input" \
  --result "$original" \
  --result "$resume" \
  --output-dir "$out" \
  --prefix main_complete \
  --expected-manifest "$expected_manifest"
audit_status=$?
set -e
if [[ "$audit_status" -ne 0 && "$audit_status" -ne 2 ]]; then
  echo "main audit failed with status $audit_status" >&2
  exit "$audit_status"
fi

retry_keys="$out/main_complete.retry_keys.jsonl"
retry_count=$(wc -l < "$retry_keys")
echo "retry wave 1: scheduled $retry_count strict-invalid group/task pairs"
if [[ "$retry_count" -eq 0 ]]; then
  exit 0
fi

exec .venv/bin/python scripts/run_draco_routing_experiment_resume.py \
  --input "$input" \
  --only-group-task-keys "$retry_keys" \
  --expected-compatibility-manifest "$expected_manifest" \
  --config "$gateway_config" \
  --output-dir "$out" \
  --groups B0,B1,B2,B3,B4,G1 \
  --max-tasks 0 \
  --concurrency 5 \
  --timeout 3600 \
  --runner-mode agent_loop \
  --agent-max-iterations 12 \
  --require-clean-source \
  --judge-model google/gemini-3.1-pro-preview \
  --judge-repeats 3 \
  --judge-concurrency 6 \
  --judge-max-attempts 3 \
  --generation-max-attempts 3 \
  --generation-max-tokens 16384 \
  --generation-retry-backoff 2 \
  --tool-mode local_web_tools \
  --require-openrouter-non-byok \
  --local-web-search-provider brave \
  --local-web-search-api-key-env BRAVE_SEARCH_API_KEY \
  --contamination-blocked-domains hf.co,huggingface.co,datasets-server.huggingface.co,github.com,raw.githubusercontent.com,openrouter.ai,perplexity.ai,research.perplexity.ai \
  --experiment-config-set benchmark_input.enforce_reference_input=false \
  --experiment-config-set runner.concurrency=5
