param(
    [switch]$Cli,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PackageDir = Join-Path $ScriptDir 'packages'
$PythonBin = Join-Path $ScriptDir 'runtime\python\python.exe'
$VenvBase = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { $env:TEMP }
$VenvRoot = Join-Path $VenvBase 'OpenSquilla\venvs'
$RequiresRouterRuntime = $true
if ((-not $env:OPENSQUILLA_LLM_API_KEY) -and $env:OPENROUTER_API_KEY) {
    $env:OPENSQUILLA_LLM_API_KEY = $env:OPENROUTER_API_KEY
}

if (-not (Test-Path $PythonBin)) {
    throw "Bundled Python runtime not found: $PythonBin"
}
if (-not (Test-Path $PackageDir)) {
    throw "OpenSquilla package directory not found: $PackageDir"
}

function Test-WindowsVCRedistInstalled {
    if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows
    )) {
        return $true
    }
    $runtimeKeys = @(
        'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
    )
    foreach ($key in $runtimeKeys) {
        if (-not (Test-Path $key)) {
            continue
        }
        $runtime = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
        if ($runtime -and $runtime.Installed -eq 1 -and $runtime.Major -ge 14) {
            return $true
        }
    }
    return $false
}

function Test-WindowsAdmin {
    if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows
    )) {
        return $true
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-WindowsVCRedistInstaller {
    $redistUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
    $candidateInstallers = @(
        (Join-Path $ScriptDir 'vc_redist.x64.exe'),
        (Join-Path $ScriptDir 'redist\vc_redist.x64.exe'),
        (Join-Path $ScriptDir 'runtime\vc_redist.x64.exe')
    )
    $installerPath = $candidateInstallers |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if ($installerPath) {
        return $installerPath
    }

    $downloadDir = Join-Path ([System.IO.Path]::GetTempPath()) 'OpenSquilla'
    $installerPath = Join-Path $downloadDir 'vc_redist.x64.exe'
    New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null
    Write-Host (
        'OpenSquilla: downloading Microsoft Visual C++ Redistributable ' +
        '2015-2022 x64 from Microsoft.'
    )
    try {
        Invoke-WebRequest -Uri $redistUrl -OutFile $installerPath -UseBasicParsing
        return $installerPath
    } catch {
        Write-Warning (
            'OpenSquilla: could not download Microsoft Visual C++ ' +
            "Redistributable from $redistUrl. Error: $($_.Exception.Message)"
        )
        return $null
    }
}

function Install-WindowsVCRedistWithInstaller {
    param(
        [switch]$Repair
    )

    $installerPath = Get-WindowsVCRedistInstaller
    if (-not $installerPath) {
        return $false
    }

    $action = if ($Repair) { 'repairing' } else { 'installing' }
    Write-Host (
        "OpenSquilla: $action Microsoft Visual C++ Redistributable 2015-2022 x64..."
    )
    $redistArgs = if ($Repair) {
        @('/repair', '/quiet', '/norestart')
    } else {
        @('/install', '/quiet', '/norestart')
    }
    try {
        if (Test-WindowsAdmin) {
            $process = Start-Process -FilePath $installerPath -ArgumentList $redistArgs -Wait -PassThru
        } else {
            Write-Host (
                'OpenSquilla: administrator approval may be requested to ' +
                'install or repair Microsoft Visual C++ Redistributable.'
            )
            $process = Start-Process -FilePath $installerPath `
                -ArgumentList $redistArgs `
                -Verb RunAs `
                -Wait `
                -PassThru
        }
    } catch {
        Write-Warning (
            'OpenSquilla: Visual C++ Redistributable installer could not be ' +
            "started. Error: $($_.Exception.Message)"
        )
        return $false
    }

    if ($process.ExitCode -in @(0, 1638, 3010)) {
        Write-Host 'OpenSquilla: Microsoft Visual C++ Redistributable is ready.'
        if ($process.ExitCode -eq 3010) {
            Write-Warning (
                'OpenSquilla: the Visual C++ installer requested a reboot; ' +
                'restart Windows if ONNX Runtime still fails to load.'
            )
        }
        return $true
    }

    Write-Warning (
        'OpenSquilla: Microsoft Visual C++ Redistributable installer exited ' +
        "with code $($process.ExitCode)."
    )
    return $false
}

function Install-WindowsVCRedistIfNeeded {
    param(
        [switch]$Repair
    )

    if (-not $RequiresRouterRuntime) {
        return $true
    }
    if ($env:OPENSQUILLA_SKIP_VC_REDIST -eq '1') {
        Write-Host (
            'OpenSquilla: skipping Microsoft Visual C++ Redistributable check ' +
            'because OPENSQUILLA_SKIP_VC_REDIST=1.'
        )
        return $true
    }
    if ((Test-WindowsVCRedistInstalled) -and -not $Repair) {
        return $true
    }

    $redistUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
    if ($Repair) {
        if (Install-WindowsVCRedistWithInstaller -Repair) {
            return $true
        }
    } elseif (Install-WindowsVCRedistWithInstaller) {
        return $true
    }

    $winget = if ($Repair) { $null } else { Get-Command winget -ErrorAction SilentlyContinue }
    if ($winget) {
        Write-Host (
            'OpenSquilla: Microsoft Visual C++ Redistributable not detected; ' +
            'installing with winget.'
        )
        $wingetArgs = @(
            'install',
            '--id',
            'Microsoft.VCRedist.2015+.x64',
            '--exact',
            '--silent',
            '--accept-package-agreements',
            '--accept-source-agreements'
        )
        & winget @wingetArgs
        if ($LASTEXITCODE -eq 0) {
            Write-Host 'OpenSquilla: Microsoft Visual C++ Redistributable installation completed.'
            return $true
        }
        Write-Warning (
            'OpenSquilla: winget could not install Microsoft Visual C++ ' +
            "Redistributable (exit $LASTEXITCODE)."
        )
    }

    Write-Warning (
        'OpenSquilla: Microsoft Visual C++ Redistributable 2015-2022 x64 is ' +
        'required for the bundled ONNX router.'
    )
    Write-Warning (
        'OpenSquilla can still start with safe router fallback, but bundled ' +
        'ONNX model routing is disabled until this runtime is installed.'
    )
    Write-Warning (
        "If automatic installation fails, install it manually: $redistUrl"
    )
    Write-Warning (
        'After installing, reopen PowerShell and restart OpenSquilla.'
    )
    return $false
}

function Test-OnnxRuntimeImport {
    if (-not (Test-Path $VenvPython)) {
        return $false
    }
    & $VenvPython -c "import onnxruntime as ort; print('onnxruntime', ort.__version__)" | Out-Host
    return ($LASTEXITCODE -eq 0)
}

function Repair-WindowsVCRedistForOnnxIfNeeded {
    if (-not $RequiresRouterRuntime) {
        return
    }
    if ($env:OPENSQUILLA_SKIP_VC_REDIST -eq '1') {
        return
    }
    if (Test-OnnxRuntimeImport) {
        return
    }

    Write-Warning (
        'OpenSquilla: ONNX Runtime failed to import after setup. Attempting ' +
        'Visual C++ Redistributable repair before starting the gateway.'
    )
    Install-WindowsVCRedistIfNeeded -Repair | Out-Null
    if (Test-OnnxRuntimeImport) {
        return
    }

    Write-Warning (
        'OpenSquilla: ONNX Runtime still failed after Visual C++ repair. If ' +
        'the router warning remains, check CPU/VM AVX compatibility or install ' +
        'the Microsoft Visual C++ Redistributable manually: ' +
        'https://aka.ms/vs/17/release/vc_redist.x64.exe'
    )
}

if (-not (Test-Path $VenvRoot)) {
    New-Item -ItemType Directory -Path $VenvRoot -Force | Out-Null
}
$OpenSquillaWheel = Get-ChildItem -Path $PackageDir -Filter 'opensquilla-*.whl' |
    Sort-Object Name |
    Select-Object -First 1
if (-not $OpenSquillaWheel) {
    throw "OpenSquilla wheel not found in $PackageDir"
}
$Sha256 = [System.Security.Cryptography.SHA256]::Create()
$WheelStream = [System.IO.File]::OpenRead($OpenSquillaWheel.FullName)
try {
    $WheelHashFull = -join ($Sha256.ComputeHash($WheelStream) | ForEach-Object {
        $_.ToString('x2')
    })
} finally {
    $WheelStream.Dispose()
    $Sha256.Dispose()
}
$WheelHash = $WheelHashFull.Substring(0, 12).ToLowerInvariant()
$Hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash(
    [System.Text.Encoding]::UTF8.GetBytes("$ScriptDir|$WheelHash")
)
$ReleaseId = -join ($Hash[0..5] | ForEach-Object { $_.ToString('x2') })
$VenvDir = Join-Path $VenvRoot $ReleaseId
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$InstallMarker = Join-Path $VenvDir ".opensquilla-wheelhouse-$WheelHash"
$env:PATH = "$ScriptDir;$ScriptDir\runtime\python;$env:PATH"
$env:PATH = "$VenvDir\Scripts;$env:PATH"
$PortableDataDir = if ($env:OPENSQUILLA_PORTABLE_HOME) {
    $env:OPENSQUILLA_PORTABLE_HOME
} else {
    Join-Path $VenvBase "OpenSquilla\portable\$ReleaseId"
}
if (-not $env:OPENSQUILLA_GATEWAY_CONFIG_PATH) {
    $env:OPENSQUILLA_GATEWAY_CONFIG_PATH = Join-Path $PortableDataDir 'config.toml'
}
if (-not $env:OPENSQUILLA_STATE_DIR) {
    $env:OPENSQUILLA_STATE_DIR = $PortableDataDir
}
if (-not $env:OPENSQUILLA_GATEWAY_STATE_DIR) {
    $env:OPENSQUILLA_GATEWAY_STATE_DIR = Join-Path $env:OPENSQUILLA_STATE_DIR 'state'
}
if (-not $env:OPENSQUILLA_GATEWAY_WORKSPACE_DIR) {
    $env:OPENSQUILLA_GATEWAY_WORKSPACE_DIR = Join-Path $env:OPENSQUILLA_STATE_DIR 'workspace'
}
New-Item -ItemType Directory -Path $env:OPENSQUILLA_STATE_DIR -Force | Out-Null
Install-WindowsVCRedistIfNeeded | Out-Null

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating local OpenSquilla environment..."
    & $PythonBin -m venv --without-pip $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "OpenSquilla environment creation failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path $InstallMarker)) {
    Write-Host "Installing OpenSquilla from bundled wheels..."
    $SitePackages = & $VenvPython -c "import site; print(site.getsitepackages()[0])"
    if ($LASTEXITCODE -ne 0) {
        throw "OpenSquilla site-packages lookup failed with exit code $LASTEXITCODE."
    }
    $WheelInstallScript = @'
import pathlib
import shutil
import sys
import zipfile

package_dir = pathlib.Path(sys.argv[1])
site_packages = pathlib.Path(sys.argv[2])
site_packages.mkdir(parents=True, exist_ok=True)
for wheel_path in sorted(package_dir.glob("*.whl")):
    with zipfile.ZipFile(wheel_path) as wheel:
        for info in wheel.infolist():
            name = info.filename
            if not name or name.endswith("/"):
                continue
            if ".data/" in name:
                _prefix, data_rel = name.split(".data/", 1)
                kind, _sep, remainder = data_rel.partition("/")
                if kind not in {"purelib", "platlib"} or not remainder:
                    continue
                target_rel = pathlib.Path(remainder)
            else:
                target_rel = pathlib.Path(name)
            target = site_packages / target_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with wheel.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
'@
    $WheelInstallScript | & $PythonBin - $PackageDir $SitePackages
    if ($LASTEXITCODE -ne 0) {
        throw "OpenSquilla bundled wheel installation failed with exit code $LASTEXITCODE."
    }
    New-Item -ItemType File -Path $InstallMarker -Force | Out-Null
}
Repair-WindowsVCRedistForOnnxIfNeeded

