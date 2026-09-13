# Разово переключает задачу планировщика TagMarketsAgent на бесконсольный
# запуск через tools\run_agent.vbs вместо run_agent.bat. Тот же шаг, что был
# сделан на компьютере вручную — этот файл делает его одной командой, чтобы
# повторить на ноутбуке (или на любой другой машине) без набора PowerShell
# по шагам.
#
# Запускать от администратора: без прав на изменение задачи Set-ScheduledTask
# откажет с ошибкой доступа.
#
# Использование:
#   powershell -ExecutionPolicy Bypass -File tools\setup_console_free.ps1

$ErrorActionPreference = "Stop"

$taskName = "TagMarketsAgent"
$projectDir = Split-Path -Parent $PSScriptRoot
$vbsPath = Join-Path $projectDir "tools\run_agent.vbs"

Write-Host "Проверяю, что задача существует..."
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Задача [$taskName] не найдена на этой машине - переключать нечего." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $vbsPath)) {
    Write-Host "Не нашёл $vbsPath - обнови код (git pull) перед запуском этого скрипта." -ForegroundColor Red
    exit 1
}

Write-Host "Найдена задача [$taskName], текущее действие:"
foreach ($a in $task.Actions) {
    Write-Host ("  Execute: " + $a.Execute)
    Write-Host ("  Arguments: " + $a.Arguments)
}

$vbsArg = "//B " + [char]34 + $vbsPath + [char]34
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $vbsArg
$settings = New-ScheduledTaskSettingsSet -Hidden -ExecutionTimeLimit (New-TimeSpan -Hours 72)

try {
    Set-ScheduledTask -TaskName $taskName -Action $action -Settings $settings | Out-Null
} catch {
    Write-Host ("Не удалось изменить задачу: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "Скорее всего нужны права администратора - перезапусти PowerShell от имени администратора и повтори." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Готово. Новое действие задачи:" -ForegroundColor Green
$updated = Get-ScheduledTask -TaskName $taskName
foreach ($a in $updated.Actions) {
    Write-Host ("  Execute: " + $a.Execute)
    Write-Host ("  Arguments: " + $a.Arguments)
}

Write-Host ""
$answer = Read-Host "Перезапустить агент прямо сейчас, чтобы проверить? (y/n)"
if ($answer -eq "y") {
    $q = [char]39
    $filterExpr = "Name = " + $q + "pythonw.exe" + $q + " OR Name = " + $q + "python.exe" + $q
    $procs = Get-CimInstance Win32_Process -Filter $filterExpr |
        Where-Object { $_.CommandLine -like "*agent.py*" }
    foreach ($p in $procs) {
        Write-Host ("Останавливаю старый процесс агента (PID " + $p.ProcessId + ")...")
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 5
    $logPath = Join-Path $projectDir "logs\agent.log"
    if (Test-Path $logPath) {
        Write-Host ""
        Write-Host "Последние строки лога агента:" -ForegroundColor Cyan
        Get-Content $logPath -Tail 5 -Encoding UTF8
    }
    $filterExpr2 = "Name = " + $q + "pythonw.exe" + $q
    $newProc = Get-CimInstance Win32_Process -Filter $filterExpr2 |
        Where-Object { $_.CommandLine -like "*agent.py*" }
    if ($newProc) {
        Write-Host ""
        Write-Host ("Агент работает (PID " + $newProc.ProcessId + "), окно консоли не появлялось.") -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "Не вижу запущенного процесса агента - проверь лог выше." -ForegroundColor Yellow
    }
}
