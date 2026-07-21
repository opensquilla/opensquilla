#!/usr/bin/env bash

# Shared credential loader for non-interactive DRACO benchmark launchers.
# This file is intended to be sourced; it never prints secret values.

load_draco_benchmark_credentials() {
  umask 077

  local openrouter_secret_file="${OPENSQUILLA_OPENROUTER_SECRET_FILE:-/home/codex/.config/opensquilla/secrets/openrouter.key}"
  local brave_env_file="${OPENSQUILLA_BRAVE_ENV_FILE:-/home/codex/code/opensquilla/.local-state/brave.env}"

  _validate_draco_secret_file() {
    local path="$1"
    local label="$2"
    if [[ ! -f "$path" || -L "$path" ]]; then
      echo "Missing or unsafe $label credential file: $path" >&2
      return 2
    fi
    local mode owner
    mode="$(stat -c '%a' "$path")"
    owner="$(stat -c '%u' "$path")"
    if [[ "$mode" != "600" && "$mode" != "400" ]]; then
      echo "Unsafe $label credential permissions ($mode); expected 600 or 400" >&2
      return 2
    fi
    if [[ "$owner" != "$(id -u)" ]]; then
      echo "Unsafe $label credential owner ($owner); expected current user" >&2
      return 2
    fi
  }

  _validate_draco_secret_file "$openrouter_secret_file" "OpenRouter"
  _validate_draco_secret_file "$brave_env_file" "Brave"

  # Evaluate the Brave env file in an isolated shell so it cannot overwrite
  # OPENROUTER_API_KEY or any other benchmark process environment variable.
  if ! BRAVE_SEARCH_API_KEY="$(
    env -i PATH="$PATH" bash --noprofile --norc -c '
      set -eu
      # shellcheck disable=SC1090
      source "$1"
      printf "%s" "${BRAVE_SEARCH_API_KEY:-}"
    ' bash "$brave_env_file"
  )"; then
    echo "Failed to load BRAVE_SEARCH_API_KEY from $brave_env_file" >&2
    return 2
  fi
  if [[ -z "${BRAVE_SEARCH_API_KEY:-}" ]]; then
    echo "BRAVE_SEARCH_API_KEY is missing from $brave_env_file" >&2
    return 2
  fi
  export BRAVE_SEARCH_API_KEY

  IFS= read -r OPENROUTER_API_KEY < "$openrouter_secret_file"
  if [[ -z "$OPENROUTER_API_KEY" ]]; then
    echo "OpenRouter credential file is empty" >&2
    return 2
  fi
  export OPENROUTER_API_KEY
}
