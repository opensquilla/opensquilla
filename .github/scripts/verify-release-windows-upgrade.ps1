param(
  [Parameter(Mandatory = $true)]
  [string]$CandidateInstaller,
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[A-Za-z0-9._-]{1,80}$')]
  [string]$Label,
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^v[0-9]+\.[0-9]+\.[0-9]+(rc[0-9]+)?$')]
  [string]$OldTag,
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^OpenSquilla-[A-Za-z0-9.-]+-win-x64\.exe$')]
  [string]$OldAsset,
  [Parameter(Mandatory = $true)]
  [ValidateSet('pre-rc3', 'modern')]
  [string]$Layout,
  [Parameter(Mandatory = $true)]
  [string]$CandidateManifest,
  [switch]$VerifyConfigReset,
  [switch]$VerifyCliImport,
  [switch]$VerifyInspectFailure,
  [switch]$VerifyLongRunningUpdateBanner
)

$ErrorActionPreference = 'Stop'
$repository = 'opensquilla/opensquilla'
$candidate = (Resolve-Path -LiteralPath $CandidateInstaller).Path
$candidateName = [IO.Path]::GetFileName($candidate)
$candidateManifestPath = (Resolve-Path -LiteralPath $CandidateManifest).Path
$candidateIdentity = Get-Content -Raw -LiteralPath $candidateManifestPath | ConvertFrom-Json
if (
  $candidateIdentity.schema_version -ne 1 -or
  $candidateIdentity.candidate_installer_name -ne $candidateName -or
  $candidateIdentity.app_exe_sha256 -notmatch '^[0-9a-f]{64}$' -or
  $candidateIdentity.app_asar_sha256 -notmatch '^[0-9a-f]{64}$' -or
  $candidateIdentity.gateway_sha256 -notmatch '^[0-9a-f]{64}$' -or
  $candidateIdentity.gateway_tree_sha256 -notmatch '^[0-9a-f]{64}$'
) {
  throw "Invalid or mismatched candidate identity manifest: $candidateManifestPath"
}
$sandbox = Join-Path $env:RUNNER_TEMP "opensquilla-release-preservation-$Label"
$oldDir = Join-Path $sandbox 'old'
$installDir = Join-Path $sandbox 'OpenSquilla'
$appData = Join-Path $sandbox 'appdata'
$localAppData = Join-Path $sandbox 'localappdata'
$userProfile = Join-Path $sandbox 'user-profile'
$userData = Join-Path $appData '@opensquilla\desktop-electron'
$profile = Join-Path $userData 'opensquilla'
$probe = Join-Path $PWD '.github\scripts\verify-release-profile-preservation.py'
$clientProbe = Join-Path $PWD '.github\scripts\verify-release-desktop-client.mjs'
$releasedSessionSeed = Join-Path $PWD '.github\scripts\seed-released-desktop-session.mjs'
$updateBannerSmoke = Join-Path $PWD 'desktop\electron\scripts\test-packaged-update-banner.mjs'
$retainedMarker = "HISTORICAL_RELEASE_SESSION_$Label"
$env:APPDATA = $appData
$env:LOCALAPPDATA = $localAppData
$env:USERPROFILE = $userProfile
$env:OPENSQUILLA_DESKTOP_DISABLE_AUTO_UPDATE = '1'
$env:OPENSQUILLA_RECOVERY_OFFLINE = '1'

