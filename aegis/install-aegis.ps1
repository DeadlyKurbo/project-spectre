param(
    [switch]$SkipBuild,
    [switch]$SkipConfig,
    [switch]$ForceRuntimeDownload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptName = "A.E.G.I.S. Installer"
$operatorName = if ([string]::IsNullOrWhiteSpace($env:AEGIS_OPERATOR_NAME)) {
    $env:USERNAME
} else {
    $env:AEGIS_OPERATOR_NAME
}
$timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")

Write-Host ""
Write-Host "$scriptName" -ForegroundColor Cyan
Write-Host "Operator: $operatorName" -ForegroundColor Cyan
Write-Host "Timestamp: $timestamp" -ForegroundColor DarkGray
Write-Host ""

$aegisDir = $PSScriptRoot
$requirementsFile = Join-Path $aegisDir "requirements.txt"
$runtimeDir = Join-Path $aegisDir ".python"
$runtimeExe = Join-Path $runtimeDir "python.exe"
$basePythonExe = $null
$venvDir = Join-Path $aegisDir ".venv"
$venvExe = Join-Path $venvDir "Scripts\python.exe"
$distDir = Join-Path $aegisDir "dist"
$installerCacheDir = Join-Path $aegisDir ".installer"

function Assert-Path {
    param(
        [string]$Path,
        [string]$Message
    )
    if (-not (Test-Path -Path $Path)) {
        throw $Message
    }
}

function Write-Step {
    param(
        [int]$Index,
        [int]$Total,
        [string]$Message
    )
    Write-Host ("[{0}/{1}] {2}" -f $Index, $Total, $Message) -ForegroundColor Green
}

function New-CleanDirectory {
    param([string]$Path)
    if (-not (Test-Path -Path $Path)) {
        New-Item -Path $Path -ItemType Directory | Out-Null
    }
}

function Install-PortablePython {
    $pythonVersion = "3.11.9"
    $arch = if ([Environment]::Is64BitOperatingSystem) { "amd64" } else { "win32" }
    $installerName = "python-$pythonVersion-$arch.exe"
    $installerPath = Join-Path $installerCacheDir $installerName
    $installerUrl = "https://www.python.org/ftp/python/$pythonVersion/$installerName"

    New-CleanDirectory -Path $installerCacheDir

    if ($ForceRuntimeDownload -or -not (Test-Path -Path $installerPath)) {
        Write-Host "Downloading Python $pythonVersion ($arch)..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath
    } else {
        Write-Host "Reusing cached Python installer at $installerPath" -ForegroundColor Yellow
    }

    if (Test-Path -Path $runtimeDir) {
        Write-Host "Existing runtime detected at $runtimeDir. Replacing it." -ForegroundColor Yellow
        Remove-Item -Path $runtimeDir -Recurse -Force
    }

    Write-Host "Installing portable Python runtime to $runtimeDir" -ForegroundColor Yellow
    $arguments = @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=0",
        "Include_test=0",
        "Include_pip=1",
        "TargetDir=$runtimeDir"
    )
    $process = Start-Process -FilePath $installerPath -ArgumentList $arguments -PassThru -Wait
    if ($process.ExitCode -ne 0) {
        throw "Python installer failed with exit code $($process.ExitCode)."
    }
}

function Ensure-Venv {
    param([string]$PythonExe)
    if (-not (Test-Path -Path $venvExe)) {
        Write-Host "Creating virtual environment at $venvDir" -ForegroundColor Yellow
        & $PythonExe -m venv $venvDir
    } else {
        Write-Host "Using existing virtual environment at $venvDir" -ForegroundColor Yellow
    }
}

function Invoke-Python {
    param([string[]]$Arguments)
    & $venvExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $venvExe $($Arguments -join ' ')"
    }
}

function Resolve-SystemPython {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        return $pyCommand.Source
    }

    return $null
}

Assert-Path -Path $aegisDir -Message "Could not locate the aegis directory at $aegisDir."
Assert-Path -Path $requirementsFile -Message "Missing requirements.txt in $aegisDir."

$steps = @("runtime", "venv", "pip", "requirements")
if (-not $SkipBuild) { $steps += "build" }
if (-not $SkipConfig) { $steps += "config" }
$totalSteps = $steps.Count
$step = 1

$basePythonExe = if ($ForceRuntimeDownload) { $null } else { Resolve-SystemPython }
if ($basePythonExe) {
    Write-Step -Index $step -Total $totalSteps -Message "System Python detected at $basePythonExe"
} elseif (-not (Test-Path -Path $runtimeExe)) {
    Write-Step -Index $step -Total $totalSteps -Message "Preparing portable Python runtime"
    Install-PortablePython
    Assert-Path -Path $runtimeExe -Message "Python runtime did not install correctly."
    $basePythonExe = $runtimeExe
} else {
    Write-Step -Index $step -Total $totalSteps -Message "Portable Python runtime already available"
    $basePythonExe = $runtimeExe
}
$step++

Write-Step -Index $step -Total $totalSteps -Message "Preparing virtual environment"
Ensure-Venv -PythonExe $basePythonExe
$step++

Write-Step -Index $step -Total $totalSteps -Message "Upgrading pip"
Invoke-Python -Arguments @("-m", "pip", "install", "--upgrade", "pip")
$step++

Write-Step -Index $step -Total $totalSteps -Message "Installing A.E.G.I.S. dependencies"
Invoke-Python -Arguments @("-m", "pip", "install", "-r", $requirementsFile)
$step++

if (-not $SkipBuild) {
    Write-Step -Index $step -Total $totalSteps -Message "Building aegis/dist/aegis-welcome.pyz"
    $env:PYTHONPATH = $aegisDir
    Invoke-Python -Arguments @(
        "-c",
        "import sys; sys.path.insert(0, r'$aegisDir'); import build_aegis_zipapp; build_aegis_zipapp.build_zipapp()"
    )
    $step++
}

if (-not $SkipConfig) {
    Write-Step -Index $step -Total $totalSteps -Message "Launching the A.E.G.I.S. configuration menu"
    $env:PYTHONPATH = $aegisDir
    Push-Location $aegisDir
    try {
        Invoke-Python -Arguments @(
            "-c",
            "from aegis_app import configure; configure()"
        )
    } finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Cyan
if ($basePythonExe -eq $runtimeExe) {
    Write-Host "Runtime: $runtimeDir" -ForegroundColor DarkGray
} else {
    Write-Host "System Python: $basePythonExe" -ForegroundColor DarkGray
}
Write-Host "Virtual environment: $venvDir" -ForegroundColor DarkGray
Write-Host "Distribution: $distDir" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Launch A.E.G.I.S. anytime with:" -ForegroundColor Cyan
Write-Host "  $venvExe $aegisDir\dist\aegis-welcome.pyz" -ForegroundColor White
Write-Host ""
