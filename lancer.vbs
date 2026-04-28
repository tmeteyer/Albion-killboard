Set ws = CreateObject("WScript.Shell")
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
ws.Run "pythonw """ & dir & "main.py""", 0
