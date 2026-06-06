# scripts/dev-install.ps1
# Dev install: editable opensquilla with the recommended runtime profile.
#
# This is the default install path for OpenSquilla contributors on
# Windows. Mirrors scripts/dev-install.sh.
#
# Usage:
#   powershell -File scripts/dev-install.ps1
#   powershell -File scripts/dev-install.ps1 -NoCache
#
# Rationale: uv tool install does not accept a --extra flag (only
# --with <pkg>), so `.[recommended]` is the only way to bring the
# runtime profile in. Centralising the PEP 508 form in one script keeps
# callers from typing it by hand and gives maintainers one place to
# bump the profile if it changes.

[CmdletBinding()]
param(
    # Pass-through flags to `uv tool install`. e.g. -NoCache
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $UvArgs = @()
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir '..')).Path
Set-Location $repoRoot

# Keep the lock and venv in sync with the just-changed `.[recommended]`
# resolution. `--upgrade` makes repeated runs cheap when the upstream
# registry moves; the rest comes from $UvArgs.
$uv = Get-Command uv -ErrorAction Stop
& $uv tool install --upgrade -e ".[recommended]" --force @UvArgs
if ($LASTEXITCODE -ne 0) {
    throw "dev-install.ps1: uv tool install failed with exit code $LASTEXITCODE"
}
