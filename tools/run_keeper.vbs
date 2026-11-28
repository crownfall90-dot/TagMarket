Option Explicit

Dim fso, shell, launcher
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
launcher = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "run_agent.vbs")
WScript.Quit shell.Run(Chr(34) & WScript.FullName & Chr(34) & _
    " //B //NoLogo " & Chr(34) & launcher & Chr(34) & " /watch", 0, True)
