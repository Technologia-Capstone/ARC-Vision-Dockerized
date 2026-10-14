' Windows VBScript silent zero-console launcher for A.R.C. Vision.
' Resolves backend paths and launches desktop_app.py in background via pythonw without displaying terminal windows.
' Handles invisible process creation and execution management.
Set fso = CreateObject("Scripting.FileSystemObject")
Set wshShell = CreateObject("WScript.Shell")

strCurDir = fso.GetParentFolderName(WScript.ScriptFullName)
strBackendDir = fso.GetAbsolutePathName(strCurDir & "\..\Source Code\Back End")

If Not fso.FolderExists(strBackendDir) Then
    strBackendDir = fso.GetAbsolutePathName(strCurDir & "\Source Code\Back End")
End If

If fso.FolderExists(strBackendDir) Then
    wshShell.CurrentDirectory = strBackendDir
End If

strPythonw = strBackendDir & "\.python_win\pythonw.exe"
If Not fso.FileExists(strPythonw) Then
    strPythonw = strBackendDir & "\.venv\Scripts\pythonw.exe"
    If Not fso.FileExists(strPythonw) Then
        strPythonw = "pythonw.exe"
    End If
End If

strCmd = """" & strPythonw & """ """ & strBackendDir & "\desktop_app.py"""
wshShell.Run strCmd, 0, False
