# Состояние всех частей. Печатает 4 строки: бот, синхронизация, агент, терминал.
$ErrorActionPreference = 'SilentlyContinue'
$api = 'https://crownfail.shop/tagmarkets'

$bot = 'нет связи с сервером'
$sync = '-'
try {
    $r = Invoke-RestMethod -Uri "$api/status" -TimeoutSec 15
    $bot = $r.bot
    $time = $r.last_sync.Substring(11, 5)
    $sync = "$($r.accounts) счетов, обновлено $time"
} catch {
    try {
        Invoke-RestMethod -Uri "$api/health" -TimeoutSec 10 | Out-Null
        $bot = 'сервер отвечает, состояние уточняется'
    } catch { }
}

$agent = 'остановлен'
if ((Get-ScheduledTask -TaskName TagMarketsAgent).State -eq 'Running') { $agent = 'работает' }

$term = 'остановлен'
if (Get-Process terminal64) { $term = 'работает' }

Write-Output $bot
Write-Output $sync
Write-Output $agent
Write-Output $term
