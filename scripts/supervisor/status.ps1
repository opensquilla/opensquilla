<#
.SYNOPSIS
    Show a one-row-per-profile status table for all OpenSquilla gateways.

.DESCRIPTION
    Runs `opensquilla --profile <name> gateway status --json` for each
    discovered profile, parses the JSON payload, and prints a compact
    aligned table with: name, state, host, port, pid, log path.

    Profiles with no gateway running show "not_started" instead of
    failing the table render.

.PARAMETER ProfilesRoot
    Override the profiles-root directory.

.PARAMETER BasePort
    Must match the value used by start-all.ps1 for the per-profile
    port mapping to align with the CLI's `gateway status --port` lookup.

.EXAMPLE
    .\status.ps1
    .\status.ps1 -ProfilesRoot D:\work\profiles
#>
[CmdletBinding()]
param(
    [string] $ProfilesRoot,
    [int]    $BasePort = 18791
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

$rows = @()
foreach ($entry in $entries) {
    $port = Get-ProfilePort -Name $entry.Name -BasePort $BasePort -ProfilesRoot $root
    $env:OPENSQUILLA_HOME = $root
    $env:OPENSQUILLA_PROFILE = $entry.Name
    Push-Location -LiteralPath $repo
    try {
        $raw = & uv run opensquilla --profile $entry.Name gateway status --port $port --json 2>$null
        $parsed = $null
        if ($raw) { $parsed = $raw | ConvertFrom-Json -ErrorAction SilentlyContinue }
    } finally {
        Pop-Location
    }

    if ($parsed) {
        $rows += [pscustomobject]@{
            Profile = $entry.Name
            State   = [string]$parsed.state
            Port    = [int]$parsed.port
            Host    = [string]$parsed.host
            Pid     = if ($parsed.pid) { [int]$parsed.pid } else { '-' }
            Log     = [string]$parsed.logPath
        }
    } else {
        $rows += [pscustomobject]@{
            Profile = $entry.Name
            State   = 'unknown'
            Port    = $port
            Host    = '-'
            Pid     = '-'
            Log     = '-'
        }
    }
}

# Render aligned table. PowerShell 5.1 lacks Format-Table auto-width on
# all hosts, so compute column widths explicitly.
function Format-Table {
    param([object[]] $Data)
    $cols = 'Profile','State','Port','Host','Pid','Log'
    $widths = @{}
    foreach ($c in $cols) { $widths[$c] = $c.Length }
    foreach ($r in $Data) {
        foreach ($c in $cols) {
            $v = [string]$r.$c
            if ($v.Length -gt $widths[$c]) { $widths[$c] = $v.Length }
        }
    }
    $header = ($cols | ForEach-Object { $_.PadRight($widths[$_]) }) -join '  '
    Write-Host $header -ForegroundColor Cyan
    Write-Host ('-' * $header.Length) -ForegroundColor DarkGray
    foreach ($r in $Data) {
        $line = ($cols | ForEach-Object { ([string]$r.$_).PadRight($widths[$_]) }) -join '  '
        $color = switch ($r.State) {
            'running'     { 'Green' }
            'unhealthy'   { 'Red' }
            'not_started' { 'DarkGray' }
            default       { 'Yellow' }
        }
        Write-Host $line -ForegroundColor $color
    }
}

Format-Table -Data $rows

# Non-zero exit if anything is not running AND has a config (so an
# un-initialized profile doesn't show as a failure).
$misconfigured = $rows | Where-Object { $_.State -notin @('running','not_started') }
$uninitialized = $entries | Where-Object { -not $_.HasConfig }
if ($misconfigured.Count -gt 0) {
    Write-Status ("{0} profile(s) need attention (unhealthy/stale/target_mismatch)" -f $misconfigured.Count) -Level warn
    exit 1
}
