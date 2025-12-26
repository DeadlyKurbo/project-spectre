param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptName = "A.E.G.I.S. Uninstaller"
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
$runtimeDir = Join-Path $aegisDir ".python"
$venvDir = Join-Path $aegisDir ".venv"
$distDir = Join-Path $aegisDir "dist"
$installerCacheDir = Join-Path $aegisDir ".installer"
$configPath = Join-Path $aegisDir "aegis-config.json"
$homeConfigPath = Join-Path $HOME ".aegis-config.json"
$desktopShortcut = Join-Path $HOME "Desktop\A.E.G.I.S. Welcome.lnk"

$targets = @(
    $runtimeDir,
    $venvDir,
    $distDir,
    $installerCacheDir,
    $configPath,
    $homeConfigPath,
    $desktopShortcut
)

Write-Host "The following A.E.G.I.S. items will be removed if they exist:" -ForegroundColor Yellow
$targets | ForEach-Object { Write-Host " - $_" -ForegroundColor Yellow }
Write-Host ""

if (-not $Force) {
    $confirmation = Read-Host "Continue with uninstall? (y/N)"
    if ($confirmation -notin @("y", "Y", "yes", "YES", "Yes")) {
        Write-Host "Uninstall cancelled." -ForegroundColor DarkGray
        exit 0
    }
}

function Remove-Target {
    param([string]$Path)
    if (-not (Test-Path -Path $Path)) {
        return
    }
    try {
        Remove-Item -Path $Path -Recurse -Force
        Write-Host "Removed $Path" -ForegroundColor Green
    } catch {
        Write-Host "Failed to remove $Path: $($_.Exception.Message)" -ForegroundColor Red
    }
}

$targets | ForEach-Object { Remove-Target -Path $_ }

Write-Host ""
Write-Host "Uninstall complete." -ForegroundColor Cyan
Write-Host ""
