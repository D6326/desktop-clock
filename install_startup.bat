@echo off
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
(
echo Set ws = CreateObject("WScript.Shell"^)
echo ws.Run "pythonw.exe ""%~dp0desktop_clock.py""", 0
) > "%STARTUP%\DesktopClock.vbs"
echo Installed: %STARTUP%\DesktopClock.vbs
echo Clock will start automatically on next login.
pause