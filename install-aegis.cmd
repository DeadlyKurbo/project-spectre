@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%install-aegis.ps1"

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %*
if errorlevel 1 (
  echo.
  echo Installer failed. Review the log above for details.
  exit /b 1
)

endlocal
