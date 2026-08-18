@echo off
setlocal enabledelayedexpansion
chcp 866 >nul
title TagMarkets
cd /d "%~dp0"
set KEY=%USERPROFILE%\.ssh\tagmarkets_vps
set VPS=root@89.44.86.228
set SSH=ssh -i "%KEY%" -o BatchMode=yes -o ConnectTimeout=15 -p 2222 %VPS%
set PS=powershell -NoProfile -ExecutionPolicy Bypass

:menu
cls
echo ==================================================
echo                    TagMarkets
echo ==================================================
echo.

set N=0
for /f "usebackq delims=" %%s in (`%PS% -File "%~dp0status.ps1"`) do (
  set /a N+=1
  if !N!==1 set BOT=%%s
  if !N!==2 set SYNC=%%s
  if !N!==3 set AGENT=%%s
  if !N!==4 set TERM=%%s
)

echo    Бот на сервере (24/7) : !BOT!
echo    Агент MT5 на этом ПК  : !AGENT!
echo    Терминал MetaTrader   : !TERM!
echo    Данные на сервере     : !SYNC!
echo.
echo --------------------------------------------------
echo      9  - ВКЛЮЧИТЬ ВСЁ
echo      8  - ВЫКЛЮЧИТЬ ВСЁ
echo      7  - ПЕРЕЗАГРУЗИТЬ ВСЁ
echo --------------------------------------------------
echo      БОТ                    АГЕНТ
echo      1 запустить            4 запустить
echo      2 остановить           5 остановить
echo      3 перезапустить        6 перезапустить
echo.
echo      G запустить терминал   H закрыть терминал
echo      L лог бота             K лог агента
echo --------------------------------------------------
echo      0 обновить экран       Q выход
echo.
set /p C=Выбери пункт:

if /i "!C!"=="9" call :all_on
if /i "!C!"=="8" call :all_off
if /i "!C!"=="7" call :all_restart
if /i "!C!"=="1" call :bot enable --now
if /i "!C!"=="2" call :bot disable --now
if /i "!C!"=="3" call :bot restart
if /i "!C!"=="4" call :agent start
if /i "!C!"=="5" call :agent stop
if /i "!C!"=="6" call :agent restart
if /i "!C!"=="G" call :term on
if /i "!C!"=="H" call :term off
if /i "!C!"=="L" call :botlog
if /i "!C!"=="K" call :agentlog
if /i "!C!"=="Q" exit /b
goto menu

:all_on
echo.
echo   Включаю бота на сервере...
%SSH% "systemctl enable --now tagmarkets-bot"
if errorlevel 1 echo   ! сервер не отвечает по SSH
echo   Включаю агента, он поднимет терминал сам...
%PS% -Command "Enable-ScheduledTask -TaskName TagMarketsAgent | Out-Null; Start-ScheduledTask -TaskName TagMarketsAgent"
echo.
echo   Готово. Работает, пока не выключишь сам.
timeout /t 4 >nul
exit /b

:all_off
echo.
echo   Останавливаю бота...
%SSH% "systemctl disable --now tagmarkets-bot"
echo   Останавливаю агента...
%PS% -Command "Stop-ScheduledTask -TaskName TagMarketsAgent; Disable-ScheduledTask -TaskName TagMarketsAgent | Out-Null"
echo   Закрываю терминал...
taskkill /IM terminal64.exe /F >nul 2>&1
echo.
echo   Всё остановлено.
timeout /t 4 >nul
exit /b

:all_restart
echo.
%SSH% "systemctl restart tagmarkets-bot"
%PS% -Command "Stop-ScheduledTask -TaskName TagMarketsAgent; Start-Sleep 3; Enable-ScheduledTask -TaskName TagMarketsAgent | Out-Null; Start-ScheduledTask -TaskName TagMarketsAgent"
echo   Перезапущено.
timeout /t 4 >nul
exit /b

:bot
echo.
%SSH% "systemctl %1 %2 tagmarkets-bot"
if errorlevel 1 (echo   ! Сервер не отвечает по SSH. Перезапусти его в панели FirstByte.) else (echo   Готово.)
timeout /t 4 >nul
exit /b

:agent
if "%1"=="start"   %PS% -Command "Enable-ScheduledTask -TaskName TagMarketsAgent | Out-Null; Start-ScheduledTask -TaskName TagMarketsAgent"
if "%1"=="stop"    %PS% -Command "Stop-ScheduledTask -TaskName TagMarketsAgent; Disable-ScheduledTask -TaskName TagMarketsAgent | Out-Null"
if "%1"=="restart" %PS% -Command "Stop-ScheduledTask -TaskName TagMarketsAgent; Start-Sleep 3; Enable-ScheduledTask -TaskName TagMarketsAgent | Out-Null; Start-ScheduledTask -TaskName TagMarketsAgent"
echo   Готово.
timeout /t 3 >nul
exit /b

:term
if "%1"=="off" (
  taskkill /IM terminal64.exe /F >nul 2>&1
  echo   Терминал закрыт. Без него агент не получит новые сделки.
) else (
  %PS% -Command "Start-Process 'D:\MetaTrader5\terminal64.exe' -WindowStyle Minimized"
  echo   Терминал запущен, агент спрячет окно в течение 15 секунд.
)
timeout /t 4 >nul
exit /b

:botlog
cls
echo === лог бота на сервере ===
%SSH% "journalctl -u tagmarkets-bot -n 25 --no-pager"
if errorlevel 1 echo   Нет связи по SSH.
echo.
pause
exit /b

:agentlog
cls
echo === лог агента ===
if exist "%~dp0agent.log" (%PS% -Command "Get-Content '%~dp0agent.log' -Tail 25 -Encoding UTF8") else (echo Лог пока пуст.)
echo.
pause
exit /b
