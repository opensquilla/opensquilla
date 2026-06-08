<#
.SYNOPSIS
    Start the OpenSquilla gateway for every profile under the profiles root
    IN PARALLEL (PowerShell 7+ `ForEach-Object -Parallel`, default throttle 8).

.DESCRIPTION
    Discovers all subdirectories of the profiles root (each is one profile),
    computes a deterministic port per profile (`BasePort + sorted-index`),
    and invokes `opensquilla --profile <name> gateway start --port <port>`
    in parallel. A profile that fails to start does not stop the others —
    the parallel runspace logs the failure and the final summary reports it.

    The previous sequential `foreach` loop was the bottleneck once you
    have 10+ profiles (each start is dominated by gateway readiness wait,
    not CPU). Parallel mode cuts wall time from O(N * readiness) to roughly
    O(ceil(N / ThrottleLimit) * readiness).

    If a profile is already running (gateway status reports running for the
    same host/port), the script skips it and reports "already up".

.PARAMETER ProfilesRoot
    Override the profiles-root directory. Defaults to
    $env:OPENSQUILLA_HOME or the script's built-in default.

.PARAMETER BasePort
    First port in the allocation sequence. Each subsequent profile (in
    alphabetical order) gets BasePort+1, +2, etc.

.PARAMETER Host
    Bind address passed to `gateway start`. Default 127.0.0.1.

.PARAMETER SkipRunning
    If set, do not attempt to start profiles whose gateway is already
    running on the assigned port.

.PARAMETER ThrottleLimit
    Number of profiles to start in parallel. Default 8. Set to 1 to
    fall back to serial behavior (matches the original `foreach` loop).

.PARAMETER Ignore
    Comma-separated list of profile names to skip. Mirrors
    `opensquilla profiles init-all --only-uninitialised` in spirit:
    bring up "everything except a few I want to leave down". Globs are
    NOT supported; pass exact names. The ignore list is forwarded to
    the port-allocation algorithm so the surviving profiles keep
    stable port numbers.

.PARAMETER Repo
    Override the OpenSquilla source checkout that backs this script.
    Only used when `opensquilla` is not on PATH. Defaults to the parent
    of this script's directory (i.e. two levels up from
    `scripts/supervisor/`).

.EXAMPLE
    .\start-all.ps1
    .\start-all.ps1 -BasePort 19000
    .\start-all.ps1 -ProfilesRoot D:\work\profiles -SkipRunning
    .\start-all.ps1 -Repo D:\src\opensquilla
    .\start-all.ps1 -ThrottleLimit 4          # conservative on low-RAM hosts
