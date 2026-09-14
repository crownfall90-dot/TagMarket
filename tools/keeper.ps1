# Сторож агента TagMarkets. Перезапускает агента, только если:
#   - процесс агента не запущен (ПК включился, агент упал), либо
#   - агент жив, но >=3 минут нет успешной связи с терминалом (отметка agent.beat).
# Проверка лёгкая (список процессов + дата файла); перезапуск — редкое событие.
#
# Пути ищутся сами (от расположения этого скрипта и переменных окружения), а
# не прописаны жёстко под одну машину — тот же файл работает и на ноутбуке,
# и на ПК независимо от буквы диска или версии Python (см. run_agent.vbs,
# тот же приём для запуска агента без консоли).
$dir  = Split-Path -Parent $PSScriptRoot
$beat = Join-Path $dir 'data\agent.beat'

function Find-Pythonw {
    $base = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path $base) {
        $found = Get-ChildItem $base -Filter 'pythonw.exe' -Recurse -ErrorAction SilentlyContinue |
                 Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    $onPath = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    return $null
}

$py = Find-Pythonw
if (-not $py) {
    Write-Warning 'keeper: pythonw.exe не найден — перезапустить агента нечем'
    return
}

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
