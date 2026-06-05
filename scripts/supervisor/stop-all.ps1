<#
.SYNOPSIS
    Stop the OpenSquilla gateway for every profile under the profiles root.

.DESCRIPTION
    Iterates the same discovery order as start-all.ps1 and calls
    `opensquilla --profile <name> gateway stop --port <port>`. A profile
    that is not running (or already stopped) is reported and skipped
    without failing the whole loop.

    A forced stop (-Force) is delegated to the CLI via `--force` so the
    underlying SIGTERM/timeout logic in opensquilla.cli.gateway_lifecycle
    stays the single source of truth for shutdown behaviour.

.PARAMETER ProfilesRoot
    Override the profiles-root directory.

.PARAMETER BasePort
    Must match the BasePort used by start-all.ps1 (or the override
    recorded in your autostart task). Default 18791.

.PARAMETER Host
    Bind address passed to `gateway stop`. Must match start-all. Default 127.0.0.1.

.EXAMPLE
    .\stop-all.ps1
    .\stop-all.ps1 -Force
#>
[CmdletBinding()]
param(
    [string] $ProfilesRoot,
    [int]    $BasePort = 18791,
    [string] $BindHost = '127.0.0.1',
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

$root   = Get-ProfilesRoot -Override $ProfilesRoot
$repo   = Get-OpensquillaRoot
$entries = Get-ProfileEntries -ProfilesRoot $root

if (-not $entries -or $entries.Count -eq 0) {
    Write-Status "No profiles found under $root." -Level warn
    return
}

$stopped = 0
$skipped = 0
$failed  = 0
foreach ($entry in $entries) {
    $port = Get-ProfilePort -Name $entry.Name -BasePort $BasePort -ProfilesRoot $root
    Write-Status ("[{0}] stopping (port {1}) ..." -f $entry.Name, $port)
    try {
        $stopArgs = @('--profile', $entry.Name, 'gateway', 'stop', '--listen', $BindHost, '--port', [string]$port)
        if ($Force) { $stopArgs += '--force' }
        $code = Invoke-Opensquilla -Repo $repo -Profile $entry.Path -Arguments $stopArgs
        # Exit code 0 = stopped; non-zero = nothing to stop / already stopped.
        if ($code -eq 0) {
            Write-Status ("[{0}] stopped" -f $entry.Name) -Level ok
            $stopped += 1
        } else {
            Write-Status ("[{0}] not running (exit={1})" -f $entry.Name, $code) -Level ok
            $skipped += 1
        }
    } catch {
        Write-Status ("[{0}] threw: {1}" -f $entry.Name, $_.Exception.Message) -Level err
        $failed += 1
    }
}

Write-Host ''
$summaryLevel = if ($failed -eq 0) { 'ok' } else { 'warn' }
Write-Status ("Summary: stopped={0} skipped={1} failed={2}" -f $stopped, $skipped, $failed) `
    -Level $summaryLevel

if ($failed -gt 0) {
    exit 1
}
