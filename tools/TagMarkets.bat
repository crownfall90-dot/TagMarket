@echo off
setlocal enabledelayedexpansion
:: Enable/Start-ScheduledTask trebuyut prav administratora - bez nih punkty
:: 4/6/7/9 molcha lovili "Otkazano v dostupe" i agent ostavalsya ostanovlen.
:: Proveryaem prava cherez net session (ne daet vyvoda, tolko kod vozvrata)
:: i, esli ih net, perezapuskaem etot zhe .bat s temi zhe argumentami cherez UAC.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Nuzhny prava administratora - otkryvayu novoe okno...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs" >nul 2>&1
    timeout /t 2 >nul
    exit /b
)
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

echo    ��� �� �ࢥ� (24/7) : !BOT!
echo    ����� MT5 �� �⮬ ��  : !AGENT!
echo    ��ନ��� MetaTrader   : !TERM!
echo    ����� �� �ࢥ�     : !SYNC!
echo.
echo --------------------------------------------------
echo      9  - �������� ���
echo      8  - ��������� ���
echo      7  - ������������� ���
echo --------------------------------------------------
echo      ���                    �����
echo      1 ��������            4 ��������
echo      2 ��⠭�����           5 ��⠭�����
echo      3 ��१�������        6 ��१�������
echo.
echo      G �������� �ନ���   H ������� �ନ���
echo      L ��� ���             K ��� �����
echo --------------------------------------------------
echo      V ���ᨨ ���� (�⪠�)
echo --------------------------------------------------
echo      0 �������� ��࠭       Q ��室
echo.
set /p C=�롥� �㭪�:

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
if /i "!C!"=="V" call :rollback
if /i "!C!"=="Q" exit /b
goto menu

:all_on
echo.
echo   ������ ��� �� �ࢥ�...
%SSH% "systemctl enable --now tagmarkets-bot"
if errorlevel 1 echo   ! �ࢥ� �� �⢥砥� �� SSH
echo   ������ �����, �� �������� �ନ��� ᠬ...
%PS% -Command "Enable-ScheduledTask -TaskName TagMarketsAgent | Out-Null; Start-ScheduledTask -TaskName TagMarketsAgent"
echo.
echo   ��⮢�. ����⠥�, ���� �� �몫���� ᠬ.
timeout /t 4 >nul
exit /b

:all_off
echo.
echo   ��⠭������� ���...
%SSH% "systemctl disable --now tagmarkets-bot"
echo   ��⠭������� �����...
%PS% -Command "Stop-ScheduledTask -TaskName TagMarketsAgent; Disable-ScheduledTask -TaskName TagMarketsAgent | Out-Null"
echo   ����뢠� �ନ���...
taskkill /IM terminal64.exe /F >nul 2>&1
echo.
echo   ��� ��⠭������.
timeout /t 4 >nul
exit /b

:all_restart
echo.
%SSH% "systemctl restart tagmarkets-bot"
%PS% -Command "Stop-ScheduledTask -TaskName TagMarketsAgent; Start-Sleep 3; Enable-ScheduledTask -TaskName TagMarketsAgent | Out-Null; Start-ScheduledTask -TaskName TagMarketsAgent"
echo   ��१���饭�.
timeout /t 4 >nul
exit /b

:bot
echo.
%SSH% "systemctl %1 %2 tagmarkets-bot"
if errorlevel 1 (echo   ! ��ࢥ� �� �⢥砥� �� SSH. ��१����� ��� � ������ FirstByte.) else (echo   ��⮢�.)
timeout /t 4 >nul
exit /b

:agent
if "%1"=="start"   %PS% -Command "Enable-ScheduledTask -TaskName TagMarketsAgent | Out-Null; Start-ScheduledTask -TaskName TagMarketsAgent"
if "%1"=="stop"    %PS% -Command "Stop-ScheduledTask -TaskName TagMarketsAgent; Disable-ScheduledTask -TaskName TagMarketsAgent | Out-Null"
if "%1"=="restart" %PS% -Command "Stop-ScheduledTask -TaskName TagMarketsAgent; Start-Sleep 3; Enable-ScheduledTask -TaskName TagMarketsAgent | Out-Null; Start-ScheduledTask -TaskName TagMarketsAgent"
echo   ��⮢�.
timeout /t 3 >nul
exit /b

:term
if "%1"=="off" (
  taskkill /IM terminal64.exe /F >nul 2>&1
  echo   ��ନ��� ������. ��� ���� ����� �� ������ ���� ᤥ���.
) else (
  %PS% -Command "Start-Process 'D:\MetaTrader5\terminal64.exe' -WindowStyle Hidden"
  echo   ��ନ��� ����饭 ᪮����, ����� ����� ���� � �祭�� 15 ᥪ㭤.
)
timeout /t 4 >nul
exit /b

:botlog
cls
echo === ��� ��� �� �ࢥ� ===
%SSH% "journalctl -u tagmarkets-bot -n 25 --no-pager"
if errorlevel 1 echo   ��� �裡 �� SSH.
echo.
pause
exit /b

:agentlog
cls
echo === ��� ����� ===
if exist "%~dp0agent.log" (%PS% -Command "Get-Content '%~dp0agent.log' -Tail 25 -Encoding UTF8") else (echo ��� ���� ����.)
echo.
pause
exit /b

:rollback
cls
%PS% -File "%~dp0rollback.ps1"
echo.
pause
exit /b
