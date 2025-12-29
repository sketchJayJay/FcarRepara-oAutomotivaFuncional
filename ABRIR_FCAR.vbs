' FCAR - abrir sem CMD (Windows)
' Coloque este arquivo na mesma pasta do app.py (ou start.py)
Option Explicit

Dim sh, fso, base, py, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base

py = base & "\venv\Scripts\pythonw.exe"
If Not fso.FileExists(py) Then
  py = "pythonw"
End If

cmd = Chr(34) & py & Chr(34) & " " & Chr(34) & base & "\start_fcar.py" & Chr(34)
' 0 = janela oculta, False = não esperar terminar
sh.Run cmd, 0, False
