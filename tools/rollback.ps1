# Ручной откат кода агента на одну из последних версий. Показывает последние
# 10 коммитов текущей ветки (дата, сообщение, кто запушил) и откатывает на
# выбранный через git reset --hard + перезапуск задачи планировщика.
#
# Использование:
#   powershell -ExecutionPolicy Bypass -File tools\rollback.ps1

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location $projectDir

$dirty = git status --porcelain
if ($dirty) {
    Write-Host "В рабочей копии есть незакоммиченные изменения - откат их сотрёт:" -ForegroundColor Yellow
    Write-Host $dirty
    $answer = Read-Host "Продолжить всё равно? (y/n)"
    if ($answer -ne "y") {
        Write-Host "Отменено." -ForegroundColor Yellow
        exit 1
    }
}

$currentHead = git rev-parse HEAD
Write-Host ""
Write-Host "Сейчас на коммите: $($currentHead.Substring(0,8))" -ForegroundColor Cyan
Write-Host ""
Write-Host "Последние версии:" -ForegroundColor Cyan
Write-Host ""

# %h дата автора | первая строка сообщения, без Origin-Host/Co-Authored-By трейлеров
$log = git log -10 --pretty=format:"%h|%ad|%s" --date=format:"%d.%m %H:%M"
$commits = @()
$i = 1
foreach ($line in $log -split "`n") {
    $parts = $line -split '\|', 3
    if ($parts.Count -lt 3) { continue }
    $hash, $date, $subject = $parts
    $marker = if ($hash -eq $currentHead.Substring(0,7)) { " <- текущая" } else { "" }
    Write-Host ("  {0,2}) {1}  {2}  {3}{4}" -f $i, $hash, $date, $subject, $marker)
    $commits += [PSCustomObject]@{ N = $i; Hash = $hash; Subject = $subject }
    $i++
}

Write-Host ""
$choice = Read-Host "Номер версии для отката (или Enter для отмены)"
if ([string]::IsNullOrWhiteSpace($choice)) {
    Write-Host "Отменено." -ForegroundColor Yellow
    exit 0
}

$picked = $commits | Where-Object { $_.N -eq [int]$choice }
if (-not $picked) {
    Write-Host "Нет такого номера." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Откатываюсь на $($picked.Hash) - $($picked.Subject)" -ForegroundColor Yellow
$confirm = Read-Host "Точно? (y/n)"
if ($confirm -ne "y") {
    Write-Host "Отменено." -ForegroundColor Yellow
    exit 0
}

git reset --hard $picked.Hash
if ($LASTEXITCODE -ne 0) {
    Write-Host "git reset не сработал." -ForegroundColor Red
    exit 1
}

# Ручной откат — осознанный выбор человека, и агент должен считать эту
# версию заведомо рабочей, а не «неподтверждённым обновлением». Без этого
# автоматический откат мог бы позже сам утащить машину ОБРАТНО на тот самый
# плохой коммит, от которого человек только что вручную сбежал: last_good_commit
# на диске всё ещё указывал бы на него, и следующее неудачное автообновление
# откатилось бы именно туда. Полный путь до новой версии узнаём через тот же
# git rev-parse, что использует сам agent.py — избегаем хранить укороченный хэш
$fullHash = git rev-parse $picked.Hash
$goodFile = Join-Path $projectDir "data\last_good_commit"
$pendingFile = Join-Path $projectDir "data\pending_commit"
New-Item -ItemType Directory -Force -Path (Split-Path $goodFile) | Out-Null
Set-Content -Path $goodFile -Value $fullHash -NoNewline -Encoding ascii
if (Test-Path $pendingFile) { Remove-Item $pendingFile -Force }

Write-Host ""
Write-Host "Готово. Код теперь на версии $($picked.Hash)." -ForegroundColor Green

$restart = Read-Host "Перезапустить агента сейчас? (y/n)"
if ($restart -eq "y") {
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like "*agent.py*" }
    foreach ($p in $procs) {
        Write-Host "Останавливаю старый процесс (PID $($p.ProcessId))..."
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    try {
        Start-ScheduledTask -TaskName TagMarketsAgent
        Write-Host "Агент перезапущен через задачу планировщика." -ForegroundColor Green
    } catch {
        Write-Host "Не нашёл задачу планировщика TagMarketsAgent - запусти агента вручную." -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 5
    $logPath = Join-Path $projectDir "logs\agent.log"
    if (Test-Path $logPath) {
        Write-Host ""
        Write-Host "Последние строки лога:" -ForegroundColor Cyan
        Get-Content $logPath -Tail 5 -Encoding UTF8
    }
}
