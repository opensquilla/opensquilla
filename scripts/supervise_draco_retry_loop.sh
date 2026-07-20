#!/usr/bin/env bash
set -euo pipefail

repo=/home/codex/code/opensquilla-agentic-routing
out="$repo/reports/draco/routing-full-b0-b1-b2-b3-b4-g1-lowconcurrency-20260716-004728"
input=/home/codex/code/opensquilla/data/draco/test.jsonl
current_pid=${DRACO_CURRENT_PID:-4140152}
current_manifest=${DRACO_CURRENT_MANIFEST:-"$out/draco_run_20260717-150041.manifest.json"}
completed_wave=${DRACO_COMPLETED_WAVE:-1}
max_waves=${DRACO_MAX_WAVES:-20}

while kill -0 "$current_pid" 2>/dev/null; do
  sleep 30
done

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
    --config /home/codex/code/opensquilla/.local-state/config.toml \
    --output-dir "$out" \
    --groups B0,B1,B2,B3,B4,G1 \
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
    --experiment-config-set runner.concurrency=5
  run_status=$?
  set -e
  if [[ "$run_status" -ne 0 ]]; then
    echo "retry wave $next_wave failed with status $run_status" >&2
    exit "$run_status"
  fi
  completed_wave=$next_wave
done
