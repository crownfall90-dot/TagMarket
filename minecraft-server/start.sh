#!/usr/bin/env bash
# Запуск сервера. Первый раз: ./start.sh --accept-eula (принимая лицензию Mojang https://aka.ms/MinecraftEULA)
set -euo pipefail
cd "$(dirname "$0")"

[ -f fabric-server-launch.jar ] || { echo "Сначала запустите ./install.sh"; exit 1; }

if [ "${1:-}" = "--accept-eula" ]; then
  echo "eula=true" > eula.txt
  shift
fi
grep -qs '^eula=true' eula.txt || { echo "Примите EULA: ./start.sh --accept-eula"; exit 1; }

exec java ${JAVA_OPTS:--Xms2G -Xmx4G} -jar fabric-server-launch.jar nogui "$@"
