@echo off
title A.E.G.I.S. Installer
echo.
echo ============================================
echo   A.E.G.I.S. Installation
echo   Administrative ^& Engagement Global Interface System
echo ============================================
echo.
echo This will set up the A.E.G.I.S. desktop app.
echo You may see a security prompt - click "Run" or "Yes" to continue.
echo.

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "install-aegis.ps1" %*
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% equ 0 (
    echo Installation finished successfully.
    echo.
    echo To launch A.E.G.I.S., double-click "Launch-AEGIS.bat"
    echo or run: .venv\Scripts\python.exe dist\aegis-welcome.pyz
) else (
    echo Installation failed with error code %EXIT_CODE%.
    echo.
    echo Troubleshooting:
    echo - Make sure you have an internet connection.
    echo - Try running this as Administrator if you see permission errors.
    echo - If Python fails to download, install Python 3.11 from python.org first.
)
echo.
pause
