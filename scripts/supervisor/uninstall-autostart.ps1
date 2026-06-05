<#
.SYNOPSIS
    Remove the OpenSquilla multi-profile supervisor from Task Scheduler.

.DESCRIPTION
    Deletes the task registered by install-autostart.ps1. Idempotent: a
    missing task is reported as a no-op rather than an error.

.PARAMETER TaskName
    Task to remove. Default: `OpenSquillaProfileSupervisor`.
#>
[CmdletBinding()]
param(
    [string] $TaskName = 'OpenSquillaProfileSupervisor'
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command schtasks.exe -ErrorAction SilentlyContinue)) {
    throw 'schtasks.exe not found — this script only runs on Windows.'
}

# /Query first so we can give a clear "nothing to do" message instead of
# letting schtasks print its own (cryptic) error.
$query = Start-Process -FilePath schtasks.exe `
    -ArgumentList @('/Query', '/TN', $TaskName) `
    -NoNewWindow -Wait -PassThru
if ($query.ExitCode -ne 0) {
    Write-Status "Task '$TaskName' is not registered — nothing to do." -Level warn
    return
}

$del = Start-Process -FilePath schtasks.exe `
    -ArgumentList @('/Delete', '/TN', $TaskName, '/F') `
    -NoNewWindow -Wait -PassThru
if ($del.ExitCode -ne 0) {
    throw "schtasks /Delete exited with code $($del.ExitCode)"
}
Write-Status "Removed task '$TaskName'." -Level ok
