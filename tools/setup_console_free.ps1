# Перенаправляет существующие задачи на один экземпляр проекта.
# Запускайте из папки агента, которую должна обслуживать эта машина.
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
$launchers = @{
    TagMarketsAgent = 'run_agent.vbs'
    TagMarketsKeeper = 'run_keeper.vbs'
}

foreach ($name in @('TagMarketsAgent', 'TagMarketsKeeper')) {
    $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
    if (-not $task) {
        if ($name -eq 'TagMarketsAgent') { throw "Задача $name не найдена." }
        continue
    }
    $launcher = Join-Path $PSScriptRoot $launchers[$name]
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "Файл не найден: $launcher" }
    $current = $task.Actions
    if ($current.Count -eq 1 -and (Split-Path -Leaf $current[0].Execute) -ieq 'wscript.exe' -and
        $current[0].Arguments.TrimEnd().EndsWith(('"{0}"' -f $launcher), [StringComparison]::OrdinalIgnoreCase)) {
        Write-Output "$name уже запускается через WScript."
        continue
    }
    $arguments = '//B //NoLogo "{0}"' -f $launcher
    $action = New-ScheduledTaskAction -Execute $wscript -Argument $arguments -WorkingDirectory $project
    Set-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -Action $action | Out-Null
    Write-Output "$name → $launcher"
}
