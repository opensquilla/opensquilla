#!/usr/bin/env bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${OPENSQUILLA_REPO:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
REFERENCE_REPO="${OPENSQUILLA_REFERENCE_REPO:-$(dirname "$REPO")/opensquilla}"
INPUT="${DRACO_INPUT:-$REFERENCE_REPO/data/draco/mini.jsonl}"
CONFIG="${DRACO_GATEWAY_CONFIG:-$REFERENCE_REPO/.local-state/config.toml}"
EXPERIMENT_CONFIG="$REPO/configs/benchmarks/draco_b2_g12.json"
CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME:?HOME is required}/.config}"
OPENROUTER_SECRET_FILE="${OPENSQUILLA_OPENROUTER_SECRET_FILE:-$CONFIG_HOME/opensquilla/secrets/openrouter.key}"
BRAVE_ENV_FILE="${OPENSQUILLA_BRAVE_ENV_FILE:-$REFERENCE_REPO/.local-state/brave.env}"
SMOKE_ONLY=0

if [[ "${DRACO_DRY_RUN:-0}" != "0" ]]; then
  echo "This formal wrapper refuses inherited DRACO_DRY_RUN; use the runner CLI explicitly." >&2
  exit 2
fi

if [[ "$#" -gt 1 ]]; then
  echo "Usage: $0 [OUTPUT_DIR|--smoke-only]" >&2
  exit 2
fi
case "${1:-}" in
  "") OUTPUT_DIR="$REPO/reports/draco/draco-mini-b2-fullconfig-newkey-$(date +%Y%m%d-%H%M%S)" ;;
  --smoke-only|--local-web-tools-smoke-only)
    SMOKE_ONLY=1
    OUTPUT_DIR="$REPO/reports/draco/draco-mini-b2-web-smoke"
    ;;
  -*)
    echo "Unknown option: $1" >&2
    echo "Usage: $0 [OUTPUT_DIR|--smoke-only]" >&2
    exit 2
    ;;
  *) OUTPUT_DIR="$1" ;;
esac