$OpenSquillaArgs = @("-m", "opensquilla.cli.main")

if ($Cli) {
    & $VenvPython @OpenSquillaArgs @CliArgs
    exit $LASTEXITCODE
}

if ((-not (Test-Path $env:OPENSQUILLA_GATEWAY_CONFIG_PATH)) -and $env:OPENROUTER_API_KEY) {
    & $VenvPython @OpenSquillaArgs onboard `
        --provider openrouter `
        --api-key-env OPENROUTER_API_KEY `
        --minimal
} else {
    & $VenvPython @OpenSquillaArgs onboard
}
if ($LASTEXITCODE -ne 0) {
    throw "OpenSquilla onboarding failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "Starting OpenSquilla gateway."
Write-Host "Web UI: http://127.0.0.1:18791/control/"
Write-Host "Press Ctrl+C in this terminal to stop the gateway."
$OutputRedirected = [Console]::IsOutputRedirected
if (-not $OutputRedirected) {
    & $VenvPython @OpenSquillaArgs gateway run
    $GatewayExitCode = $LASTEXITCODE
} else {
    $LogDir = Join-Path $env:OPENSQUILLA_STATE_DIR 'logs'
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    $ConsoleLog = Join-Path $LogDir 'gateway-console.log'
    Write-Host "Console log: $ConsoleLog"
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $VenvPython @OpenSquillaArgs gateway run 2>&1 |
            ForEach-Object {
                if ($_ -is [System.Management.Automation.ErrorRecord]) {
                    $_.ToString()
                } else {
                    $_
                }
            } |
            Tee-Object -FilePath $ConsoleLog -Append
        $GatewayExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
}
exit $GatewayExitCode
