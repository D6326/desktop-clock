@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Registering TaskbarClock DeskBand
echo ============================================
echo.
echo This script MUST be run as Administrator!
echo.

if not exist "TaskbarClock.dll" (
    echo ERROR: TaskbarClock.dll not found. Run build.bat first.
    pause
    exit /b 1
)

set REGASM=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe

if not exist "%REGASM%" (
    echo ERROR: RegAsm.exe not found
    pause
    exit /b 1
)

echo Registering COM component...
"%REGASM%" /codebase TaskbarClock.dll

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo REGISTRATION FAILED
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Registration successful!
echo.
echo   To enable the clock:
echo   1. Right-click on the taskbar
echo   2. Select "Toolbars"
echo   3. Check "NTP Clock"
echo.
echo   If you don't see it, restart Explorer:
echo   - Press Ctrl+Shift+Esc
echo   - Find "Windows Explorer" in Processes
echo   - Right-click and restart
echo ============================================
pause
