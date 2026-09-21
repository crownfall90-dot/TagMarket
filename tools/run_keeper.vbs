' Launch keeper.ps1 with absolutely no window. powershell.exe -WindowStyle
' Hidden still creates a console host process that can flash on screen for
' an instant before hiding - WScript.Shell.Run with the third argument
' False and the second argument 0 (SW_HIDE) creates no window at all, the
' same trick already used by run_agent.vbs for the agent itself.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
keeperScript = scriptDir & "\keeper.ps1"

shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & keeperScript & """", 0, True
