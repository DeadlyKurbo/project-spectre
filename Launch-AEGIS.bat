@echo off
title A.E.G.I.S.
cd /d "%~dp0"

set VENV_PYTHON=aegis\.venv\Scripts\python.exe
set APP_PATH=aegis\dist\aegis-welcome.pyz

if not exist "%VENV_PYTHON%" (
    echo A.E.G.I.S. is not installed yet.
    echo.
    echo Please run "Install-AEGIS.bat" first.
    echo.
    pause
    exit /b 1
)

if not exist "%APP_PATH%" (
    echo A.E.G.I.S. app bundle not found.
    echo.
    echo Please run "Install-AEGIS.bat" to set up the application.
    echo.
    pause
    exit /b 1
)

"%VENV_PYTHON%" "%APP_PATH%"
