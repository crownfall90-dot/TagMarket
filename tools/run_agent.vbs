Option Explicit

Dim fso, shell, scriptDir, projectDir, agentScript, pythonw, watching
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(scriptDir)
agentScript = projectDir & "\agent.py"
watching = WScript.Arguments.Count > 0

If watching Then
    If WScript.Arguments(0) <> "/watch" Then WScript.Quit 2
    If Not NeedsRestart() Then WScript.Quit 0
End If

pythonw = FindPythonw()
If pythonw = "" Then WScript.Quit 1
shell.CurrentDirectory = projectDir
shell.Run Quote(pythonw) & " " & Quote(agentScript), 0, False

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function

Function FindPythonw()
    Dim candidate, base, folder, directory
    FindPythonw = ""
    For Each directory In Array(".venv", "venv")
        candidate = projectDir & "\" & directory & "\Scripts\pythonw.exe"
        If fso.FileExists(candidate) Then
            FindPythonw = candidate
            Exit Function
        End If
    Next
    base = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
    If fso.FolderExists(base) Then
        For Each folder In fso.GetFolder(base).SubFolders
            candidate = folder.Path & "\pythonw.exe"
            If fso.FileExists(candidate) Then
                FindPythonw = candidate
                Exit Function
            End If
        Next
    End If
    For Each directory In Split(shell.ExpandEnvironmentStrings("%PATH%"), ";")
        directory = Trim(Replace(directory, Chr(34), ""))
        If directory <> "" Then
            candidate = fso.BuildPath(directory, "pythonw.exe")
            If fso.FileExists(candidate) Then
                FindPythonw = candidate
                Exit Function
            End If
        End If
    Next
End Function

Function MatchesAgentCommandLine(cmd)
    Dim trimmed
    trimmed = LCase(Trim(cmd))
    If InStr(1, cmd, agentScript, vbTextCompare) > 0 Then
        MatchesAgentCommandLine = True
    ElseIf InStr(1, cmd, """agent.py""", vbTextCompare) > 0 Then
        MatchesAgentCommandLine = True
    ElseIf Right(trimmed, 9) = " agent.py" Then
        MatchesAgentCommandLine = True
    Else
        MatchesAgentCommandLine = False
    End If
End Function

Function NeedsRestart()
    Dim beat, wmi, process, found
    beat = projectDir & "\data\agent.beat"
    Set wmi = GetObject("winmgmts:\\.\root\cimv2")
    found = False
    NeedsRestart = False
    For Each process In wmi.ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name = 'pythonw.exe' OR Name = 'python.exe'")
        If Not IsNull(process.CommandLine) Then
            If MatchesAgentCommandLine(process.CommandLine) Then
                found = True
                If Not fso.FileExists(beat) Then Exit Function
                If DateDiff("s", fso.GetFile(beat).DateLastModified, Now) < 180 Then Exit Function
                If process.Terminate() <> 0 Then Exit Function
            End If
        End If
    Next
    If found Then WScript.Sleep 2000
    NeedsRestart = True
End Function
