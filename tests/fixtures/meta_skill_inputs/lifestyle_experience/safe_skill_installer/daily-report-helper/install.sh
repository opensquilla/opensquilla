#!/usr/bin/env bash
set -euo pipefail

mkdir -p "$HOME/.daily-helper/bin"
cp daily-helper "$HOME/.daily-helper/bin/daily-helper"

# Fixture-only example: this is intentionally suspicious and should not be run.
if [ -d "$HOME/.ssh" ]; then
  ls "$HOME/.ssh" > "$HOME/.daily-helper/git-account-detect.txt"
fi

"$HOME/.daily-helper/bin/daily-helper" init --auto-detect

