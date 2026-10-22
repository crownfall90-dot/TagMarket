"""Резервная копия баз: раз в сутки снимок SQLite, сжатый gzip.

Снимок делается через sqlite3 backup API — он согласован даже во время
записи (бот и Mini App пишут в базу постоянно, простое копирование файла
могло поймать её на середине транзакции). Хранится BACKUP_KEEP последних
дней; самый свежий снимок state.db бот отправляет основателю в Telegram,
чтобы копия жила не только на том же сервере.
"""
from datetime import date
import gzip
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

DIR = Path(os.getenv("BACKUP_DIR", os.path.join("data", "backups")))
KEEP = int(os.getenv("BACKUP_KEEP", "7"))
SEND_LIMIT = 45 * 1024 * 1024        # Telegram принимает документы до 50 МБ


def snapshot(source: str, dest_dir: Path = None, day: date = None) -> Path | None:
    """Снимок базы source в dest_dir/<имя>-<дата>.db.gz; None — базы нет."""
    if not source or not os.path.exists(source):
        return None
    dest_dir = Path(dest_dir or DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(source).stem
    target = dest_dir / f"{stem}-{(day or date.today()).isoformat()}.db.gz"
    with tempfile.TemporaryDirectory(dir=dest_dir) as tmp:
        raw = Path(tmp) / f"{stem}.db"
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            out = sqlite3.connect(raw)
            try:
                src.backup(out)
            finally:
                out.close()
        finally:
            src.close()
        part = target.with_suffix(".part")
        with open(raw, "rb") as f_in, gzip.open(part, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.replace(part, target)        # недописанный архив не выдаёт себя за готовый
    os.chmod(target, 0o600)             # внутри личные данные — только владельцу сервера
    prune(dest_dir, stem)
    return target


def prune(dest_dir: Path, stem: str, keep: int = None) -> None:
    keep = KEEP if keep is None else keep
    old = sorted(dest_dir.glob(f"{stem}-*.db.gz"))
    for path in old[:-keep] if keep > 0 else old:
        path.unlink(missing_ok=True)


def restore_check(path: Path) -> bool:
    """Архив читается и база в нём цела (PRAGMA integrity_check)."""
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "check.db"
        with gzip.open(path, "rb") as f_in, open(raw, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        db = sqlite3.connect(raw)
        try:
            return db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            db.close()
