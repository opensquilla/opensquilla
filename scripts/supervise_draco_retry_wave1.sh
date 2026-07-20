#!/usr/bin/env bash
set -euo pipefail

repo=/home/codex/code/opensquilla-agentic-routing
out="$repo/reports/draco/routing-full-b0-b1-b2-b3-b4-g1-lowconcurrency-20260716-004728"
input=/home/codex/code/opensquilla/data/draco/test.jsonl
original="$out/draco_ensemble_20260716-004848.jsonl"
resume="$out/draco_ensemble_20260717-124519.jsonl"
main_pid=4097848

while kill -0 "$main_pid" 2>/dev/null; do
  sleep 10
done

cd "$repo"
set +e
.venv/bin/python scripts/audit_draco_results.py \
  --input "$input" \
  --result "$original" \
  --result "$resume" \
  --output-dir "$out" \
  --prefix main_complete
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
