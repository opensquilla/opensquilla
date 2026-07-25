param(
  [Parameter(Mandatory = $true)]
  [string]$CandidateInstaller,
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[A-Za-z0-9._-]{1,80}$')]
  [string]$Label,
  [Parameter(Mandatory = $true)]
  [string]$CandidateManifest
)

$ErrorActionPreference = 'Stop'
$candidate = (Resolve-Path -LiteralPath $CandidateInstaller).Path
$candidateManifestPath = [IO.Path]::GetFullPath($CandidateManifest)
$sandbox = Join-Path $env:RUNNER_TEMP "opensquilla-release-clean-$Label"
$installDir = Join-Path $sandbox 'OpenSquilla'
$appData = Join-Path $sandbox 'appdata'
$localAppData = Join-Path $sandbox 'localappdata'
$userProfile = Join-Path $sandbox 'user-profile'
$userData = Join-Path $appData '@opensquilla\desktop-electron'
$profile = Join-Path $userData 'opensquilla'
$probe = Join-Path $PWD '.github\scripts\verify-release-profile-preservation.py'
$clientProbe = Join-Path $PWD '.github\scripts\verify-release-desktop-client.mjs'
$marker = "CLEAN_INSTALL_SESSION_$Label"

$env:APPDATA = $appData
$env:LOCALAPPDATA = $localAppData
$env:USERPROFILE = $userProfile
$env:OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE = '1'
$env:OPENSQUILLA_RECOVERY_OFFLINE = '1'
New-Item -ItemType Directory -Force `
  -Path $appData, $localAppData, $userProfile | Out-Null
if (Test-Path -LiteralPath $installDir) {
  throw 'Clean-install target directory must not exist before installation.'
}

function Get-DirectoryTreeSha256 {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Root
  )
  $rootPath = [IO.Path]::GetFullPath($Root)
  $entries = @(
    Get-ChildItem -LiteralPath $rootPath -File -Recurse |
      ForEach-Object {
        $relativePath = [IO.Path]::GetRelativePath($rootPath, $_.FullName).Replace('\', '/')
        $fileHash = (
          Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        "$relativePath`t$fileHash"
      } |
      Sort-Object -CaseSensitive
  )
  if ($entries.Count -eq 0) {
    throw "Cannot hash an empty candidate runtime tree: $rootPath"
  }
  $payload = [Text.Encoding]::UTF8.GetBytes(
    [string]::Join("`n", $entries) + "`n"
  )
  $hasher = [Security.Cryptography.SHA256]::Create()
  try {
    return ([BitConverter]::ToString($hasher.ComputeHash($payload))).Replace(
      '-',
      ''
    ).ToLowerInvariant()
  } finally {
    $hasher.Dispose()
  }
}

function Get-CleanInstalledProcessIds {
  $prefix = [IO.Path]::GetFullPath($installDir + [IO.Path]::DirectorySeparatorChar)
  $processIds = @()
  Get-Process -Name 'OpenSquilla', 'opensquilla-gateway' -ErrorAction SilentlyContinue |
    ForEach-Object {
      try {
        $path = if ($_.Path) { [IO.Path]::GetFullPath($_.Path) } else { '' }
        if ($path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
          $processIds += $_.Id
        }
      } catch {
        if ($_.Exception.Message -notmatch 'exited|cannot find|No process') { throw }
      }
    }
  return @($processIds)
}

function Stop-CleanInstalledProcesses {
  $deadline = [DateTime]::UtcNow.AddSeconds(30)
  while ($true) {
    $processIds = @(Get-CleanInstalledProcessIds)
    if ($processIds.Count -eq 0) { return }
    foreach ($processId in $processIds) {
      & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
      $taskkillExit = $LASTEXITCODE
      if (
        $taskkillExit -ne 0 -and
        (Get-Process -Id $processId -ErrorAction SilentlyContinue)
      ) {
        throw "Failed to stop installed process $processId (taskkill $taskkillExit)."
      }
    }
    if ([DateTime]::UtcNow -ge $deadline) {
      throw "Installed processes remained after cleanup: $((Get-CleanInstalledProcessIds) -join ', ')"
    }
    Start-Sleep -Milliseconds 250
  }
}

