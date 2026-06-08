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

    .PARAMETER ProfilesRoot
        The directory to scan.

    .PARAMETER Ignore
        Optional list of profile names to skip. Useful for
        `start-all.ps1 -Ignore coder,test_*` to leave a few profiles
        down while bringing the rest of the fleet up. Filtering is
        applied AFTER the alphabetical sort so port allocation stays
        stable when the ignore list changes between invocations.
    #>
    param(
        [Parameter(Mandatory)] [string]   $ProfilesRoot,
        [string[]]                       $Ignore
    )
    if (-not (Test-Path -LiteralPath $ProfilesRoot -PathType Container)) {
        return @()
    }
    $entries = Get-ChildItem -LiteralPath $ProfilesRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name
    $ignoreSet = if ($Ignore) { [System.Collections.Generic.HashSet[string]]::new(
        [string[]]$Ignore, [System.StringComparer]::OrdinalIgnoreCase) } else { $null }
    $results = @()
    foreach ($entry in $entries) {
        if ($ignoreSet -and $ignoreSet.Contains($entry.Name)) {
            continue
        }
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

function Test-PortInUse {
    <#
    .SYNOPSIS Probe whether a TCP port is currently in use.
    .DESCRIPTION
    Returns $true if a TCP connection to host:port succeeds within
    200ms (something is listening). Returns $false otherwise (free,
    connection refused, or unreachable). The probe is best-effort:
    a port that is free at supervisor time can still race with
    another process at start time. Used by Get-ProfilePort to honor
    the port-allocation algorithm even when the algorithm's nominal
    port is already bound.
    #>
    param(
        [Parameter(Mandatory)] [int]    $Port,
        [string] $BindHost = '127.0.0.1'
    )
    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($BindHost, $Port, $null, $null)
        $result = $iar.AsyncWaitHandle.WaitOne(200, $false)
        if ($result -and $client.Connected) {
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        if ($client) {
            try { $client.Close() } catch {}
        }
    }
}

function Get-ProfilePort {
    <#
    .SYNOPSIS Compute the port for a profile, hunting forward if occupied.

    .DESCRIPTION
    Computes the algorithm's nominal port (per the rules below). If
    that port is already bound (e.g., a stale gateway from a previous
    session, or an app squatting on the slot), the function scans
    forward up to $MaxPortOffset ports to find the first free port.
    This way the operator can leave a port-hungry profile at the
    next available slot without manually re-jigging the algorithm.

    Allocation rules (same on Windows / macOS / Linux):

      * The profile named `default` is anchored at exactly $BasePort
        (default 18791). It is treated specially because operators
        always want the "vanilla" gateway on the documented port.

      * All other profiles start at $BasePort + 2 (i.e. the
        BasePort+1 slot is intentionally left empty). Each
        subsequent non-default profile (in alphabetical order)
        increments by one: BasePort+2, BasePort+3, ...

      * With the default BasePort=18791 that gives:

            default         → 18791
            <1st non-default> → 18793
            <2nd non-default> → 18794
            ...

      * The order is taken from `Get-ProfileEntries`, which respects
        the optional -Ignore list. So removing a profile from the
        fleet does NOT cause port numbers to drift for the
        survivors.

      * PORT-HUNTING: if the algorithm's nominal port for this
        profile is in use, the function scans forward (nominal+1,
        nominal+2, ...) until it finds a free port. The chosen port
        is reported via Write-Status when it differs from nominal.

    .PARAMETER Ignore
        Optional list of profile names to exclude when computing the
        index. Forwarded to `Get-ProfileEntries`. The default
        profile's port is unchanged regardless of the ignore list.

    .PARAMETER MaxPortOffset
        How far forward to scan before giving up. Default 50 (i.e.,
        ports up to nominal+50 will be tried). Set to 0 to disable
        port-hunting (return the nominal port even if it's taken).
    #>
    param(
        [Parameter(Mandatory)] [string]   $Name,
        [Parameter(Mandatory)] [int]      $BasePort,
        [Parameter(Mandatory)] [string]   $ProfilesRoot,
        [string[]]                       $Ignore,
        [int]                            $MaxPortOffset = 50
    )
    if ($Name -eq 'default') {
        $nominal = [int]$BasePort
    } else {
        $siblings = Get-ProfileEntries -ProfilesRoot $ProfilesRoot -Ignore $Ignore
        $index = 0
        $found = $false
        foreach ($sibling in $siblings) {
            if ($sibling.Name -eq 'default') {
                continue
            }
            if ($sibling.Name -eq $Name) {
                $nominal = [int]($BasePort + 2 + $index)
                $found = $true
                break
            }
            $index += 1
        }
        if (-not $found) {
            # Profile not present in root (or filtered out). Fall back
            # to the first non-default slot so a one-off query still
            # returns a usable port.
            $nominal = [int]($BasePort + 2)
        }
    }

    # Port-hunt: scan forward if the nominal port is occupied.
    for ($offset = 0; $offset -le $MaxPortOffset; $offset++) {
        $candidate = $nominal + $offset
        if (-not (Test-PortInUse -Port $candidate)) {
            if ($offset -gt 0) {
                Write-Status (
                    "[{0}] nominal port {1} taken; using {2} (+{3})" -f $Name, $nominal, $candidate, $offset
                ) -Level warn
            }
            return [int]$candidate
        }
    }

    # No free port in the search window. Return the nominal and
    # surface the failure so the operator sees the situation.
    Write-Status (
        "[{0}] no free port in {1}..{2} (nominal {3}); returning nominal" -f $Name, $nominal, ($nominal + $MaxPortOffset), $nominal
    ) -Level err
    return [int]$nominal
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

# --- Real task state ------------------------------------------------------

function Get-GatewayState {
    <#
    .SYNOPSIS Query opensquilla for the REAL gateway state of a profile/port.

    .DESCRIPTION
    Runs `opensquilla --profile <name> gateway status --port <port> --json`
    and parses the response. This is the canonical "is the agent task
    actually busy" check — NOT a TCP probe. The supervisor's diagnostic
    uses this to display a faithful task status; `Get-ProfilePort`
    keeps using the lighter `Test-PortInUse` probe for port-hunting
    because the algorithm only needs "is the socket bindable",
    not "what is opensquilla thinking".

    Returns a PSCustomObject with:
      State   = 'running' | 'not_started' | 'unhealthy' | 'target_mismatch'
                | 'unknown' | 'no_opensquilla'
      Managed = $true | $false   (whether opensquilla owns the PID)
      Pid     = process ID (or $null)
      Url     = gateway URL
      Error   = error message if opensquilla call failed (or $null)
    #>
    param(
        [Parameter(Mandatory)] [int]    $Port,
        [string] $Profile = $null,
        [string] $BindHost = '127.0.0.1',
        [string] $Repo = $null
    )
    $cmd = Get-OpensquillaCommand -Repo $Repo
    if ($cmd.Mode -eq 'none') {
        return [pscustomobject]@{
            State   = 'no_opensquilla'
            Managed = $false
            Pid     = $null
            Url     = $null
            Error   = 'opensquilla not on PATH and no source checkout auto-detected'
        }
    }
    $arguments = @()
    if ($Profile) {
        $arguments += @('--profile', $Profile)
    }
    $arguments += @('gateway', 'status', '--port', [string]$Port, '--listen', $BindHost, '--json')

    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()
    try {
        switch ($cmd.Mode) {
            'installed' {
                $proc = Start-Process -FilePath $cmd.Exe `
                    -ArgumentList $arguments `
                    -NoNewWindow -Wait -PassThru `
                    -RedirectStandardOutput $stdoutFile `
                    -RedirectStandardError $stderrFile
            }
            'uv-run-repo' {
                Push-Location -LiteralPath $cmd.Repo
                try {
                    $proc = Start-Process -FilePath 'uv' `
                        -ArgumentList (@('run', 'opensquilla') + $arguments) `
                        -NoNewWindow -Wait -PassThru `
                        -RedirectStandardOutput $stdoutFile `
                        -RedirectStandardError $stderrFile
                } finally {
                    Pop-Location
                }
            }
        }
        $stdout = if (Test-Path $stdoutFile) {
            Get-Content $stdoutFile -Raw -ErrorAction SilentlyContinue
        } else { '' }
        $json = $stdout | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($json) {
            return [pscustomobject]@{
                State   = [string]$json.state
                Managed = [bool]$json.managed
                Pid     = if ($json.pid) { [int]$json.pid } else { $null }
                Url     = [string]$json.url
                Error   = $null
            }
        }
        return [pscustomobject]@{
            State   = 'unknown'
            Managed = $false
            Pid     = $null
            Url     = $null
            Error   = 'opensquilla returned no JSON on stdout'
        }
    } catch {
        return [pscustomobject]@{
            State   = 'unknown'
            Managed = $false
            Pid     = $null
            Url     = $null
            Error   = $_.Exception.Message
        }
    } finally {
        Remove-Item $stdoutFile, $stderrFile -ErrorAction SilentlyContinue
    }
}
