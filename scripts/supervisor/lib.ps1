<#
.SYNOPSIS
    Shared helpers for the OpenSquilla multi-profile supervisor scripts.

.DESCRIPTION
    Loaded via dot-sourcing (`. ./lib.ps1`) by start-all.ps1, stop-all.ps1,
    status.ps1, install-autostart.ps1, and uninstall-autostart.ps1. Owns:
      * Default profiles-root and base-port resolution.
      * Profile discovery (scan a directory, ignore non-profile entries).
      * Index-based port assignment (18791 + profile_index_within_root).
      * A small Write-Status helper so the user-facing scripts stay terse.

    Kept tiny and dependency-free: pure PowerShell, no module imports beyond
    what's bundled with Windows PowerShell 5.1+ and PowerShell 7.
#>

$ErrorActionPreference = 'Stop'

if (-not (Get-Variable -Name SUPERVISOR_LIB_LOADED -Scope Script -ErrorAction SilentlyContinue)) {
    $Script:SUPERVISOR_LIB_LOADED = $true
} else {
    return
}

# --- Configuration ---------------------------------------------------------

$Script:DEFAULT_PROFILES_DIR = 'D:\ai\opensquilla\profiles'
$Script:DEFAULT_BASE_PORT = 18791
$Script:TASK_NAME = 'OpenSquillaProfileSupervisor'
$Script:DISPLAY_NAME = 'OpenSquilla Multi-Profile Gateway Supervisor'

# --- Path / env helpers ----------------------------------------------------