if ! jq -e -s '
  length == 10
  and all(.[];
    type == "object"
    and ((.task_id // .id // "") | type == "string" and length > 0)
  )
  and ([.[] | (.task_id // .id)] | unique | length == 10)
' "$INPUT" >/dev/null; then
  echo "DRACO mini input must contain exactly 10 rows with 10 unique task IDs" >&2
  exit 2
fi

# shellcheck source=../lib/load_draco_benchmark_credentials.sh
source "$REPO/scripts/lib/load_draco_benchmark_credentials.sh"
load_draco_benchmark_credentials
# Formal benchmark traffic must reach OpenRouter directly.  Do not let an
# inherited shell environment silently replace the API endpoint or insert a
# proxy that would make provider identity and account reconciliation ambiguous.
unset OPENROUTER_BASE_URL OPENSQUILLA_LLM_PROXY
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
unset OPENSQUILLA_BENCHMARK_CACHE_NAMESPACE
unset OPENSQUILLA_BENCHMARK_CACHE_NAMESPACE_REQUIRED
export OPENSQUILLA_TRUST_ENV=0
export OPENSQUILLA_PROVIDER_ROUTING_STRICT=1
export OPENSQUILLA_PROVIDER_STREAM_ERROR_FRAMES=1
export OPENSQUILLA_OPENROUTER_METADATA_REQUIRED=1
export OPENSQUILLA_OPENROUTER_REQUIRE_PARAMETERS=1
export OPENSQUILLA_OPENROUTER_DISABLE_RESPONSE_CACHE=1

cd "$REPO"
export PYTHONPATH=src

formal_run=1
extra_args=()
if [[ "$SMOKE_ONLY" == "1" ]]; then
  formal_run=0
fi
if [[ "$SMOKE_ONLY" == "1" ]]; then
  extra_args+=(--local-web-tools-smoke-only)
elif [[ "$formal_run" == "1" ]]; then
  if [[ "${DRACO_OPENROUTER_KEY_EXCLUSIVE:-0}" != "1" ]]; then
    echo "Formal cost accounting requires DRACO_OPENROUTER_KEY_EXCLUSIVE=1" >&2
    echo "Use a dedicated OpenRouter key that is not used by any other process or machine." >&2
    exit 2
  fi
  source_paths=(scripts src configs pyproject.toml uv.lock)
  if ! git rev-parse --verify HEAD >/dev/null 2>&1 \
    || ! git diff --quiet HEAD -- "${source_paths[@]}"; then
    echo "Formal benchmark requires committed, unchanged source files" >&2
    exit 2
  fi
  if ! untracked_source="$(
    git ls-files --others --exclude-standard -- "${source_paths[@]}"
  )"; then
    echo "Unable to verify the benchmark source tree" >&2
    exit 2
  fi
  if [[ -n "$untracked_source" ]]; then
    echo "Formal benchmark refuses untracked files under scripts/src/configs" >&2
    exit 2
  fi
  if [[ -e "$OUTPUT_DIR" && ! -d "$OUTPUT_DIR" ]]; then
    echo "Formal output path exists and is not a directory: $OUTPUT_DIR" >&2
    exit 2
  fi
  if [[ -d "$OUTPUT_DIR" ]] && find "$OUTPUT_DIR" -mindepth 1 -print -quit | grep -q .; then
    echo "Formal output directory must be new or empty: $OUTPUT_DIR" >&2
    exit 2
  fi
  mkdir -p "$OUTPUT_DIR"
else
  mkdir -p "$OUTPUT_DIR"
fi

formal_success=0
cleanup_failed_formal_publish() {
  local status=$?
  trap - EXIT
  if [[ "$formal_run" == "1" && "$formal_success" != "1" ]]; then
    rm -f "$OUTPUT_DIR/cost-audit.json" \
      "$OUTPUT_DIR/EXPERIMENT_RESULTS.md" \
      "$OUTPUT_DIR/FORMAL_RUN_SUCCESS.json"
  fi
  exit "$status"
}
restore_formal_exit_trap() {
  trap - EXIT
  if [[ "$formal_run" == "1" ]]; then
    trap cleanup_failed_formal_publish EXIT
  fi
}
if [[ "$formal_run" == "1" ]]; then
  trap cleanup_failed_formal_publish EXIT
fi

benchmark_args=(
  --input "$INPUT"
  --config "$CONFIG"
  --experiment-config "$EXPERIMENT_CONFIG"
  --groups B2
  --timeout 3600
  --runner-mode agent_loop
  --agent-max-iterations 12
  --judge-model google/gemini-3.1-pro-preview
  --judge-repeats 3
  --judge-max-attempts 3
  --generation-max-attempts 3
  --generation-max-tokens 16384
  --generation-retry-backoff 2
  --tool-mode local_web_tools
  --local-web-search-provider brave
  --local-web-search-api-key-env BRAVE_SEARCH_API_KEY
  --contamination-blocked-domains hf.co,huggingface.co,datasets-server.huggingface.co,github.com,raw.githubusercontent.com,openrouter.ai,perplexity.ai,research.perplexity.ai
  --experiment-config-set runner.concurrency=5
  --experiment-config-set judge.concurrency=6
)

capture_account_snapshot() {
  local path="$1"
  shift
  .venv/bin/python scripts/experiments/capture_openrouter_account_usage.py \
    "$path" \
    --secret-file "$OPENROUTER_SECRET_FILE" \
    --expected-key-env OPENROUTER_API_KEY \
    "$@"
}

assert_account_capacity() {
  local snapshot="$1"
  local minimum_remaining="${DRACO_OPENROUTER_MIN_REMAINING_USD:-100}"
  if ! jq -en --arg value "$minimum_remaining" \
    '($value | tonumber) >= 0' >/dev/null; then
    echo "DRACO_OPENROUTER_MIN_REMAINING_USD must be a non-negative number" >&2
    return 2
  fi
  if ! jq -e --argjson minimum "$minimum_remaining" '
    .is_free_tier == false
    and .limit != null
    and .limit_remaining != null
    and ((.limit | tonumber) >= 0)
    and ((.limit_remaining | tonumber) >= $minimum)
  ' "$snapshot" >/dev/null; then
    echo "OpenRouter key needs a finite spending limit with at least \$$minimum_remaining remaining" >&2
    echo "An unlimited (null) key limit cannot prove that account credits are sufficient." >&2
    return 2
  fi
}

pending_before_snapshot=""
pending_after_snapshot=""
pending_result_dir=""
capture_pending_after_snapshot() {
  local mode="${1:-evidence}"
  if [[ -z "$pending_after_snapshot" ]]; then
    return 0
  fi
  local before="$pending_before_snapshot"
  local path="$pending_after_snapshot"
  local result_dir="$pending_result_dir"
  local status=0
  local -a result_files=()
  if [[ "$mode" == "settle" ]]; then
    mapfile -t result_files < <(find "$result_dir" -maxdepth 1 -type f \
      -name 'draco_ensemble_*.jsonl' | sort)
    if [[ "${#result_files[@]}" -ne 1 ]]; then
      echo "Expected exactly one result JSONL before account settlement" >&2
      status=2
    elif ! capture_account_snapshot "$path" \
      --settle-from "$before" \
      --settle-result-jsonl "${result_files[0]}"; then
      echo "OpenRouter settlement polling failed; capturing a plain after snapshot" >&2
      status=2
    fi
  fi
  if [[ "$mode" != "settle" || "$status" -ne 0 ]]; then
    rm -f "$path"
    if ! capture_account_snapshot "$path"; then
      echo "Failed to capture final OpenRouter account snapshot: $path" >&2
      status=2
    fi
  fi
  pending_before_snapshot=""
  pending_after_snapshot=""
  pending_result_dir=""
  return "$status"
}

capture_after_on_exit() {
  local status=$?
  trap - EXIT
  if ! capture_pending_after_snapshot evidence; then
    status=2
  fi
  if [[ "$formal_run" == "1" && "$formal_success" != "1" ]]; then
    rm -f "$OUTPUT_DIR/cost-audit.json" \
      "$OUTPUT_DIR/EXPERIMENT_RESULTS.md" \
      "$OUTPUT_DIR/FORMAL_RUN_SUCCESS.json"
  fi
  exit "$status"
}

run_accounted_command() {
  local before_snapshot="$1"
  local after_snapshot="$2"
  local result_dir="$3"
  shift 3
  if [[ -e "$before_snapshot" || -e "$after_snapshot" ]]; then
    echo "Refusing to reuse OpenRouter account snapshots" >&2
    return 2
  fi
  if ! capture_account_snapshot "$before_snapshot"; then
    return 2
  fi
  if ! assert_account_capacity "$before_snapshot"; then
    return 2
  fi
  pending_before_snapshot="$before_snapshot"
  pending_after_snapshot="$after_snapshot"
  pending_result_dir="$result_dir"
  trap capture_after_on_exit EXIT
  local command_status=0
  if "$@"; then
    command_status=0
  else
    command_status=$?
  fi
  local capture_mode=evidence
  if [[ "$command_status" -eq 0 ]]; then
    capture_mode=settle
  fi
  if ! capture_pending_after_snapshot "$capture_mode"; then
    restore_formal_exit_trap
    return 2
  fi
  restore_formal_exit_trap
  return "$command_status"
}

LAST_AUDITED_RESULT=""
LAST_AUDITED_TRACE=""
LAST_AUDITED_MANIFEST=""
LAST_AUDITED_EFFECTIVE_CONFIG=""
LAST_AUDITED_SUMMARY=""
LAST_AUDITED_COST_JSON=""
LAST_AUDITED_RESULTS_MD=""
audit_b2_output() {
  local output_dir="$1"
  local audit_input="$2"
  local expected_tasks="$3"
  local expected_concurrency="$4"
  local expected_judge_concurrency="$5"
  local before_snapshot="$6"
  local after_snapshot="$7"
  local reference_effective_config="$8"
  local expected_cache_namespace_sha256="${9:-}"
  local required_observed_tools="${10:-}"
  local include_validation="${11:-0}"
  local -a result_files trace_files manifest_files effective_config_files audit_args
  mapfile -t result_files < <(find "$output_dir" -maxdepth 1 -type f \
    -name 'draco_ensemble_*.jsonl' | sort)
  mapfile -t manifest_files < <(find "$output_dir" -maxdepth 1 -type f \
    -name 'draco_run_*.manifest.json' | sort)
  mapfile -t trace_files < <(find "$output_dir" -maxdepth 1 -type f \
    -name 'draco_run_*.trace.jsonl' | sort)
  mapfile -t effective_config_files < <(find "$output_dir" -maxdepth 1 -type f \
    -name 'draco_run_*.experiment-config.effective.json' | sort)
  if [[ "${#result_files[@]}" -ne 1 || "${#trace_files[@]}" -ne 1 || \
        "${#manifest_files[@]}" -ne 1 || \
        "${#effective_config_files[@]}" -ne 1 ]]; then
    echo "Expected exactly one result, trace, manifest, and effective config in $output_dir" >&2
    return 2
  fi
  local structural_audit_dir="$output_dir/strict-structure-audit"
  .venv/bin/python scripts/audit_draco_results.py \
    --input "$audit_input" \
    --result "${result_files[0]}" \
    --output-dir "$structural_audit_dir" \
    --expected-manifest "${manifest_files[0]}" \
    --prefix b2-strict-structure \
    --groups B2 \
    --max-tasks "$expected_tasks" \
    --require-result-evidence
  local summary_file="${result_files[0]%.jsonl}.summary.json"
  audit_args=(
    .venv/bin/python scripts/experiments/audit_draco_mini_cost_validation.py
    "${result_files[0]}"
    --expected-tasks "$expected_tasks"
    --manifest "${manifest_files[0]}"
    --trace-jsonl "${trace_files[0]}"
    --effective-config "${effective_config_files[0]}"
    --reference-effective-config "$reference_effective_config"
    --summary "$summary_file"
    --expected-agent-max-iterations 12
    --expected-generation-max-attempts 3
    --expected-concurrency "$expected_concurrency"
    --expected-judge-repeats 3
    --expected-judge-max-attempts 3
    --expected-judge-concurrency "$expected_judge_concurrency"
    --expected-tool-mode local_web_tools
    --expected-input-jsonl "$audit_input"
    --account-before "$before_snapshot"
    --account-after "$after_snapshot"
    --require-account-reconciliation
    --require-clean-source-now
    --account-cost-tolerance-usd 0.000001
    --external-preflight-call-count 1
    --max-selected-tool-failure-rate 0.5
  )
  if [[ -n "$expected_cache_namespace_sha256" ]]; then
    audit_args+=(
      --expected-cache-namespace-sha256 "$expected_cache_namespace_sha256"
    )
  fi
  if [[ -n "$required_observed_tools" ]]; then
    audit_args+=(--required-observed-tools "$required_observed_tools")
  fi
  if [[ "$include_validation" == "1" ]]; then
    audit_args+=(
      --validation-account-before "$canary_before"
      --validation-account-after "$canary_after"
      --validation-manifest "$canary_manifest"
      --validation-input-jsonl "$canary_input"
      --validation-external-preflight-call-count 1
    )
  fi
  "${audit_args[@]}"
  LAST_AUDITED_RESULT="${result_files[0]}"
  LAST_AUDITED_TRACE="${trace_files[0]}"
  LAST_AUDITED_MANIFEST="${manifest_files[0]}"
  LAST_AUDITED_EFFECTIVE_CONFIG="${effective_config_files[0]}"
  LAST_AUDITED_SUMMARY="$summary_file"
  LAST_AUDITED_COST_JSON="$output_dir/cost-audit.json"
  LAST_AUDITED_RESULTS_MD="$output_dir/EXPERIMENT_RESULTS.md"
}

assert_frozen_inputs() {
  [[ "$(sha256sum "$INPUT" | awk '{print $1}')" == "$input_sha256" ]] \
    || { echo "DRACO input changed during the formal run" >&2; return 2; }
  [[ "$(sha256sum "$CONFIG" | awk '{print $1}')" == "$gateway_config_sha256" ]] \
    || { echo "Gateway config changed during the formal run" >&2; return 2; }
  [[ "$(sha256sum "$EXPERIMENT_CONFIG" | awk '{print $1}')" == "$experiment_config_sha256" ]] \
    || { echo "Experiment config changed during the formal run" >&2; return 2; }
  [[ "$(sha256sum "$REPO/uv.lock" | awk '{print $1}')" == "$uv_lock_sha256" ]] \
    || { echo "uv.lock changed during the formal run" >&2; return 2; }
  [[ "$(git rev-parse HEAD)" == "$source_git_head" ]] \
    || { echo "Git HEAD changed during the formal run" >&2; return 2; }
  git diff --quiet HEAD -- "${source_paths[@]}" \
    || { echo "Tracked source changed during the formal run" >&2; return 2; }
  local current_untracked
  current_untracked="$(
    git ls-files --others --exclude-standard -- "${source_paths[@]}"
  )" || { echo "Unable to re-audit the source tree" >&2; return 2; }
  [[ -z "$current_untracked" ]] \
    || { echo "Untracked source appeared during the formal run" >&2; return 2; }
  .venv/bin/python scripts/experiments/capture_draco_runtime_environment.py verify \
    "$runtime_environment" --repo "$REPO" \
    || { echo "Python/dependency runtime changed during the formal run" >&2; return 2; }
}

assert_static_preflight_output() {
  local directory="$1"
  local reference_config="$2"
  local -a manifests effective_configs
  mapfile -t manifests < <(find "$directory" -maxdepth 1 -type f \
    -name 'draco_run_*.manifest.json' | sort)
  mapfile -t effective_configs < <(find "$directory" -maxdepth 1 -type f \
    -name 'draco_run_*.experiment-config.effective.json' | sort)
  if [[ "${#manifests[@]}" -ne 1 || "${#effective_configs[@]}" -ne 1 ]]; then
    echo "Static preflight did not produce one manifest/effective config" >&2
    return 2
  fi
  jq -e --slurpfile expected "$reference_config" '. == $expected[0]' \
    "${effective_configs[0]}" >/dev/null \
    || { echo "Static effective config differs from the frozen full config" >&2; return 2; }
  jq -e '
    .status == "complete"
    and .groups == ["B2"]
    and .rows_written == 10
    and .task_count == 10
    and .tool_policy.tool_mode == "local_web_tools"
    and .tool_policy.tools_enabled == true
    and .tool_policy.tool_names == ["web_search", "web_fetch"]
    and (.tool_policy | has("execution_security") | not)
    and .tool_policy.local_web_tools.search_runtime == {
      "configured_provider":"brave", "provider":"brave", "max_results":5,
      "api_key_configured":true, "api_key_source":"env:BRAVE_SEARCH_API_KEY",
      "api_key_env":"BRAVE_SEARCH_API_KEY", "credential_status":"configured",
      "runtime_configured":true, "proxy_configured":false, "use_env_proxy":false,
      "fallback_policy":"off", "diagnostics":false
    }
    and .tool_policy.local_web_tools.sandbox_runtime.configured == true
    and (.tool_policy.local_web_tools.sandbox_runtime.backend | type) == "string"
    and (.tool_policy.local_web_tools.sandbox_runtime.backend | length) > 0
    and .tool_policy.local_web_tools.sandbox_runtime.backend != "host"
    and .tool_policy.local_web_tools.sandbox_runtime.approval_queue
      == "auto_deny_unattended"
    and (.tool_policy.local_web_tools.sandbox_runtime.effective | type) == "object"
    and (.tool_policy.local_web_tools.sandbox_runtime.effective
      | has("sandbox_enabled"))
    and (.tool_policy.local_web_tools.sandbox_runtime.effective
      | has("grading_enabled"))
    and (.tool_policy.local_web_tools.sandbox_runtime.effective
      | has("insecure_mode"))
    and .tool_policy.local_web_tools.fetch_runtime.firecrawl_allowed == false
    and .tool_policy.local_web_tools.fetch_runtime.firecrawl_api_key_active == false
    and .tool_policy.local_web_tools.preflight.status == "skipped_dry_run"
    and .run_compatibility.contracts.B2.tools.local_web_tools.preflight == null
    and .run_compatibility.contracts.B2.resolved_llm_runtime.provider == "openrouter"
    and .run_compatibility.contracts.B2.resolved_llm_runtime.base_url
      == "https://openrouter.ai/api/v1"
    and .run_compatibility.contracts.B2.resolved_llm_runtime.provider_routing_strict == true
    and .run_compatibility.contracts.B2.resolved_llm_runtime.router_metadata_required == true
    and .run_compatibility.contracts.B2.resolved_llm_runtime.require_parameters == true
    and .run_compatibility.contracts.B2.resolved_llm_runtime.response_cache_disabled == true
    and .run_compatibility.contracts.B2.resolved_llm_runtime.trust_env == false
    and .run_compatibility.contracts.B2.resolved_llm_runtime.ambient_proxies == {}
    and .run_compatibility.contracts.B2.resolved_llm_runtime.cache_namespace_enabled == false
  ' "${manifests[0]}" >/dev/null \
    || { echo "Static runtime/tool contract gate failed" >&2; return 2; }
}

create_artifact_snapshot() {
  local root="$1"
  local output="$2"
  local allow_success="${3:-0}"
  local -a snapshot_args
  snapshot_args=(snapshot "$output" --root "$root" --recursive)
  if [[ "$allow_success" == "1" ]]; then
    snapshot_args+=(--allow-after FORMAL_RUN_SUCCESS.json)
  fi
  .venv/bin/python scripts/experiments/seal_draco_b2_artifacts.py \
    "${snapshot_args[@]}"
}

verify_artifact_snapshot() {
  .venv/bin/python scripts/experiments/seal_draco_b2_artifacts.py verify "$1"
}

if [[ "$formal_run" != "1" ]]; then
  .venv/bin/python scripts/run_draco_routing_experiment.py \
    "${benchmark_args[@]}" \
    "${extra_args[@]}" \
    --output-dir "$OUTPUT_DIR" \
    --max-tasks 10 \
    --concurrency 5 \
    --judge-concurrency 6
  exit 0
fi

lock_file="${DRACO_OPENROUTER_LOCK_FILE:-/tmp/opensquilla-draco-openrouter.lock}"
exec 9>"$lock_file"
if ! flock -n 9; then
  echo "Another local DRACO benchmark holds the OpenRouter cost-attribution lock" >&2
  exit 2
fi

input_sha256="$(sha256sum "$INPUT" | awk '{print $1}')"
gateway_config_sha256="$(sha256sum "$CONFIG" | awk '{print $1}')"
experiment_config_sha256="$(sha256sum "$EXPERIMENT_CONFIG" | awk '{print $1}')"
uv_lock_sha256="$(sha256sum "$REPO/uv.lock" | awk '{print $1}')"
source_git_head="$(git rev-parse HEAD)"

runtime_environment="$OUTPUT_DIR/runtime-environment.json"
.venv/bin/python scripts/experiments/capture_draco_runtime_environment.py capture \
  "$runtime_environment" --repo "$REPO"

full_reference_config="$OUTPUT_DIR/frozen-full-effective-config.json"
full_reference_tmp="$OUTPUT_DIR/.frozen-full-effective-config.json.tmp"
jq '.runner.concurrency = 5 | .judge.concurrency = 6' \
  "$EXPERIMENT_CONFIG" >"$full_reference_tmp"
mv "$full_reference_tmp" "$full_reference_config"

# A no-model static run must resolve to the complete golden configuration and
# the intended direct-provider/configured tool runtime before any account or model call.
static_dir="$OUTPUT_DIR/static-preflight"
mkdir -p "$static_dir"
.venv/bin/python scripts/run_draco_routing_experiment.py \
  "${benchmark_args[@]}" \
  --output-dir "$static_dir" \
  --max-tasks 10 \
  --concurrency 5 \
  --judge-concurrency 6 \
  --dry-run \
  --require-clean-source
assert_static_preflight_output "$static_dir" "$full_reference_config"
static_snapshot="$static_dir/artifact-snapshot.json"
create_artifact_snapshot "$static_dir" "$static_snapshot"
assert_frozen_inputs

# The paid canary is a synthetic, non-mini task. A one-run cache namespace is
# prefixed to every OpenRouter wire request so it cannot warm the formal task
# prompts through an upstream provider's implicit prompt cache.
canary_dir="$OUTPUT_DIR/nonbyok-canary"
mkdir -p "$canary_dir"
canary_input="$canary_dir/canary-input.jsonl"
canary_config="$canary_dir/canary-experiment-config.json"
.venv/bin/python scripts/experiments/prepare_draco_b2_canary.py \
  --base-config "$EXPERIMENT_CONFIG" \
  --benchmark-input "$INPUT" \
  --output-input "$canary_input" \
  --output-config "$canary_config"
route_before_canary="$canary_dir/openrouter-route-preflight.json"
.venv/bin/python scripts/experiments/validate_openrouter_b2_routes.py \
  "$route_before_canary"
canary_cache_namespace="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
if [[ ! "$canary_cache_namespace" =~ ^[0-9a-f]{64}$ ]]; then
  echo "Unable to create a valid canary cache namespace" >&2
  exit 2
fi
canary_cache_namespace_sha256="sha256:$(
  printf '%s' "$canary_cache_namespace" | sha256sum | awk '{print $1}'
)"
canary_before="$canary_dir/openrouter-account-before.json"
canary_after="$canary_dir/openrouter-account-after.json"
set +e
run_accounted_command "$canary_before" "$canary_after" "$canary_dir" \
  env \
  OPENSQUILLA_BENCHMARK_CACHE_NAMESPACE="$canary_cache_namespace" \
  OPENSQUILLA_BENCHMARK_CACHE_NAMESPACE_REQUIRED=1 \
  .venv/bin/python scripts/run_draco_routing_experiment.py \
  "${benchmark_args[@]}" \
  --input "$canary_input" \
  --experiment-config "$canary_config" \
  --output-dir "$canary_dir" \
  --max-tasks 1 \
  --concurrency 1 \
  --judge-concurrency 1 \
  --require-clean-source \
  --require-openrouter-non-byok \
  --experiment-config-set runner.concurrency=1 \
  --experiment-config-set judge.concurrency=1
canary_status=$?
set -e
if [[ "$canary_status" -ne 0 ]]; then
  echo "Non-BYOK canary failed; the full benchmark was not started" >&2
  exit "$canary_status"
fi
unset canary_cache_namespace
audit_b2_output "$canary_dir" "$canary_input" 1 1 1 \
  "$canary_before" "$canary_after" "$canary_config" \
  "$canary_cache_namespace_sha256" "web_search,web_fetch" 0
assert_frozen_inputs
canary_manifest="$LAST_AUDITED_MANIFEST"
canary_snapshot="$canary_dir/artifact-snapshot.json"
create_artifact_snapshot "$canary_dir" "$canary_snapshot"
verify_artifact_snapshot "$static_snapshot"
verify_artifact_snapshot "$canary_snapshot"

route_before_full="$OUTPUT_DIR/openrouter-route-preflight-before-full.json"
.venv/bin/python scripts/experiments/validate_openrouter_b2_routes.py \
  "$route_before_full"
verify_artifact_snapshot "$canary_snapshot"
account_before="$OUTPUT_DIR/openrouter-account-before.json"
account_after="$OUTPUT_DIR/openrouter-account-after.json"
set +e
run_accounted_command "$account_before" "$account_after" "$OUTPUT_DIR" \
  .venv/bin/python scripts/run_draco_routing_experiment.py \
  "${benchmark_args[@]}" \
  --output-dir "$OUTPUT_DIR" \
  --max-tasks 10 \
  --concurrency 5 \
  --judge-concurrency 6 \
  --require-clean-source \
  --require-openrouter-non-byok
run_status=$?
set -e
if [[ "$run_status" -ne 0 ]]; then
  exit "$run_status"
fi
assert_frozen_inputs
verify_artifact_snapshot "$static_snapshot"
verify_artifact_snapshot "$canary_snapshot"
audit_b2_output "$OUTPUT_DIR" "$INPUT" 10 5 6 \
  "$account_before" "$account_after" "$full_reference_config" "" \
  "web_search,web_fetch" 1
assert_frozen_inputs
verify_artifact_snapshot "$static_snapshot"
verify_artifact_snapshot "$canary_snapshot"

full_snapshot="$OUTPUT_DIR/artifact-snapshot.json"
create_artifact_snapshot "$OUTPUT_DIR" "$full_snapshot" 1
verify_artifact_snapshot "$full_snapshot"
verify_artifact_snapshot "$static_snapshot"
verify_artifact_snapshot "$canary_snapshot"

.venv/bin/python scripts/experiments/seal_draco_b2_artifacts.py success \
  "$OUTPUT_DIR/FORMAL_RUN_SUCCESS.json" \
  --source-git-head "$source_git_head" \
  --input-sha256 "$input_sha256" \
  --gateway-config-sha256 "$gateway_config_sha256" \
  --experiment-config-sha256 "$experiment_config_sha256" \
  --snapshot "$static_snapshot" \
  --snapshot "$canary_snapshot" \
  --snapshot "$full_snapshot" \
  --evidence "$route_before_canary" \
  --evidence "$route_before_full"

formal_success=1
trap - EXIT
