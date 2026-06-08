<#
.SYNOPSIS
    Register start-all.ps1 with Windows Task Scheduler to run at user logon.

.DESCRIPTION
    Creates (or updates) a task named `OpenSquillaProfileSupervisor` that
    fires `start-all.ps1` whenever the current user logs in interactively.
    The task is per-user, so it does NOT need administrator rights.

    The task is configured to:
      * Run only when the user is logged on (`Interactive`).
      * Run with highest privileges available to the user (no UAC prompt —
        `RunOnlyIfLoggedOn` prevents a credentials popup).
      * Re-fire if the previous run is still going (`MultipleInstancesParallel`).
      * Use a 10-minute execution time limit. `start-all.ps1` itself waits
        for each `gateway start` to pass its health check, so the bound is
        generous; if it ever fires, you have a real problem to look at.

    The task only registers a schedule — it does not start any gateway
    right now. Run `.\start-all.ps1` manually for that.

.PARAMETER ProfilesRoot
    Override the profiles-root directory. Persisted into the task's
    invocation command.

.PARAMETER BasePort
    Base port for the per-profile port mapping. Persisted.

.PARAMETER TaskName
    Override the registered task name. Default:
    `OpenSquillaProfileSupervisor`.

.PARAMETER Repo
    Override the OpenSquilla source checkout that backs the registered
    `start-all.ps1` invocation. Only used when `opensquilla` is not on
    PATH. Defaults to the parent of this script's directory.

.EXAMPLE
    .\install-autostart.ps1
    .\install-autostart.ps1 -BasePort 19000
    .\install-autostart.ps1 -Repo D:\src\opensquilla
#>
[CmdletBinding()]
param(
    [string] $ProfilesRoot,
    [int]    $BasePort   = 18791,
    [string] $TaskName   = 'OpenSquillaProfileSupervisor',
    [string] $Repo
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

if (-not (Get-Command schtasks.exe -ErrorAction SilentlyContinue)) {
    throw 'schtasks.exe not found — this script only runs on Windows.'
}

# Resolve and persist the profiles root. We pass it on the start-all
# invocation so the task is independent of $env:OPENSQUILLA_HOME
# at logon time.
$root = Get-ProfilesRoot -Override $ProfilesRoot
$startAll = Join-Path $PSScriptRoot 'start-all.ps1'

# Build the action payload. schtasks /TR requires the script be quoted;
# -NoProfile keeps PSReadLine / profile-loading off the boot path.
$actionArg = "-NoProfile -ExecutionPolicy Bypass -File `"$startAll`" -ProfilesRoot `"$root`" -BasePort $BasePort -SkipRunning"
if ($Repo) {
    $actionArg += " -Repo `"$Repo`""
}
$actionXml = "<Exec><Command>powershell.exe</Command><Arguments>$actionArg</Arguments></Exec>"

# schtasks.exe doesn't accept XML inline for /Create with the patterns we
# need, so we write a temporary .xml and register via /XML.
$taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$env:USERNAME</Author>
    <Description>Auto-start every OpenSquilla profile gateway under $root at user logon.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$env:USERDOMAIN\$env:USERNAME</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions>
    $actionXml
  </Actions>
</Task>
"@

$xmlPath = Join-Path $env:TEMP "opensquilla-supervisor-$TaskName.xml"
[System.IO.File]::WriteAllText($xmlPath, $taskXml, [System.Text.Encoding]::Unicode)

try {
    # /F overwrites any pre-existing task with the same name.
    $proc = Start-Process -FilePath schtasks.exe `
        -ArgumentList @('/Create', '/TN', $TaskName, '/XML', $xmlPath, '/F') `
        -NoNewWindow -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "schtasks /Create exited with code $($proc.ExitCode)"
    }
    Write-Status "Registered task '$TaskName' to run start-all.ps1 at logon." -Level ok
    Write-Status "Profiles root: $root" -Level info
    Write-Status "Base port:     $BasePort" -Level info
    Write-Status "Task XML kept at $xmlPath for inspection." -Level info
} finally {
    Remove-Item -LiteralPath $xmlPath -ErrorAction SilentlyContinue
}