New-Item -ItemType Directory -Force `
  -Path $oldDir, $appData, $localAppData, $userProfile | Out-Null
gh release download $OldTag --repo $repository --pattern $OldAsset --dir $oldDir
if ($LASTEXITCODE -ne 0) { throw "Failed to download the $OldTag Windows installer." }
$oldInstaller = Join-Path $oldDir $OldAsset

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

function Get-InstalledProcessIds {
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

function Stop-InstalledProcesses {
  $deadline = [DateTime]::UtcNow.AddSeconds(30)
  while ($true) {
    $processIds = @(Get-InstalledProcessIds)
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
      throw "Installed processes remained after cleanup: $((Get-InstalledProcessIds) -join ', ')"
    }
    Start-Sleep -Milliseconds 250
  }
}

try {
  $old = Start-Process -FilePath $oldInstaller -ArgumentList @('/S', "/D=$installDir") `
    -Wait -PassThru
  if ($old.ExitCode -ne 0) {
    throw "$OldTag installer failed with exit code $($old.ExitCode)."
  }

  python $probe seed `
    --home $profile `
    --label $Label `
    --layout $Layout `
    --source-tag $OldTag `
    --profile-only
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to seed the synthetic $OldTag profile."
  }
  $oldGateway = Get-ChildItem -Path (Join-Path $installDir 'resources\runtime\gateway') `
    -Filter 'opensquilla-gateway.exe' -File -Recurse | Select-Object -First 1
  if (-not $oldGateway) { throw "The $OldTag packaged gateway was not found." }
  & node $releasedSessionSeed `
    --gateway $oldGateway.FullName `
    --profile-home $profile `
    --layout $Layout `
    --label $Label
  if ($LASTEXITCODE -ne 0) {
    throw "The $OldTag packaged runtime failed to create a retained session."
  }
  python $probe verify `
    --home $profile `
    --label $Label `
    --retained-marker $retainedMarker
  if ($LASTEXITCODE -ne 0) {
    throw "The $OldTag packaged runtime did not persist its retained session."
  }

  $installed = Start-Process -FilePath $candidate -ArgumentList @('/S', "/D=$installDir") `
    -Wait -PassThru
  if ($installed.ExitCode -ne 0) {
    throw "Candidate installer failed with exit code $($installed.ExitCode)."
  }
  python $probe verify `
    --home $profile `
    --label $Label `
    --retained-marker $retainedMarker
  if ($LASTEXITCODE -ne 0) {
    throw "Candidate installation changed $OldTag profile data."
  }

  $app = Join-Path $installDir 'OpenSquilla.exe'
  if (-not (Test-Path -LiteralPath $app -PathType Leaf)) {
    throw 'Candidate installation did not publish OpenSquilla.exe.'
  }
  $appAsar = Join-Path $installDir 'resources\app.asar'
  if (-not (Test-Path -LiteralPath $appAsar -PathType Leaf)) {
    throw 'Candidate installation did not publish resources\app.asar.'
  }
  $gatewayRoot = Join-Path $installDir 'resources\runtime\gateway'
  $gateway = Get-ChildItem -Path $gatewayRoot `
    -Filter 'opensquilla-gateway.exe' -File -Recurse | Select-Object -First 1
  if (-not $gateway) { throw 'Packaged recovery CLI was not found.' }
  $installedAppExeHash = (
    Get-FileHash -LiteralPath $app -Algorithm SHA256
  ).Hash.ToLowerInvariant()
  $installedAppAsarHash = (
    Get-FileHash -LiteralPath $appAsar -Algorithm SHA256
  ).Hash.ToLowerInvariant()
  $installedGatewayHash = (
    Get-FileHash -LiteralPath $gateway.FullName -Algorithm SHA256
  ).Hash.ToLowerInvariant()
  $installedGatewayTreeHash = Get-DirectoryTreeSha256 -Root $gatewayRoot
  if (
    $installedAppExeHash -ne $candidateIdentity.app_exe_sha256 -or
    $installedAppAsarHash -ne $candidateIdentity.app_asar_sha256 -or
    $installedGatewayHash -ne $candidateIdentity.gateway_sha256 -or
    $installedGatewayTreeHash -ne $candidateIdentity.gateway_tree_sha256
  ) {
    throw 'Candidate installer did not replace the old application with the verified candidate.'
  }
  if ($VerifyInspectFailure) {
    & node $clientProbe `
      --executable $app `
      --user-data-dir $userData `
      --profile-home $profile `
      --probe $probe `
      --label $Label `
      --mode upgrade `
      --use-default-user-data `
      --force-inspect-failure `
      --retained-marker $retainedMarker
    if ($LASTEXITCODE -ne 0) {
      throw 'Candidate packaged inspector-failure smoke failed.'
    }
    Stop-InstalledProcesses
  }

  & node $clientProbe `
    --executable $app `
    --user-data-dir $userData `
    --profile-home $profile `
    --probe $probe `
    --label $Label `
    --mode upgrade `
    --use-default-user-data `
    --retained-marker $retainedMarker
  if ($LASTEXITCODE -ne 0) {
    throw "Candidate packaged-client upgrade smoke failed for $OldTag."
  }
  Stop-InstalledProcesses

  if ($VerifyLongRunningUpdateBanner) {
    & node $updateBannerSmoke `
      --executable $app `
      --user-data-dir $userData `
      --candidate-name $candidateName
    if ($LASTEXITCODE -ne 0) {
      throw 'Candidate long-running update-banner smoke failed.'
    }
  }
  Stop-InstalledProcesses

  $inspectionRaw = & $gateway.FullName recovery inspect --home $profile --json
  if ($LASTEXITCODE -ne 0) { throw 'Packaged recovery inspection failed.' }
  $inspection = $inspectionRaw | ConvertFrom-Json
  if ($inspection.outcome -notin @('ready', 'attention')) {
    throw "Unsafe packaged profile inspection: $inspectionRaw"
  }
  if ([IO.Path]::GetFullPath($inspection.primary_home) -ne [IO.Path]::GetFullPath($profile)) {
    throw 'Candidate selected a different primary profile after upgrade.'
  }
  if (
    [IO.Path]::GetFullPath($inspection.effective_workspace) -ne
    [IO.Path]::GetFullPath((Join-Path $profile 'workspace'))
  ) {
    throw 'Candidate selected a different workspace after upgrade.'
  }
  $configuredState = @($inspection.candidates | Where-Object {
    $_.kind -eq 'state' -and $_.configured -and $_.valid
  })
  if (
    $configuredState.Count -ne 1 -or
    [IO.Path]::GetFullPath($configuredState[0].path) -ne
    [IO.Path]::GetFullPath((Join-Path $profile 'state'))
  ) {
    throw 'Candidate selected a different state directory after upgrade.'
  }
  python $probe verify `
    --home $profile `
    --label $Label `
    --retained-marker $retainedMarker
  if ($LASTEXITCODE -ne 0) {
    throw "Candidate launch changed $OldTag retained profile data."
  }

  if ($VerifyConfigReset) {
    $resetLabel = "$Label-config-reset"
    $resetUserData = Join-Path $sandbox 'config-reset-user-data\OpenSquilla'
    $resetProfile = Join-Path $resetUserData 'opensquilla'
    python $probe seed `
      --home $resetProfile `
      --label $resetLabel `
      --layout modern `
      --source-tag v0.5.0
    if ($LASTEXITCODE -ne 0) {
      throw 'Failed to seed the config-reset profile.'
    }
    Set-Content -LiteralPath (Join-Path $resetProfile 'config.toml') `
      -Value 'state_dir = [' `
      -Encoding utf8NoBOM
    & node $clientProbe `
      --executable $app `
      --user-data-dir $resetUserData `
      --profile-home $resetProfile `
      --probe $probe `
      --label $resetLabel `
      --mode upgrade `
      --allow-config-change
    if ($LASTEXITCODE -ne 0) {
      throw 'Candidate config-reset packaged-client smoke failed.'
    }
    Stop-InstalledProcesses
    python $probe verify `
      --home $resetProfile `
      --label $resetLabel `
      --allow-config-change
    if ($LASTEXITCODE -ne 0) {
      throw 'Candidate config reset changed the retained session.'
    }
  }

  if ($VerifyCliImport) {
    $cliLabel = "$Label-cli031"
    $cliSource = Join-Path $sandbox 'cli-home\.opensquilla'
    $cliUserData = Join-Path $sandbox 'cli-import-user-data\OpenSquilla'
    $cliTarget = Join-Path $cliUserData 'opensquilla'
    $cliLockRoot = Join-Path $sandbox 'cli-lock-root'
    New-Item -ItemType Directory -Force -Path $cliUserData, $cliLockRoot | Out-Null
    python $probe seed `
      --home $cliSource `
      --label $cliLabel `
      --layout modern `
      --source-tag v0.3.1
    if ($LASTEXITCODE -ne 0) {
      throw 'Failed to seed the frozen v0.3.1 CLI profile.'
    }
    $previousStateDir = $env:OPENSQUILLA_STATE_DIR
    $previousConfigPath = $env:OPENSQUILLA_GATEWAY_CONFIG_PATH
    $previousLockGate = $env:OPENSQUILLA_TEST_PROFILE_LOCK_ROOT
    $previousLockRoot = $env:OPENSQUILLA_USER_STATE_DIR
    try {
      $env:OPENSQUILLA_STATE_DIR = $cliTarget
      $env:OPENSQUILLA_GATEWAY_CONFIG_PATH = Join-Path $cliTarget 'config.toml'
      $env:OPENSQUILLA_TEST_PROFILE_LOCK_ROOT = '1'
      $env:OPENSQUILLA_USER_STATE_DIR = $cliLockRoot
      $cliImportRaw = & $gateway.FullName migrate opensquilla `
        --source $cliSource `
        --kind cli-home `
        --apply `
        --json
      if ($LASTEXITCODE -ne 0) { throw 'Packaged v0.3.1 CLI import failed.' }
      $cliImportRaw | Set-Content -LiteralPath (Join-Path $sandbox 'cli-import.json')
      $cliImport = $cliImportRaw | ConvertFrom-Json
      if (-not $cliImport.apply) { throw 'Packaged v0.3.1 CLI import did not apply.' }
      if (@($cliImport.items | Where-Object { $_.status -eq 'error' }).Count -ne 0) {
        throw 'Packaged v0.3.1 CLI import reported an error item.'
      }
      if ($cliImport.preflight.session_count -ne 1) {
        throw 'Packaged v0.3.1 CLI import did not discover the retained session.'
      }
    } finally {
      $env:OPENSQUILLA_STATE_DIR = $previousStateDir
      $env:OPENSQUILLA_GATEWAY_CONFIG_PATH = $previousConfigPath
      $env:OPENSQUILLA_TEST_PROFILE_LOCK_ROOT = $previousLockGate
      $env:OPENSQUILLA_USER_STATE_DIR = $previousLockRoot
    }
    & node $clientProbe `
      --executable $app `
      --user-data-dir $cliUserData `
      --profile-home $cliTarget `
      --probe $probe `
      --label $cliLabel `
      --mode upgrade `
      --allow-config-change
    if ($LASTEXITCODE -ne 0) {
      throw 'Candidate v0.3.1 CLI-to-Desktop packaged-client smoke failed.'
    }
    Stop-InstalledProcesses
    python $probe verify `
      --home $cliTarget `
      --label $cliLabel `
      --allow-config-change
    if ($LASTEXITCODE -ne 0) {
      throw 'Candidate changed the imported v0.3.1 CLI retained session.'
    }
    python $probe verify --home $cliSource --label $cliLabel
    if ($LASTEXITCODE -ne 0) {
      throw 'Candidate or importer changed the v0.3.1 CLI source profile.'
    }
  }

  $uninstaller = Get-ChildItem -LiteralPath $installDir -Filter 'Uninstall*.exe' -File |
    Select-Object -First 1
  if (-not $uninstaller) { throw 'Candidate Windows uninstaller was not found.' }
  $uninstall = Start-Process -FilePath $uninstaller.FullName -ArgumentList @('/S') `
    -Wait -PassThru
  if ($uninstall.ExitCode -ne 0) {
    throw "Candidate uninstaller failed with exit code $($uninstall.ExitCode)."
  }
  $deadline = [DateTime]::UtcNow.AddSeconds(30)
  while (
    (Test-Path -LiteralPath $app -PathType Leaf) -and
    [DateTime]::UtcNow -lt $deadline
  ) {
    Start-Sleep -Seconds 1
  }
  if (Test-Path -LiteralPath $app -PathType Leaf) {
    throw 'Candidate uninstaller did not remove OpenSquilla.exe.'
  }
  python $probe verify `
    --home $profile `
    --label $Label `
    --retained-marker $retainedMarker
  if ($LASTEXITCODE -ne 0) {
    throw "Candidate uninstaller changed $OldTag profile data."
  }
} finally {
  Stop-InstalledProcesses
}