function Get-ProfilesRoot {
    <#
    .SYNOPSIS Resolve the profiles root directory (OPENSQUILLA_HOME or default).
    #>
    param([string]$Override)
    $candidate = if ($Override) { $Override } elseif ($env:OPENSQUILLA_HOME) { $env:OPENSQUILLA_HOME } else { $Script:DEFAULT_PROFILES_DIR }
    if (-not $candidate) {
        throw 'Profiles root is empty. Pass -ProfilesRoot or set $env:OPENSQUILLA_HOME.'
    }
    if (-not (Test-Path -LiteralPath $candidate)) {
        throw "Profiles root does not exist: $candidate"
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Get-OpensquillaRoot {
    <#
    .SYNOPSIS Resolve the OpenSquilla repo root (where `uv run opensquilla ...` lives).
    .DESCRIPTION
    Resolution order (first hit wins):
      1. The explicit -Repo override, if any.
      2. The parent of this script's directory. The supervisor scripts live in
         <repo>/scripts/supervisor/, so two levels up is the repo root. This
         covers the documented "clone the repo and run the scripts" workflow
         on any host without a machine-specific default.
      3. The parent of an installed `opensquilla` executable (uv tool install
         typically places it under %USERPROFILE%\.local\bin or
         %LOCALAPPDATA%\uv\bin). The script does not actually need the repo
         in this case; it only needs a path whose `uv run` invocation is
         unambiguous, so we resolve the repo from the executable's
         location as a last-resort tiebreaker.
    Returns the resolved repo path, or $null if nothing was found (in which
    case the caller should fall back to the installed executable directly).
    #>
    param([string]$Override)
    if ($Override) {
        if (-not (Test-Path -LiteralPath $Override)) {
            throw "OpenSquilla repo not found: $Override. Pass -Repo or omit to auto-detect."
        }
        return (Resolve-Path -LiteralPath $Override).Path
    }
    $scriptDir = $PSScriptRoot
    if ($scriptDir) {
        $candidate = Join-Path (Split-Path -Parent $scriptDir) '..' | Join-Path -ChildPath '..' | ForEach-Object { $_ }
        # Two levels up from <repo>/scripts/supervisor/ is the repo root.
        $candidate = Split-Path -Parent (Split-Path -Parent $scriptDir)
        if (Test-Path -LiteralPath (Join-Path $candidate 'pyproject.toml')) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Get-OpensquillaCommand {
    <#
    .SYNOPSIS Resolve the best way to invoke `opensquilla` on this host.
    .DESCRIPTION
    Returns a hashtable with:
      * Mode   — 'uv-run-repo' | 'installed' | 'none'
      * Repo   — repo path (Mode=uv-run-repo only)
      * Exe    — full path to the installed opensquilla executable (Mode=installed only)
    Callers should use Mode to pick the invocation strategy: uv run from Repo
    when iterating from a source checkout, or the installed executable when
    the user installed via `uv tool install`. PowerShell's standard
    `Get-Command opensquilla` resolves via PATH for the second case so we
    do not have to hard-code the tool directory.
    #>
    param([string]$Repo)
    $opensquilla = Get-Command 'opensquilla' -ErrorAction SilentlyContinue
    if ($opensquilla) {
        return @{ Mode = 'installed'; Exe = $opensquilla.Path }
    }
    $resolvedRepo = Get-OpensquillaRoot -Override $Repo
    if ($resolvedRepo -and (Test-Path -LiteralPath (Join-Path $resolvedRepo 'pyproject.toml'))) {
        return @{ Mode = 'uv-run-repo'; Repo = $resolvedRepo }
    }
    return @{ Mode = 'none' }
}

# --- Profile discovery -----------------------------------------------------

function Get-ProfileEntries {
    <#
    .SYNOPSIS Enumerate profiles under a root directory.

    .DESCRIPTION
    A "profile" is a subdirectory of the profiles root that contains a
    `config.toml` (or, defensively, just *any* subdirectory at all). The
    discovery order is alphabetical, deterministic across hosts.

    Returns PSCustomObjects with: Name, Path, ConfigPath, HasConfig.
    #>
    param(
        [Parameter(Mandatory)] [string] $ProfilesRoot
    )
    if (-not (Test-Path -LiteralPath $ProfilesRoot -PathType Container)) {
        return @()
    }
    $entries = Get-ChildItem -LiteralPath $ProfilesRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name
    $results = @()
    foreach ($entry in $entries) {
        $configPath = Join-Path $entry.FullName 'config.toml'
        $hasConfig = Test-Path -LiteralPath $configPath -PathType Leaf
        $results += [pscustomobject]@{
            Name = $entry.Name
            Path = $entry.FullName
            ConfigPath = $configPath
            HasConfig = $hasConfig
        }
    }
    return ,$results
}

# --- Port allocation -------------------------------------------------------

function Get-ProfilePort {
    <#
    .SYNOPSIS Compute the port for a profile (BasePort + index within root).

    .DESCRIPTION
    Same algorithm on Windows / macOS / Linux: profile order is the sorted
    alphabetical order of the profiles-root subdirectory listing, so the
    port mapping is stable across reboots. Operators can override by passing
    a different -BasePort; per-profile override lives in
    `<profile>/config.toml` under `[gateway] port` and is read directly by
    `opensquilla gateway start` (this script does not parse TOML itself).
    #>
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [int]    $BasePort,
        [Parameter(Mandatory)] [string] $ProfilesRoot
    )
    $siblings = Get-ProfileEntries -ProfilesRoot $ProfilesRoot
    $index = 0
    foreach ($sibling in $siblings) {
        if ($sibling.Name -eq $Name) {
            return [int]($BasePort + $index)
        }
        $index += 1
    }
    # Profile not present in root — caller is misusing. Fall back to base.
    return [int]$BasePort
}

# --- Output helpers --------------------------------------------------------

function Write-Status {
    param(
        [string] $Message,
        [ValidateSet('info', 'ok', 'warn', 'err')] [string] $Level = 'info'
    )
    $prefix = switch ($Level) {
        'ok'   { '[OK]   ' }
        'warn' { '[WARN] ' }
        'err'  { '[ERR]  ' }
        default { '[..]   ' }
    }
    $color = switch ($Level) {
        'ok'   { 'Green' }
        'warn' { 'Yellow' }
        'err'  { 'Red' }
        default { 'Cyan' }
    }
    Write-Host ($prefix + $Message) -ForegroundColor $color
}

function Invoke-Opensquilla {
    <#
    .SYNOPSIS Run an `opensquilla` subcommand inside a profile.

    .DESCRIPTION
    Centralises the env setup (OPENSQUILLA_HOME + OPENSQUILLA_PROFILE)
    and the invocation strategy so the user-facing scripts don't have to
    repeat the boilerplate. Returns the process exit code.

    Picks the best available strategy at call time:
      1. If `opensquilla` is on PATH (typical after `uv tool install`),
         invoke it directly — no repo needed.
      2. Otherwise, fall back to `uv run` from a source checkout if one
         is auto-detected next to this script. This covers the "run the
         scripts straight from a clone" workflow.
      3. If neither is available, throw — the operator must either
         install the wheel or run the scripts from inside a clone.
    #>
    param(
        [string] $Repo,
        [Parameter(Mandatory)] [string] $Profile,
        [Parameter(Mandatory)] [string[]] $Arguments
    )
    $profileLeaf = Split-Path -Leaf $Profile
    $profileRoot = Split-Path -Parent $Profile
    $env:OPENSQUILLA_HOME = $profileRoot
    $env:OPENSQUILLA_PROFILE = $profileLeaf

    $cmd = Get-OpensquillaCommand -Repo $Repo
    switch ($cmd.Mode) {
        'installed' {
            $proc = Start-Process -FilePath $cmd.Exe `
                -ArgumentList $Arguments `
                -NoNewWindow -Wait -PassThru
            return $proc.ExitCode
        }
        'uv-run-repo' {
            Push-Location -LiteralPath $cmd.Repo
            try {
                $proc = Start-Process -FilePath 'uv' `
                    -ArgumentList (@('run', 'opensquilla') + $Arguments) `
                    -NoNewWindow -Wait -PassThru
                return $proc.ExitCode
            } finally {
                Pop-Location
            }
        }
        default {
            throw 'opensquilla is not on PATH and no source checkout was auto-detected next to this script. Either run `uv tool install opensquilla` (recommended) or invoke these scripts from inside a clone of opensquilla/opensquilla.'
        }
    }
}
