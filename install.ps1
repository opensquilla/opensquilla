# install.ps1 — user-local OpenSquilla installer (no admin).
#
# Installer contract:
#   - installs into a user-owned prefix (never Program Files or system32)
#   - prefers uv tool install; falls back to pip --user; errors clearly if neither exists
#   - defaults to the "recommended" runtime profile (memory + bundled v4 router)
#     and allows `$env:OPENSQUILLA_INSTALL_PROFILE="core"` to opt back down
#   - prints a post-install banner documenting the default bind
#     (127.0.0.1:18790) and the explicit opt-in required to expose the gateway
#     on the network (-Listen 0.0.0.0 or $env:OPENSQUILLA_LISTEN="0.0.0.0")
#   - adds an extra WARNING when the operator requested network exposure at
#     install time via $env:OPENSQUILLA_LISTEN="0.0.0.0"
#
# Dry-run: set $env:OPENSQUILLA_INSTALL_DRY_RUN="1" to print the install plan +
# banner without touching the system.

param(
    [string]$Profile = "",
    [string[]]$Extras = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- prefix resolution ------------------------------------------------------

if ($env:OPENSQUILLA_PREFIX) {
    $prefix = $env:OPENSQUILLA_PREFIX
} elseif ($env:LOCALAPPDATA) {
    $prefix = Join-Path $env:LOCALAPPDATA 'opensquilla'
} else {
    $prefix = Join-Path $HOME '.local'
}

$dryRun = $env:OPENSQUILLA_INSTALL_DRY_RUN -eq '1'
$profile = if ($Profile) {
    $Profile
} elseif ($env:OPENSQUILLA_INSTALL_PROFILE) {
    $env:OPENSQUILLA_INSTALL_PROFILE
} else {
    'recommended'
}

$validExtras = @(
    'feishu',
    'telegram',
    'dingtalk',
    'wecom',
    'qq',
    'msteams',
    'matrix',
    'matrix-e2e',
    'document-extras'
)

function Split-InstallExtras {
    param([string[]]$Values)

    $items = New-Object System.Collections.Generic.List[string]
    foreach ($value in $Values) {
        if (-not $value) {
            continue
        }
        foreach ($part in ($value -split '[,\s]+')) {
            $item = $part.Trim()
            if ($item -and -not $items.Contains($item)) {
                $items.Add($item)
            }
        }
    }
    return $items.ToArray()
}

$extraInputs = @()
if ($env:OPENSQUILLA_INSTALL_EXTRAS) {
    $extraInputs += $env:OPENSQUILLA_INSTALL_EXTRAS
}
$extraInputs += $Extras
$installExtras = @(Split-InstallExtras $extraInputs)

$unknownExtras = @($installExtras | Where-Object { $_ -notin $validExtras })
if ($unknownExtras.Count -gt 0) {
    Write-Error "install.ps1: unsupported extras: $($unknownExtras -join ', '). Supported extras: $($validExtras -join ', ')."
    exit 1
}

switch ($profile) {
    'core' { $targetExtras = @() }
    'minimal' { $profile = 'core'; $targetExtras = @() }
    'recommended' { $targetExtras = @('recommended') }
    default {
        Write-Error "install.ps1: unsupported OPENSQUILLA_INSTALL_PROFILE='$profile'. Supported profiles: core, recommended."
        exit 1
    }
}

$targetExtras += $installExtras
$installTarget = if ($targetExtras.Count -gt 0) {
    ".[$($targetExtras -join ',')]"
} else {
    '.'
}

function Test-SquillaRouterAssets {
    param(
        [switch]$WarnOnly
    )

    if ($profile -ne 'recommended') {
        return
    }

    $modelRoot = 'src/opensquilla/squilla_router/models'
    $required = @(
        "$modelRoot/v4.2_phase3_inference/lgbm_main.bin",
        "$modelRoot/v4.2_phase3_inference/router.runtime.yaml",
        "$modelRoot/v4.2_phase3_inference/mlp/model.onnx",
        "$modelRoot/v4.2_phase3_inference/features/tfidf.pkl",
        "$modelRoot/v4.2_phase3_inference/bge_onnx/model.onnx"
    )
    $pointerLine = 'version https://git-lfs.github.com/spec/v1'
    $missing = New-Object System.Collections.Generic.List[string]
    $pointers = New-Object System.Collections.Generic.List[string]

    foreach ($path in $required) {
        if (-not (Test-Path $path -PathType Leaf)) {
            $missing.Add($path)
            continue
        }
        $firstLine = Get-Content -Path $path -TotalCount 1 -ErrorAction SilentlyContinue
        if ($firstLine -eq $pointerLine) {
            $pointers.Add($path)
        }
    }

    if ($missing.Count -gt 0 -or $pointers.Count -gt 0) {
        if ($WarnOnly) {
            Write-Host 'install.ps1: dry-run note — real recommended install would fail until bundled squilla-router v4 assets are available in this checkout.'
        }
        else {
            Write-Error 'install.ps1: bundled squilla-router v4 assets are unavailable in this checkout.'
        }
        if ($missing.Count -gt 0) {
            $message = "install.ps1: missing squilla-router assets: $($missing -join ', ')"
            if ($WarnOnly) { Write-Host $message } else { Write-Error $message }
        }
        if ($pointers.Count -gt 0) {
            $message = "install.ps1: Git LFS pointer files detected: $($pointers -join ', ')"
            if ($WarnOnly) { Write-Host $message } else { Write-Error $message }
        }
        $lfsMessage = 'install.ps1: run `git lfs install` once, then `git lfs pull --include="src/opensquilla/squilla_router/models/**"`.'
        $coreMessage = 'install.ps1: or retry with `$env:OPENSQUILLA_INSTALL_PROFILE="core"` for the minimal runtime.'
        if ($WarnOnly) {
            Write-Host $lfsMessage
            Write-Host $coreMessage
            return
        }
        Write-Error $lfsMessage
        Write-Error $coreMessage
        exit 1
    }
}

# --- installer selection ----------------------------------------------------

$installer = $null
$installArgs = @()

if (Get-Command uv -ErrorAction SilentlyContinue) {
    $installer = 'uv'
    $installArgs = @('tool', 'install', '--force', '--reinstall-package', 'opensquilla', $installTarget)
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $installer = 'pip'
    $installArgs = @('-m', 'pip', 'install', '--user', $installTarget)
} else {
    Write-Error "install.ps1: neither 'uv' nor 'python' is available on PATH. Install uv (https://docs.astral.sh/uv/) or Python 3.12+ and retry."
    exit 1
}

$installCmd = if ($installer -eq 'uv') {
    "uv $($installArgs -join ' ')"
} else {
    "python $($installArgs -join ' ')"
}

# --- banner -----------------------------------------------------------------

function Write-Banner {
    @"
────────────────────────────────────────────────────────────────────────────
OpenSquilla installed via $installer → $prefix (profile: $profile)
Extras: $(if ($installExtras.Count -gt 0) { $installExtras -join ', ' } else { 'none' })

Default gateway bind: 127.0.0.1:18790 (loopback only)
Network exposure is opt-in only. To expose the gateway on the network you
must use one of:
  - CLI flag:  opensquilla gateway run --listen 0.0.0.0
  - Env var:   `$env:OPENSQUILLA_LISTEN="0.0.0.0"; opensquilla gateway run

Reminder: only expose 0.0.0.0 behind a trusted reverse proxy or VPN. The
gateway's first-class auth assumes loopback-scope by default.
────────────────────────────────────────────────────────────────────────────
"@ | Write-Host
}

function Write-ListenWarning {
    @"
⚠  WARNING: you have selected network-exposed default — ensure you
   understand the blast radius. The gateway will bind to 0.0.0.0 and be
   reachable from every interface on this host.
"@ | Write-Host
}

if ($dryRun) {
    Write-Host "install.ps1: dry-run — would run: $installCmd"
    Write-Host "install.ps1: dry-run — prefix: $prefix"
    Test-SquillaRouterAssets -WarnOnly
    Write-Banner
    if ($env:OPENSQUILLA_LISTEN -eq '0.0.0.0') {
        Write-ListenWarning
    }
    exit 0
}

# --- execute ---------------------------------------------------------------

Test-SquillaRouterAssets

Write-Host "install.ps1: installing via $installer into prefix $prefix"
Write-Host "install.ps1: running: $installCmd"
if ($installer -eq 'uv') {
    & uv @installArgs
} else {
    & python @installArgs
}

Write-Banner
if ($env:OPENSQUILLA_LISTEN -eq '0.0.0.0') {
    Write-ListenWarning
}