#>
[CmdletBinding()]
param(
    [string]   $ProfilesRoot,
    [int]      $BasePort = 18791,
    [string]   $BindHost = '127.0.0.1',
    [switch]   $SkipRunning,
    [int]      $ThrottleLimit = 8,
    [string[]] $Ignore = @(),
    [string]   $Repo
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

$root    = Get-ProfilesRoot -Override $ProfilesRoot
$cmd     = Get-OpensquillaCommand -Repo $Repo
$entries = Get-ProfileEntries -ProfilesRoot $root -Ignore $Ignore

if ($Ignore -and $Ignore.Count -gt 0) {
    Write-Status "Ignoring $($Ignore.Count) profile(s): $($Ignore -join ', ')" -Level info
}

if (-not $entries -or $entries.Count -eq 0) {
    Write-Status "No profiles found under $root. Run `opensquilla --profile <name> init` first." -Level warn
    return
}

Write-Status "Discovered $($entries.Count) profile(s) under $root" -Level info
Write-Status "Base port: $BasePort (each profile = base + sorted-index)" -Level info
Write-Status "Throttle: $ThrottleLimit parallel starts" -Level info
switch ($cmd.Mode) {
    'installed'     { Write-Status "Mode: installed `opensquilla` at $($cmd.Exe)" -Level info }
    'uv-run-repo'   { Write-Status "Mode: uv run from $($cmd.Repo)" -Level info }
    default         { Write-Status "Mode: no `opensquilla` found; set PATH or pass -Repo" -Level err }
}
Write-Host ''

# Pre-compute port per profile (sequential, fast — no external calls).
# This is the only place we touch Get-ProfilePort. Once we have the port
# table the parallel block can run with no cross-runspace state.
$profileJobs = foreach ($entry in $entries) {
    $port = Get-ProfilePort -Name $entry.Name -BasePort $BasePort -ProfilesRoot $root -Ignore $Ignore
    [pscustomobject]@{
        Name = $entry.Name
        Path = $entry.Path
        Port = $port
    }
}

# Parallel starts. Each runspace sets OPENSQUILLA_HOME / OPENSQUILLA_PROFILE
# for its own process (Start-Process inherits the caller's env by default
# but the per-call env vars we set here are scoped to that subprocess and
# do NOT race across runspaces because Start-Process snapshots env at
# launch time).
$results = $profileJobs | ForEach-Object -Parallel {
    $job       = $_
    $name      = $job.Name
    $path      = $job.Path
    $port      = $job.Port
    $BindHost  = $using:BindHost
    $SkipRun   = $using:SkipRunning
    $cmd       = $using:cmd

    $profileLeaf = Split-Path -Leaf $path
    $profileRoot = Split-Path -Parent $path
    $env:OPENSQUILLA_HOME    = $profileRoot
    $env:OPENSQUILLA_PROFILE = $profileLeaf

    # Inlined Write-Status — lib.ps1 functions are not visible inside the
    # parallel runspace (dot-sourced functions do not cross runspace
    # boundaries). Output goes to the caller's console, possibly
    # interleaved across profiles; the final summary groups by status.
    function _WS {
        param([string]$Msg, [string]$Level = 'info')
        $prefix = switch ($Level) { 'ok' { '[OK]   ' } 'warn' { '[WARN] ' } 'err' { '[ERR]  ' } default { '[..]   ' } }
        $color  = switch ($Level) { 'ok' { 'Green' } 'warn' { 'Yellow' } 'err' { 'Red' } default { 'Cyan' } }
        Write-Host ("[{0}] {1}" -f $name, ($prefix + $Msg)) -ForegroundColor $color
    }

    function _Invoke {
        param([string[]]$Arguments)
        switch ($cmd.Mode) {
            'installed' {
                return (Start-Process -FilePath $cmd.Exe `
                    -ArgumentList $Arguments `
                    -NoNewWindow -Wait -PassThru).ExitCode
            }
            'uv-run-repo' {
                Push-Location -LiteralPath $cmd.Repo
                try {
                    return (Start-Process -FilePath 'uv' `
                        -ArgumentList (@('run', 'opensquilla') + $Arguments) `
                        -NoNewWindow -Wait -PassThru).ExitCode
                } finally {
                    Pop-Location
                }
            }
            default {
                throw 'opensquilla is not on PATH and no source checkout was auto-detected next to this script.'
            }
        }
    }

    try {
        if ($SkipRun) {
            $statusArgs = @('--profile', $name, 'gateway', 'status', '--port', [string]$port, '--listen', $BindHost, '--json')
            $statusCode = _Invoke $statusArgs
            if ($statusCode -eq 0) {
                _WS ("already running on port {0} — skipped" -f $port) -Level ok
                return [pscustomobject]@{ Name = $name; Port = $port; Status = 'skipped'; Code = 0 }
            }
        }

        $startArgs = @('--profile', $name, 'gateway', 'start', '--listen', $BindHost, '--port', [string]$port)
        _WS ("starting on port {0} ..." -f $port)
        $code = _Invoke $startArgs
        if ($code -eq 0) {
            _WS ("up on port {0}" -f $port) -Level ok
            return [pscustomobject]@{ Name = $name; Port = $port; Status = 'started'; Code = 0 }
        } else {
            _WS ("start failed (exit={0})" -f $code) -Level err
            return [pscustomobject]@{ Name = $name; Port = $port; Status = 'failed'; Code = $code }
        }
    } catch {
        _WS ("threw: {0}" -f $_.Exception.Message) -Level err
        return [pscustomobject]@{ Name = $name; Port = $port; Status = 'failed'; Code = 1; Error = $_.Exception.Message }
    }
} -ThrottleLimit $ThrottleLimit

# Aggregate. Results are emitted in completion order, not profile order;
# we sort by name for a deterministic summary table.
$started = ($results | Where-Object { $_.Status -eq 'started' }).Count
$skipped = ($results | Where-Object { $_.Status -eq 'skipped' }).Count
$failed  = ($results | Where-Object { $_.Status -eq 'failed'  }).Count

Write-Host ''
Write-Status "Per-profile result (sorted by name):" -Level info
foreach ($r in ($results | Sort-Object Name)) {
    $level = switch ($r.Status) { 'started' { 'ok' } 'skipped' { 'warn' } default { 'err' } }
    $line = if ($r.Status -eq 'started') { "up on port {0}" -f $r.Port }
            elseif ($r.Status -eq 'skipped') { "skipped (port {0})" -f $r.Port }
            else { "FAILED (port {0}, exit={1}{2})" -f $r.Port, $r.Code, ($(if ($r.Error) { " — $($r.Error)" } else { '' })) }
    Write-Status ("[{0,-30s}] {1}" -f $r.Name, $line) -Level $level
}

Write-Host ''
$summaryLevel = if ($failed -eq 0) { 'ok' } else { 'warn' }
Write-Status ("Summary: started={0} skipped={1} failed={2}" -f $started, $skipped, $failed) `
    -Level $summaryLevel

if ($failed -gt 0) {
    exit 1
}
