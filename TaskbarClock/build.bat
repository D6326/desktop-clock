@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Building TaskbarClock DeskBand
echo ============================================

set CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe

if not exist "%CSC%" (
    echo ERROR: csc.exe not found at %CSC%
    pause
    exit /b 1
)

echo Compiling...

"%CSC%" ^
  /target:library ^
  /platform:x64 ^
  /out:TaskbarClock.dll ^
  TaskbarClock.cs

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo BUILD FAILED
    pause
    exit /b 1
)

echo.
echo Build successful: TaskbarClock.dll
echo.
echo Next step: run register.bat as Administrator
pause
