' Запуск агента совсем без окна — в отличие от .bat (тот всегда на миг
' показывает своё окно cmd.exe, даже если сам агент прячется через pythonw).
' WScript.Shell.Run с третьим параметром False и вторым 0 (SW_HIDE) не создаёт
' видимого окна вообще: ни рамки, ни мелькания при alt-tab или сворачивании
' полноэкранных игр — то, ради чего это и делалось.
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "D:\TagMarket-main"
shell.Run """C:\Users\crown\AppData\Local\Programs\Python\Python314\pythonw.exe"" agent.py", 0, False
