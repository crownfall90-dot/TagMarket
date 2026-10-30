#!/usr/bin/env bash
# Устанавливает сервер The Harpy Express: Extended (Minecraft 1.21.1, Fabric).
# Источник сборки: https://modrinth.com/modpack/the-harpy-express-extended
# Другая сборка: PACK_URL=<ссылка на .mrpack> ./install.sh
set -euo pipefail

cd "$(dirname "$0")"

PACK_URL="${PACK_URL:-https://cdn.modrinth.com/data/2i0gqJXe/versions/SQLyLSA9/The%20Harpy%20Express%20-%20Extended%203.8.141.mrpack}"
INSTALLER_VERSION="${INSTALLER_VERSION:-1.0.1}"
WORK=".install-cache"

command -v java >/dev/null || { echo "Нужна Java 21+ (java не найдена)"; exit 1; }
command -v python3 >/dev/null || { echo "Нужен python3"; exit 1; }

rm -rf "$WORK" && mkdir -p "$WORK/pack"
echo "==> Скачиваю сборку"
curl -fsSL -o "$WORK/pack.mrpack" "$PACK_URL"
python3 -I -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$WORK/pack.mrpack" "$WORK/pack"

echo "==> Скачиваю серверные моды (с проверкой sha512)"
rm -rf mods && mkdir -p mods
python3 -I - "$WORK/pack/modrinth.index.json" <<'PY'
import hashlib, json, os, sys, urllib.request

index = json.load(open(sys.argv[1]))
deps = index["dependencies"]
open(".install-cache/loader.txt", "w").write(f'{deps["minecraft"]} {deps["fabric-loader"]}\n')

for f in index["files"]:
    if f.get("env", {}).get("server") == "unsupported":
        print("  пропуск (только клиент):", f["path"])
        continue
    dest = f["path"]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    data = urllib.request.urlopen(f["downloads"][0]).read()
    if hashlib.sha512(data).hexdigest() != f["hashes"]["sha512"]:
        sys.exit(f"Хеш не совпал: {dest}")
    open(dest, "wb").write(data)
    print("  ok:", dest)
PY

read -r MC_VERSION LOADER_VERSION < "$WORK/loader.txt"
echo "==> Fabric server launcher (MC $MC_VERSION, loader $LOADER_VERSION)"
curl -fsSL -o fabric-server-launch.jar \
  "https://meta.fabricmc.net/v2/versions/loader/$MC_VERSION/$LOADER_VERSION/$INSTALLER_VERSION/server/jar"

echo "==> Конфиги сборки"
cp -rn "$WORK/pack/overrides/config" . 2>/dev/null || true

SAVE_DIR=$(find "$WORK/pack/overrides/saves" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -n 1)
if [ ! -d world ] && [ -n "$SAVE_DIR" ]; then
  echo "==> Копирую карту из сборки в world/"
  cp -r "$SAVE_DIR" world
  rm -f world/session.lock
fi

[ -f server.properties ] || cp server.properties.example server.properties

rm -rf "$WORK"
echo
echo "Готово. Прочитайте EULA (https://aka.ms/MinecraftEULA), затем запустите: ./start.sh --accept-eula"
