Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
ws.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
If Not fso.FileExists(ws.CurrentDirectory & "\.venv\Scripts\python.exe") Then
    MsgBox "未找到 .venv\Scripts\python.exe，请先在项目根目录执行：" & vbCrLf & _
           "python -m venv .venv" & vbCrLf & _
           ".venv\Scripts\pip install -r requirements.txt", 48, "FontCop"
    WScript.Quit 1
End If
ws.Run ".venv\Scripts\python.exe -m src.server", 0, False
