Set WshShell = CreateObject("WScript.Shell")
strDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strDir
WshShell.Run """C:\Users\azsho\AppData\Local\Programs\Python\Python313\pythonw.exe"" """ & strDir & "\main.py""", 1, False
