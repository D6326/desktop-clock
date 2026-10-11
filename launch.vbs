Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
' NOTE: Reference launcher. Resolves the script's own directory so the
' folder can be moved or cloned anywhere without editing paths.
' For auto-start registration use install_startup.bat instead
' (it writes DesktopClock.vbs to shell:startup pointing at the
' current location).
dir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.Run "pythonw.exe """ & dir & "\desktop_clock.py""", 0
