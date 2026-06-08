#!/usr/bin/env bash
# scripts/dev-install.sh
# Dev install: editable opensquilla with the recommended runtime profile.
#
# This is the default install path for OpenSquilla contributors. It runs
# `uv tool install -e ".[recommended]"` from the repo root so the
# `opensquilla` shim on PATH tracks the current checkout and the bundled
# SquillaRouter (numpy + joblib + scikit-learn + onnxruntime + ...) is
# pulled in without any extra flags.
#
# Usage:
#   bash scripts/dev-install.sh              # reinstall after a `git pull`
#   bash scripts/dev-install.sh --no-cache   # forward flags to uv tool install
#
# Rationale for a wrapper instead of `uv tool install -e ".[recommended]"`:
#   uv tool install does not accept a --extra / --all-extras flag (only
#   `--with <pkg>` for individual packages), so the PEP 508 form
#   `.[recommended]` is the only way to bring the runtime profile in.
#   Centralising that into a script keeps callers from typing it by hand
#   and gives maintainers one place to bump the profile if it changes.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

# Keep `uv.lock` and the venv's site-packages in sync with the just-changed
# `.[recommended]` resolution. `--upgrade` makes repeated runs cheap when the
# upstream registry moves; `--no-cache` is forwarded by callers via "$@".
exec uv tool install --upgrade -e ".[recommended]" --force "$@"
