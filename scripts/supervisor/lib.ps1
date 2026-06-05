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
$Script:OPENSQUILLA_REPO = 'D:\ai\opensquilla\opensquilla'

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
    #>
    param([string]$Override)
    $candidate = if ($Override) { $Override } else { $Script:OPENSQUILLA_REPO }
    if (-not (Test-Path -LiteralPath $candidate)) {
        throw "OpenSquilla repo not found: $candidate. Pass -Repo or set $Script:OPENSQUILLA_REPO."
    }
    return (Resolve-Path -LiteralPath $candidate).Path
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
    and the working directory so the user-facing scripts don't have to repeat
    the boilerplate. Returns the process exit code.

    Uses `uv run opensquilla ...` so the same Python environment the developer
    is iterating with is what supervises the gateway. `-NoNewWindow` keeps the
    console from spawning a new window per profile when launched from a
    terminal; when launched headless (Task Scheduler at logon) the lack of a
    parent console is harmless.
    #>
    param(
        [Parameter(Mandatory)] [string] $Repo,
        [Parameter(Mandatory)] [string] $Profile,
        [Parameter(Mandatory)] [string[]] $Arguments
    )
    $profileLeaf = Split-Path -Leaf $Profile
    $profileRoot = Split-Path -Parent $Profile
    $env:OPENSQUILLA_HOME = $profileRoot
    $env:OPENSQUILLA_PROFILE = $profileLeaf
    Push-Location -LiteralPath $Repo
    try {
        $proc = Start-Process -FilePath 'uv' `
            -ArgumentList (@('run', 'opensquilla') + $Arguments) `
            -NoNewWindow -Wait -PassThru
        return $proc.ExitCode
    } finally {
        Pop-Location
    }
}
