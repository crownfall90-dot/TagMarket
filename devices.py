"""Вход в приложение для Android без Telegram: одноразовый код из бота → токен устройства.

Mini App в Telegram узнаёт человека по подписи Telegram (initData). В
приложении из Google Play такой подписи нет, поэтому устройство «привязывают»:
в боте команда /app выдаёт код из 8 символов на 10 минут, приложение
обменивает его на личный токен устройства. В базе — только SHA-256 кода и
токена; сам токен показывается приложению один раз и хранится в нём.

Токен открывает те же разделы, что и Mini App, и принимает шаги из Health
Connect. Отозвать устройство можно в боте (/app) или через API.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"     # без 0/O, 1/I/L
CODE_TTL = timedelta(minutes=10)
MAX_CODES = 5
MAX_DEVICES = 10
TOKEN_PREFIX = "pld_"
TOUCH_EVERY = timedelta(minutes=10)


def setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS app_pairing (
            code_hash TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_devices (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS app_devices_owner ON app_devices(owner_id);
    """)
    db.commit()


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _norm_code(code) -> str:
    return "".join(ch for ch in str(code or "").upper() if ch in CODE_ALPHABET)


def new_code(db, owner) -> str:
    """Одноразовый код «XXXX-XXXX» на 10 минут; старые и лишние коды владельца удаляются."""
    now = _now()
    with db:
        db.execute("DELETE FROM app_pairing WHERE expires_at<?", (now.isoformat(),))
        keep = db.execute("SELECT code_hash FROM app_pairing WHERE owner_id=? ORDER BY expires_at DESC",
                          (str(owner),)).fetchall()
        for (stale,) in keep[MAX_CODES - 1:]:
            db.execute("DELETE FROM app_pairing WHERE code_hash=?", (stale,))
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        db.execute("INSERT INTO app_pairing (code_hash,owner_id,expires_at) VALUES (?,?,?)",
                   (_hash(code), str(owner), (now + CODE_TTL).isoformat()))
    return f"{code[:4]}-{code[4:]}"


def pair(db, code, name="") -> dict:
    """Обменять код на токен устройства. ValueError — код неверный или устарел."""
    code = _norm_code(code)
    if len(code) != 8:
        raise ValueError("Код — 8 символов из бота: команда /app")
    name = str(name or "").strip()[:64] or "Android"
    now = _now()
    with db:
        row = db.execute("SELECT owner_id, expires_at FROM app_pairing WHERE code_hash=?", (_hash(code),)).fetchone()
        db.execute("DELETE FROM app_pairing WHERE code_hash=?", (_hash(code),))     # код одноразовый в любом случае
        if row is None or datetime.fromisoformat(row[1]) < now:
            raise ValueError("Код не подходит или устарел — получите новый в боте: /app")
        owner = row[0]
        devices_now = db.execute("SELECT id FROM app_devices WHERE owner_id=? ORDER BY last_seen DESC", (owner,)).fetchall()
        for (old,) in devices_now[MAX_DEVICES - 1:]:
            db.execute("DELETE FROM app_devices WHERE id=?", (old,))
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        device_id = uuid.uuid4().hex
        db.execute("INSERT INTO app_devices (id,owner_id,token_hash,name,created_at,last_seen) VALUES (?,?,?,?,?,?)",
                   (device_id, owner, _hash(token), name, now.isoformat(), now.isoformat()))
    return {"token": token, "device_id": device_id, "owner": owner}


def owner_for(db, token):
    """Владелец токена устройства или None. Отметку «был в сети» пишем не чаще раза в 10 минут."""
    if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX) or len(token) > 128:
        return None
    row = db.execute("SELECT id, owner_id, last_seen FROM app_devices WHERE token_hash=?", (_hash(token),)).fetchone()
    if row is None:
        return None
    now = _now()
    if now - datetime.fromisoformat(row[2]) >= TOUCH_EVERY:
        with db:
            db.execute("UPDATE app_devices SET last_seen=? WHERE id=?", (now.isoformat(), row[0]))
    return row[1]


def devices(db, owner):
    return [{"id": r[0], "name": r[1], "created_at": r[2], "last_seen": r[3]} for r in db.execute(
        "SELECT id,name,created_at,last_seen FROM app_devices WHERE owner_id=? ORDER BY last_seen DESC", (str(owner),))]


def revoke(db, owner, device_id=None) -> int:
    """Отозвать одно устройство или все (device_id=None). Возвращает, сколько отозвано."""
    with db:
        if device_id is None:
            return db.execute("DELETE FROM app_devices WHERE owner_id=?", (str(owner),)).rowcount
        n = db.execute("DELETE FROM app_devices WHERE id=? AND owner_id=?", (device_id, str(owner))).rowcount
    if not n:
        raise LookupError("Устройство не найдено")
    return n
