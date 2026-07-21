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
current_pid="${DRACO_CURRENT_PID:?DRACO_CURRENT_PID is required}"
current_manifest="${DRACO_CURRENT_MANIFEST:?DRACO_CURRENT_MANIFEST is required}"
expected_manifest="${DRACO_EXPECTED_MANIFEST:?DRACO_EXPECTED_MANIFEST is required}"
completed_wave="${DRACO_COMPLETED_WAVE:-1}"
max_waves="${DRACO_MAX_WAVES:-20}"
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
while kill -0 "$current_pid" 2>/dev/null; do
  cmdline="$(tr '\0' ' ' < "/proc/$current_pid/cmdline" 2>/dev/null || true)"
  if [[ "$cmdline" != *"run_draco_routing_experiment"* || "$cmdline" != *"$out"* ]]; then
    echo "PID $current_pid does not match the expected DRACO output directory" >&2
    exit 2
  fi
  if (( waited >= max_wait_seconds )); then
    echo "Timed out waiting for DRACO PID $current_pid after ${max_wait_seconds}s" >&2
    exit 2
  fi
  sleep 30
  waited=$((waited + 30))
done

if [[ ! -f "$current_manifest" ]]; then
  echo "retry manifest does not exist: $current_manifest" >&2
  exit 1
fi
if [[ $(jq -r '.status // ""' "$current_manifest") != complete ]]; then
  echo "retry wave 1 exited without a complete manifest" >&2
  exit 1
fi

cd "$repo"
while [[ "$completed_wave" -le "$max_waves" ]]; do
  prefix="retry_wave_${completed_wave}_audit"
  audit_args=(
    .venv/bin/python scripts/audit_draco_results.py
    --input "$input"
    --output-dir "$out"
    --prefix "$prefix"
    --skip-final
    --expected-manifest "$expected_manifest"
  )
  while IFS= read -r shard; do
    audit_args+=(--result "$shard")
  done < <(find "$out" -maxdepth 1 -type f -name 'draco_ensemble_*.jsonl' | sort)

  set +e
  "${audit_args[@]}"
  audit_status=$?
  set -e
  if [[ "$audit_status" -ne 0 && "$audit_status" -ne 2 ]]; then
    echo "retry wave $completed_wave audit failed with status $audit_status" >&2
    exit "$audit_status"
  fi

  retry_keys="$out/${prefix}.retry_keys.jsonl"
  retry_count=$(wc -l < "$retry_keys")
  echo "retry wave $completed_wave audit: $retry_count strict-invalid pairs remain"
  if [[ "$retry_count" -eq 0 ]]; then
    final_args=(
      .venv/bin/python scripts/audit_draco_results.py
      --input "$input"
      --output-dir "$out"
      --prefix final_audit
      --expected-manifest "$expected_manifest"
    )
    while IFS= read -r shard; do
      final_args+=(--result "$shard")
    done < <(find "$out" -maxdepth 1 -type f -name 'draco_ensemble_*.jsonl' | sort)
    "${final_args[@]}"
    echo "all DRACO group/task pairs are strictly valid"
    exit 0
  fi

  next_wave=$((completed_wave + 1))
  if [[ "$next_wave" -gt "$max_waves" ]]; then
    echo "strict-invalid pairs remain after $max_waves retry waves" >&2
    exit 1
  fi
  echo "retry wave $next_wave: scheduled $retry_count group/task pairs"

  set +e
  .venv/bin/python scripts/run_draco_routing_experiment_resume.py \
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
  run_status=$?
  set -e
  if [[ "$run_status" -ne 0 ]]; then
    echo "retry wave $next_wave failed with status $run_status" >&2
    exit "$run_status"
  fi
  completed_wave=$next_wave
done
