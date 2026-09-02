@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Unregistering TaskbarClock DeskBand
echo ============================================
echo.
echo This script MUST be run as Administrator!
echo.

set REGASM=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe

if not exist "%REGASM%" (
    echo ERROR: RegAsm.exe not found
    pause
    exit /b 1
)

echo Unregistering COM component...
"%REGASM%" /unregister TaskbarClock.dll

echo.
echo Unregistration complete.
echo You may need to restart Explorer for changes to take effect.
pause
