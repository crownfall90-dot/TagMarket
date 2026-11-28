# Совместимость со старыми задачами. Новый сторож выполняется через WScript.
$launcher = Join-Path $PSScriptRoot 'run_agent.vbs'
Start-Process -FilePath "$env:WINDIR\System32\wscript.exe" `
    -ArgumentList ('//B //NoLogo "{0}" /watch' -f $launcher) -WindowStyle Hidden