try {
  $installed = Start-Process -FilePath $candidate -ArgumentList @('/S', "/D=$installDir") `
    -Wait -PassThru
  if ($installed.ExitCode -ne 0) {
    throw "Clean candidate installation failed with exit code $($installed.ExitCode)."
  }
  $app = Join-Path $installDir 'OpenSquilla.exe'
  if (-not (Test-Path -LiteralPath $app -PathType Leaf)) {
    throw 'Clean candidate installation did not publish OpenSquilla.exe.'
  }
  $appAsar = Join-Path $installDir 'resources\app.asar'
  if (-not (Test-Path -LiteralPath $appAsar -PathType Leaf)) {
    throw 'Clean candidate installation did not publish resources\app.asar.'
  }
  $gatewayRoot = Join-Path $installDir 'resources\runtime\gateway'
  $gateway = Get-ChildItem -Path $gatewayRoot `
    -Filter 'opensquilla-gateway.exe' -File -Recurse | Select-Object -First 1
  if (-not $gateway) {
    throw 'Clean candidate installation did not publish opensquilla-gateway.exe.'
  }
  $candidateIdentity = [ordered]@{
    schema_version = 1
    candidate_installer_name = [IO.Path]::GetFileName($candidate)
    app_exe_sha256 = (Get-FileHash -LiteralPath $app -Algorithm SHA256).Hash.ToLowerInvariant()
    app_asar_sha256 = (Get-FileHash -LiteralPath $appAsar -Algorithm SHA256).Hash.ToLowerInvariant()
    gateway_sha256 = (
      Get-FileHash -LiteralPath $gateway.FullName -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    gateway_tree_sha256 = Get-DirectoryTreeSha256 -Root $gatewayRoot
  }
  $candidateManifestParent = Split-Path -Parent $candidateManifestPath
  if ($candidateManifestParent) {
    New-Item -ItemType Directory -Force -Path $candidateManifestParent | Out-Null
  }
  $candidateIdentity | ConvertTo-Json |
    Set-Content -LiteralPath $candidateManifestPath -Encoding utf8NoBOM

  & node $clientProbe `
    --executable $app `
    --user-data-dir $userData `
    --profile-home $profile `
    --probe $probe `
    --label $Label `
    --mode clean `
    --use-default-user-data
  if ($LASTEXITCODE -ne 0) {
    throw 'Clean installed packaged client failed onboarding, chat, or relaunch.'
  }
  Stop-CleanInstalledProcesses

  $uninstaller = Get-ChildItem -LiteralPath $installDir -Filter 'Uninstall*.exe' -File |
    Select-Object -First 1
  if (-not $uninstaller) { throw 'Clean candidate uninstaller was not found.' }
  $uninstall = Start-Process -FilePath $uninstaller.FullName -ArgumentList @('/S') `
    -Wait -PassThru
  if ($uninstall.ExitCode -ne 0) {
    throw "Clean candidate uninstaller failed with exit code $($uninstall.ExitCode)."
  }
  $deadline = [DateTime]::UtcNow.AddSeconds(30)
  while (
    (Test-Path -LiteralPath $app -PathType Leaf) -and
    [DateTime]::UtcNow -lt $deadline
  ) {
    Start-Sleep -Seconds 1
  }
  if (Test-Path -LiteralPath $app -PathType Leaf) {
    throw 'Clean candidate uninstaller did not remove OpenSquilla.exe.'
  }

  $snapshotRaw = & python $probe snapshot `
    --home $profile `
    --label $Label `
    --new-marker $marker `
    --skip-retained-verification
  if ($LASTEXITCODE -ne 0) {
    throw 'Clean candidate profile could not be read after uninstall.'
  }
  $snapshot = $snapshotRaw | ConvertFrom-Json
  if (
    $snapshot.new_marker_count -ne 1 -or
    @($snapshot.new_marker_session_keys).Count -ne 1
  ) {
    throw "Clean candidate uninstall did not preserve the created session: $snapshotRaw"
  }
} finally {
  Stop-CleanInstalledProcesses
}
