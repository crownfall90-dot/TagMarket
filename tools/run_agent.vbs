' Launch the agent with absolutely no window. A .bat always flashes its own
' cmd.exe window for an instant, even when the agent itself runs through
' pythonw with no window of its own. WScript.Shell.Run with the third
' argument False and the second argument 0 (SW_HIDE) creates no window at
' all - no flicker on alt-tab or when minimizing a fullscreen game.
'
' Paths are resolved from the script's own location and the user's
' environment variables rather than hardcoded - the same file works on
' this machine and on the laptop, regardless of drive letter or Python
' version. Comments are kept in plain ASCII on purpose: VBScript reads
' the file in the system's ANSI codepage, and Cyrillic here has caused
' encoding-dependent breakage before.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(scriptDir)     ' tools\ -> project root

pythonw = FindPythonw()
If pythonw = "" Then
    ' not found under the usual per-user install path - fall back to PATH
    On Error Resume Next
    pythonw = Trim(shell.Exec("cmd /c where pythonw").StdOut.ReadAll())
    On Error Goto 0
    If InStr(pythonw, vbCrLf) > 0 Then pythonw = Left(pythonw, InStr(pythonw, vbCrLf) - 1)
End If

If pythonw = "" Or Not fso.FileExists(pythonw) Then
    WScript.Quit 1     ' pythonw not found - quit quietly, nothing to flash anyway
End If

shell.CurrentDirectory = projectDir
shell.Run """" & pythonw & """ agent.py", 0, False

Function FindPythonw()
    Dim base, pyFolder, candidate
    base = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
    FindPythonw = ""
    If fso.FolderExists(base) Then
        For Each pyFolder In fso.GetFolder(base).SubFolders
            candidate = pyFolder.Path & "\pythonw.exe"
            If fso.FileExists(candidate) Then
                FindPythonw = candidate
                Exit Function
            End If
        Next
    End If
End Function
