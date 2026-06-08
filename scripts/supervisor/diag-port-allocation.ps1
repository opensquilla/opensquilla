<#
.SYNOPSIS
    Diagnostic sweep: show each profile's REAL gateway task state
    (queried from opensquilla) plus port-binding status, so an
    operator can see "this profile is BUSY (our gateway running),
    that one is FREE (not_started, ready to start), the other is
    in CONFLICT (some other process squatting on the port)".

.DESCRIPTION
    For every discovered profile under the profiles root, this script
    runs `opensquilla --profile <name> gateway status --port <nominal>
    --json` via Get-GatewayState and reads back the canonical task
    state. It ALSO probes the TCP socket (Test-PortInUse) so the
    operator can distinguish "our gateway is bound and running" from
    "something else is on our port and we don't own it".

    This is the difference from the earlier TCP-only sweep: the
    BUSY/FREE/CONFLICT label here is grounded in opensquilla's
    real task state, not a bare socket check.

    Output is a table with columns:
      Profile   - profile name
      Nominal   - algorithm-computed port (default = BasePort, others
                  = BasePort+2 + index-among-non-default)
      State     - opensquilla task state: running / not_started /
                  unhealthy / target_mismatch / unknown
      Managed   - $true if opensquilla owns the PID on this port
      TCP       - free / busy (raw socket probe)
      Status    - derived label: FREE / BUSY (ours) / BUSY (other) /
                  BROKEN / WRONG-PORT
      Action    - what to do: "ready to start" / "already up" /
                  "port-hunt needed" / "investigate"

    Exit codes (for CI / orchestration preflight):
      0 - every profile is FREE or BUSY (ours) — safe to start-all
      1 - at least one profile is in CONFLICT / BROKEN / WRONG-PORT —
          operator should fix before running start-all

.PARAMETER ProfilesRoot
    Override the profiles-root directory. Defaults to
    $env:OPENSQUILLA_HOME or the script's built-in default.

.PARAMETER BasePort
    Must match the value used by start-all.ps1 for the per-profile
    port mapping to align with the algorithm.

.PARAMETER Ignore
    Optional list of profile names to skip. Mirrors the -Ignore
    flag on start-all.ps1 / status.ps1 so you can sanity-check
    "what would happen if I started all but these".

.PARAMETER BindHost
    Loopback address to probe. Default 127.0.0.1.

.EXAMPLE
    .\diag-port-allocation.ps1
    .\diag-port-allocation.ps1 -ProfilesRoot D:\work\profiles
    .\diag-port-allocation.ps1 -Ignore coder,test_*
    .\diag-port-allocation.ps1 | Out-Null  # CI gate; $? = $true if every profile is FREE or BUSY (ours)
#>
[CmdletBinding()]
param(
    [string]   $ProfilesRoot,
    [int]      $BasePort = 18791,
    [string[]] $Ignore = @(),
    [string]   $BindHost = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

$root = Get-ProfilesRoot -Override $ProfilesRoot
$entries = Get-ProfileEntries -ProfilesRoot $root -Ignore $Ignore

if (-not $entries -or $entries.Count -eq 0) {
    Write-Status "No profiles found under $root." -Level warn
    exit 0
}

# For each profile: nominal port + opensquilla state + TCP probe.
# Status/Action derived from those three.
$report    = @()
$nonDefault = 0
foreach ($entry in $entries) {
    if ($entry.Name -eq 'default') {
        $nominal = $BasePort
    } else {
        $nominal = $BasePort + 2 + $nonDefault
        $nonDefault += 1
    }

    # Real task state — query opensquilla
    $state = Get-GatewayState -Port $nominal -Profile $entry.Name -BindHost $BindHost

    # TCP probe — for the "is the port actually bindable" cross-check
    $tcpFree = -not (Test-PortInUse -Port $nominal -BindHost $BindHost)

    # Map real state + TCP to a single Status label and Action hint.
    $status = ''
    $action = ''
    switch ($state.State) {
        'not_started' {
            if ($tcpFree) {
                $status = 'FREE'
                $action = 'ready to start'
            } else {
                $status = 'CONFLICT'
                $action = 'port blocked by other process; port-hunt'
            }
            break
        }
        'running' {
            if ($state.Managed) {
                $status = 'BUSY (ours)'
                $action = 'already up; skip'
            } else {
                $status = 'CONFLICT (not ours)'
                $action = 'some other gateway on our port; port-hunt'
            }
            break
        }
        'unhealthy' {
            $status = 'BROKEN'
            $action = 'gateway unhealthy; investigate log'
            break
        }
        'target_mismatch' {
            $status = 'WRONG-PORT'
            $action = 'gateway on a different port; align or kill'
            break
        }
        'unknown' {
            $status = 'UNKNOWN'
            $action = "opensquilla probe failed: $($state.Error)"
            break
        }
        'no_opensquilla' {
            $status = 'NO-OPENSQUILLA'
            $action = 'install opensquilla first'
            break
        }
        default {
            $status = "STATE:$($state.State)"
            $action = 'investigate'
        }
    }

    $report += [pscustomobject]@{
        Profile = $entry.Name
        Nominal = $nominal
        State   = $state.State
        Managed = if ($state.State -in @('running','unhealthy','target_mismatch')) { $state.Managed } else { $null }
        TCP     = if ($tcpFree) { 'free' } else { 'busy' }
        Status  = $status
        Action  = $action
    }
}

# Render.
$report | Format-Table -AutoSize -Wrap

# Summary line.
$free      = ($report | Where-Object { $_.Status -eq 'FREE' }).Count
$busyOurs  = ($report | Where-Object { $_.Status -eq 'BUSY (ours)' }).Count
$conflict  = ($report | Where-Object { $_.Status -like 'CONFLICT*' }).Count
$broken    = ($report | Where-Object { $_.Status -eq 'BROKEN' }).Count
$wrong     = ($report | Where-Object { $_.Status -eq 'WRONG-PORT' }).Count
$unknown   = ($report | Where-Object { $_.Status -in @('UNKNOWN','NO-OPENSQUILLA') -or $_.Status -like 'STATE:*' }).Count
$total     = $report.Count

Write-Status (
    "Allocation: free=$free busy(ours)=$busyOurs conflict=$conflict broken=$broken wrong-port=$wrong unknown=$unknown total=$total"
) -Level info

# CI / orchestration hook: non-zero exit if any profile needs human
# intervention before start-all can run cleanly.
if (($conflict + $broken + $wrong + $unknown) -gt 0) {
    exit 1
}
exit 0
