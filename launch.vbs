Set ws = CreateObject("WScript.Shell")
' NOTE: This is a reference template with a placeholder path.
' For actual startup, use install_startup.bat which generates
' DesktopClock.vbs with the correct path dynamically via %~dp0.
ws.Run "pythonw.exe ""<REPLACE_WITH_YOUR_PATH>\desktop_clock.py""", 0
