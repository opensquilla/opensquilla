<#
.SYNOPSIS
    Start the OpenSquilla gateway for every profile under the profiles root.

.DESCRIPTION
    Discovers all subdirectories of the profiles root (each is one profile),
    computes a deterministic port per profile (`BasePort + sorted-index`),
    and invokes `opensquilla --profile <name> gateway start --port <port>`
    in series. A profile that fails to start does not stop the others — the
    loop logs the failure and continues.

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
#>
[CmdletBinding()]
param(
    [string] $ProfilesRoot,
    [int]    $BasePort = 18791,
    [string] $BindHost = '127.0.0.1',
    [switch] $SkipRunning,
    [string] $Repo
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

$root   = Get-ProfilesRoot -Override $ProfilesRoot
$cmd    = Get-OpensquillaCommand -Repo $Repo
$entries = Get-ProfileEntries -ProfilesRoot $root

if (-not $entries -or $entries.Count -eq 0) {
    Write-Status "No profiles found under $root. Run `opensquilla --profile <name> init` first." -Level warn
    return
}

Write-Status "Discovered $($entries.Count) profile(s) under $root" -Level info
Write-Status "Base port: $BasePort (each profile = base + sorted-index)" -Level info
switch ($cmd.Mode) {
    'installed'     { Write-Status "Mode: installed `opensquilla` at $($cmd.Exe)" -Level info }
    'uv-run-repo'   { Write-Status "Mode: uv run from $($cmd.Repo)" -Level info }
    default         { Write-Status "Mode: no `opensquilla` found; set PATH or pass -Repo" -Level err }
}
Write-Host ''

$started = 0
$skipped = 0
$failed  = 0
foreach ($entry in $entries) {
    $port = Get-ProfilePort -Name $entry.Name -BasePort $BasePort -ProfilesRoot $root
    Write-Status ("[{0}] starting on port {1} ..." -f $entry.Name, $port)
    try {
        if ($SkipRunning) {
            $statusArgs = @('--profile', $entry.Name, 'gateway', 'status', '--port', [string]$port, '--listen', $BindHost, '--json')
            $statusCode = Invoke-Opensquilla -Repo $repo -Profile $entry.Path -Arguments $statusArgs
            # The CLI exits 0 on healthy, 1/3 on unhealthy / not-started. Treat anything
            # that is NOT 0 as "not running" and try to start.
            if ($statusCode -eq 0) {
                Write-Status ("[{0}] already running on port {1} — skipped" -f $entry.Name, $port) -Level ok
                $skipped += 1
                continue
            }
        }
        $startArgs = @('--profile', $entry.Name, 'gateway', 'start', '--listen', $BindHost, '--port', [string]$port)
        $code = Invoke-Opensquilla -Repo $repo -Profile $entry.Path -Arguments $startArgs
        if ($code -eq 0) {
            Write-Status ("[{0}] up on port {1}" -f $entry.Name, $port) -Level ok
            $started += 1
        } else {
            Write-Status ("[{0}] start failed (exit={1})" -f $entry.Name, $code) -Level err
            $failed += 1
        }
    } catch {
        Write-Status ("[{0}] threw: {1}" -f $entry.Name, $_.Exception.Message) -Level err
        $failed += 1
    }
}

Write-Host ''
$summaryLevel = if ($failed -eq 0) { 'ok' } else { 'warn' }
Write-Status ("Summary: started={0} skipped={1} failed={2}" -f $started, $skipped, $failed) `
    -Level $summaryLevel

if ($failed -gt 0) {
    exit 1
}
