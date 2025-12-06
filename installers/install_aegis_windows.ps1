[CmdletBinding()]
param(
    [string]$InstallPath
)

$ErrorActionPreference = "Stop"

function Ensure-Admin {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "Restarting installer with administrative privileges..." -ForegroundColor Yellow
        $args = @("-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
        if ($InstallPath) {
            $args += @("-InstallPath", "`"$InstallPath`"")
        }
        Start-Process -FilePath "powershell.exe" -ArgumentList $args -Verb RunAs
        exit
    }
}

function Resolve-InstallPath {
    param([string]$ProvidedPath)

    if ($ProvidedPath) {
        $resolved = Resolve-Path -LiteralPath $ProvidedPath -ErrorAction SilentlyContinue
        if ($resolved) {
            return $resolved.ProviderPath
        }

        return [System.IO.Path]::GetFullPath($ProvidedPath)
    }

    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Choose where to install A.E.G.I.S."
    $dialog.ShowNewFolderButton = $true
    $dialog.SelectedPath = [Environment]::GetFolderPath('ProgramFiles')

    $result = $dialog.ShowDialog()
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        throw "Installation folder selection was cancelled."
    }

    return $dialog.SelectedPath
}

function Get-PythonCommand {
    $candidates = @(
        @{ Name = "py"; PrefixArgs = @("-3") },
        @{ Name = "python"; PrefixArgs = @() },
        @{ Name = "python3"; PrefixArgs = @() }
    )

    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Name -ErrorAction SilentlyContinue
        if (-not $command) { continue }

        $versionOutput = & $command.Source @($candidate.PrefixArgs + @("--version")) 2>&1
        if ($LASTEXITCODE -ne 0) { continue }

        if ($versionOutput -match "(\d+)\.(\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                return [PSCustomObject]@{ Executable = $command.Source; PrefixArgs = $candidate.PrefixArgs; Version = $versionOutput }
            }
        }
    }

    throw "Python 3.10+ is required. Install it from https://www.python.org/downloads/windows/ and rerun this installer."
}

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)]$Python,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $Python.Executable @($Python.PrefixArgs + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Python exited with status $LASTEXITCODE while running: $($Arguments -join ' ')"
    }
}

function Build-AegisArtifact {
    param($Python)

    Write-Host "Building A.E.G.I.S. welcome archive using $($Python.Version)" -ForegroundColor Cyan
    Push-Location $PSScriptRoot
    try {
        Invoke-Python -Python $Python -Arguments @("run_me_to_install_aegis.py")
    }
    finally {
        Pop-Location
    }

    $artifact = Join-Path $PSScriptRoot "dist" "aegis-welcome.pyz"
    if (-not (Test-Path $artifact)) {
        throw "Expected artifact was not created at $artifact"
    }

    return $artifact
}

function Write-Launchers {
    param(
        [string]$InstallRoot,
        $Python
    )

    $batPath = Join-Path $InstallRoot "Launch-AEGIS.bat"
    $batContent = "@echo off`r`n" +
        "setlocal`r`n" +
        "set PY_CMD=%~dp0\.venv\\Scripts\\python.exe`r`n" +
        "if exist \"%PY_CMD%\" goto runApp`r`n" +
        "set PY_CMD=py -3`r`n" +
        "if not exist \"%~dp0aegis-welcome.pyz\" echo Missing aegis-welcome.pyz && exit /b 1`r`n" +
        ":runApp`r`n" +
        "%PY_CMD% \"%~dp0aegis-welcome.pyz\"`r`n"
    Set-Content -Path $batPath -Value $batContent -Encoding ASCII

    $psPath = Join-Path $InstallRoot "Launch-AEGIS.ps1"
    $psContent = @(
        "$ErrorActionPreference = 'Stop'",
        "$python = '$($Python.Executable)'",
        "if (Test-Path (Join-Path $PSScriptRoot '.venv\\Scripts\\python.exe')) {",
        "    $python = (Join-Path $PSScriptRoot '.venv\\Scripts\\python.exe')",
        "}",
        "& $python (Join-Path $PSScriptRoot 'aegis-welcome.pyz')"
    ) -join "`r`n"
    Set-Content -Path $psPath -Value $psContent -Encoding UTF8

    return $batPath
}

Ensure-Admin
$targetDirectory = Resolve-InstallPath -ProvidedPath $InstallPath
New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null

$python = Get-PythonCommand
$artifactPath = Build-AegisArtifact -Python $python

Write-Host "Copying artifact to $targetDirectory" -ForegroundColor Cyan
Copy-Item -Path $artifactPath -Destination (Join-Path $targetDirectory "aegis-welcome.pyz") -Force

$venvSource = Join-Path $PSScriptRoot ".venv"
$venvTarget = Join-Path $targetDirectory ".venv"
if (Test-Path $venvSource) {
    Write-Host "Mirroring virtual environment to $venvTarget" -ForegroundColor Cyan
    if (Test-Path $venvTarget) {
        Remove-Item -Path $venvTarget -Recurse -Force
    }
    Copy-Item -Path $venvSource -Destination $venvTarget -Recurse -Force
}

$batLauncher = Write-Launchers -InstallRoot $targetDirectory -Python $python

Write-Host "Installation complete." -ForegroundColor Green
Write-Host " - App: " (Join-Path $targetDirectory "aegis-welcome.pyz")
Write-Host " - Launch: $batLauncher"

Write-Host "Starting A.E.G.I.S. welcome app..." -ForegroundColor Cyan
Start-Process -FilePath $batLauncher -WorkingDirectory $targetDirectory
