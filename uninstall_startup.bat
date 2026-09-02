@echo off
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
del /f "%STARTUP%\DesktopClock.vbs" 2>NUL
echo Removed startup entry.
pause
