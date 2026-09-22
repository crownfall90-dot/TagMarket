# Состояние всех частей. Печатает 4 строки: бот, синхронизация, агент, терминал.
$ErrorActionPreference = 'SilentlyContinue'

# Адрес сервера и токен — из того же .env, что у агента: /status отвечает
# только с токеном (X-Token), без него пульт всегда видел бы 403
$settings = @{}
$envFile = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            $settings[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
}
$api = if ($settings['AGENT_SERVER']) { $settings['AGENT_SERVER'].TrimEnd('/') } else { 'https://crownfail.shop/tagmarkets' }
$headers = @{}
if ($settings['WEBHOOK_TOKEN']) { $headers['X-Token'] = $settings['WEBHOOK_TOKEN'] }

$bot = 'нет связи с сервером'
$sync = '-'
try {
    $r = Invoke-RestMethod -Uri "$api/status" -Headers $headers -TimeoutSec 15
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
$agentProc = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -EA SilentlyContinue |
             Where-Object { $_.CommandLine -like '*agent.py*' }
if ($agentProc) { $agent = 'работает' }

$term = 'остановлен'
if (Get-Process terminal64) { $term = 'работает' }

Write-Output $bot
Write-Output $sync
Write-Output $agent
Write-Output $term
