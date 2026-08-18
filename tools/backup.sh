#!/bin/bash
# Ежедневная резервная копия бота. Ставится таймером systemd (см. backup.timer).
#
# Базы копируем через .backup самой sqlite: простой cp во время записи даёт
# битый файл, а бот пишет постоянно.
set -eu

SRC=/opt/tagmarkets
DEST=$SRC/backup
KEEP=14                      # дней хранения
STAMP=$(date +%Y-%m-%d)
OUT=$DEST/$STAMP

mkdir -p "$OUT"

for db in trades.db state.db; do
    [ -f "$SRC/$db" ] || continue
    sqlite3 "$SRC/$db" ".backup '$OUT/$db'"
done

# счета и настройки: в них пароли, поэтому копия только для root
for f in accounts.json .env; do
    [ -f "$SRC/$f" ] && cp -p "$SRC/$f" "$OUT/"
done

chmod -R go-rwx "$OUT"
tar -czf "$OUT.tar.gz" -C "$DEST" "$STAMP" && rm -rf "$OUT"
chmod 600 "$OUT.tar.gz"

# старое чистим по времени изменения — счёт дней не зависит от имён файлов
find "$DEST" -maxdepth 1 -name '*.tar.gz' -mtime +$KEEP -delete

echo "копия готова: $OUT.tar.gz ($(du -h "$OUT.tar.gz" | cut -f1)), хранится копий: $(ls -1 "$DEST"/*.tar.gz | wc -l)"
