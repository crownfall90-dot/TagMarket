#!/bin/bash
# Ежедневная резервная копия бота. Ставится таймером systemd (см. backup.timer).
#
# Базы копируем через .backup самой sqlite: простой cp во время записи даёт
# битый файл, а бот пишет постоянно.
set -eu

SRC=/opt/tagmarkets
DATA=$SRC/data                 # store.py/partner.py/accounts.py — все по умолчанию тут,
                               # не в корне проекта (TRADES_DB/STATE_DB/ACCOUNTS_FILE
                               # переопределяют, если сервер настроен иначе)
DEST=$SRC/backup
KEEP=14                      # дней хранения
STAMP=$(date +%Y-%m-%d)
OUT=$DEST/$STAMP

mkdir -p "$OUT"

for db in trades.db state.db; do
    [ -f "$DATA/$db" ] || continue
    sqlite3 "$DATA/$db" ".backup '$OUT/$db'"
done

# счета и настройки: в них пароли, поэтому копия только для root
[ -f "$DATA/accounts.json" ] && cp -p "$DATA/accounts.json" "$OUT/"
[ -f "$SRC/.env" ] && cp -p "$SRC/.env" "$OUT/"

# пустой архив «готов» молча — раньше пути были неверными, и копия годами
# состояла из одного .env; лучше упасть с понятной ошибкой, чем соврать об успехе
if [ -z "$(ls -A "$OUT" 2>/dev/null)" ]; then
    rmdir "$OUT"
    echo "backup.sh: ничего не нашёл для копии в $DATA и $SRC — проверьте пути" >&2
    exit 1
fi

chmod -R go-rwx "$OUT"
tar -czf "$OUT.tar.gz" -C "$DEST" "$STAMP" && rm -rf "$OUT"
chmod 600 "$OUT.tar.gz"

# старое чистим по времени изменения — счёт дней не зависит от имён файлов
find "$DEST" -maxdepth 1 -name '*.tar.gz' -mtime +$KEEP -delete

echo "копия готова: $OUT.tar.gz ($(du -h "$OUT.tar.gz" | cut -f1)), хранится копий: $(ls -1 "$DEST"/*.tar.gz | wc -l)"
