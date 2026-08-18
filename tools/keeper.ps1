# Сторож агента TagMarkets. Перезапускает агента, только если:
#   - процесс агента не запущен (ПК включился, агент упал), либо
#   - агент жив, но ≥3 минут нет успешной связи с терминалом (отметка agent.beat).
# Проверка лёгкая (список процессов + дата файла); перезапуск — редкое событие.
$py   = 'C:\Users\crown\AppData\Local\Programs\Python\Python314\pythonw.exe'
$dir  = 'D:\TagMarkets'
$beat = Join-Path $dir 'agent.beat'
$proc = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -EA SilentlyContinue |
          Where-Object { $_.CommandLine -like '*agent.py*' }

function Start-Agent { Start-Process -FilePath $py -ArgumentList 'agent.py' -WorkingDirectory $dir -WindowStyle Hidden }

if (-not $proc) {
    Start-Agent                                   # процесс мёртв — поднимаем
} else {
    # отметки нет (только запустился) — даём поработать; есть и старше 3 минут — застрял
    if (Test-Path $beat) {
        $age = (New-TimeSpan -Start (Get-Item $beat).LastWriteTime -End (Get-Date)).TotalSeconds
        if ($age -ge 180) {
            Stop-Process -Id $proc.ProcessId -Force
            Start-Sleep -Seconds 2
            Start-Agent
        }
    }
}
