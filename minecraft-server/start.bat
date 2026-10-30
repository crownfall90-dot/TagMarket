@echo off
rem Запуск сервера на Windows. Первый раз: start.bat --accept-eula (принимая лицензию Mojang https://aka.ms/MinecraftEULA)
chcp 65001 >nul
cd /d "%~dp0"

if not exist fabric-server-launch.jar (
  echo fabric-server-launch.jar не найден. Запускайте start.bat из папки сервера.
  pause
  exit /b 1
)

if /i "%~1"=="--accept-eula" echo eula=true>eula.txt

findstr /b /c:"eula=true" eula.txt >nul 2>&1
if errorlevel 1 (
  echo Примите EULA: start.bat --accept-eula
  pause
  exit /b 1
)

if not defined JAVA_OPTS set JAVA_OPTS=-Xms2G -Xmx4G
java %JAVA_OPTS% -jar fabric-server-launch.jar nogui
pause
