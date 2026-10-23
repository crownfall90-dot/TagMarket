"""Мгновенные уведомления на телефон через Firebase Cloud Messaging (FCM).

Приложение для Android после входа присылает свой FCM-токен (POST /api/device/push),
он хранится у привязанного устройства. Фоновая задача сервера раз в несколько секунд
берёт новые события ленты (таблица notifications — тот же колокольчик) и отправляет
их на телефоны владельца. Сообщения «data»: уведомление рисует само приложение, и
одно событие не показывается дважды, даже если его же найдёт проверка раз в 15 минут.

Ключ сервера Firebase (JSON сервисного аккаунта) лежит в файле FCM_SERVICE_ACCOUNT
(.env, доступ только владельцу сервера). Нет ключа — модуль молчит, остаётся
проверка раз в 15 минут из приложения.
"""
import asyncio
import base64
import json
import logging
import os
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger("push")
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
EVERY = 3                    # секунд между проверками новых событий
BATCH = 50
KEY_LAST = "push:last_id"

_cache = {"token": None, "exp": 0.0, "account": None, "mtime": None}


def setup(db):
    cols = {r[1] for r in db.execute("PRAGMA table_info(app_devices)")}
    if "push_token" not in cols:
        db.execute("ALTER TABLE app_devices ADD COLUMN push_token TEXT")
    db.commit()


def set_token(db, device_token, push_token) -> bool:
    """Запомнить FCM-токен устройства, с которого пришёл запрос."""
    import devices
    push_token = str(push_token or "").strip()
    if not push_token or len(push_token) > 4096 or not push_token.isprintable():
        raise ValueError("Некорректный токен уведомлений")
    with db:
        # один телефон — одна запись: токен, переехавший на другое устройство, снимаем со старого
        db.execute("UPDATE app_devices SET push_token=NULL WHERE push_token=?", (push_token,))
        n = db.execute("UPDATE app_devices SET push_token=? WHERE token_hash=?",
                       (push_token, devices._hash(device_token))).rowcount
    return bool(n)


def account():
    """Сервисный аккаунт Firebase из файла FCM_SERVICE_ACCOUNT или None."""
    path = os.getenv("FCM_SERVICE_ACCOUNT", "").strip()
    if not path or not os.path.isfile(path):
        return None
    mtime = os.path.getmtime(path)
    if _cache["account"] is None or _cache["mtime"] != mtime:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("type") != "service_account" or not data.get("private_key") or not data.get("project_id"):
            log.warning("FCM_SERVICE_ACCOUNT: это не ключ сервисного аккаунта Firebase")
            return None
        _cache.update(account=data, mtime=mtime, token=None, exp=0.0)
    return _cache["account"]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _access_token(acc) -> str:
    """OAuth-токен Google для FCM: JWT, подписанный ключом сервисного аккаунта (RS256)."""
    if _cache["token"] and time.time() < _cache["exp"] - 60:
        return _cache["token"]
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    now = int(time.time())
    uri = acc.get("token_uri") or "https://oauth2.googleapis.com/token"
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({"iss": acc["client_email"], "scope": SCOPE, "aud": uri,
                              "iat": now, "exp": now + 3600}).encode())
    key = serialization.load_pem_private_key(acc["private_key"].encode(), password=None)
    signature = key.sign(f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    body = urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                      "assertion": f"{head}.{claims}.{_b64(signature)}"}).encode()
    with urlopen(Request(uri, data=body, method="POST"), timeout=15) as r:
        data = json.loads(r.read())
    _cache.update(token=data["access_token"], exp=time.time() + int(data.get("expires_in", 3600)))
    return _cache["token"]


def send(acc, push_token, event) -> str:
    """Отправить событие на один телефон: 'ok', 'gone' (токен больше не действует) или 'error'."""
    message = {"message": {
        "token": push_token,
        "android": {"priority": "HIGH", "ttl": "86400s"},
        "data": {"id": str(event["id"]), "kind": str(event.get("kind") or ""),
                 "title": str(event["title"])[:160], "body": str(event.get("body") or "")[:1200]},
    }}
    url = f"https://fcm.googleapis.com/v1/projects/{acc['project_id']}/messages:send"
    req = Request(url, data=json.dumps(message).encode(), method="POST",
                  headers={"Authorization": f"Bearer {_access_token(acc)}",
                           "Content-Type": "application/json; charset=utf-8"})
    try:
        with urlopen(req, timeout=15):
            return "ok"
    except HTTPError as e:
        if e.code in (400, 404):
            text = e.read().decode("utf-8", "replace")
            if "UNREGISTERED" in text or "INVALID_ARGUMENT" in text and "token" in text.lower():
                return "gone"
        if e.code == 401:
            _cache.update(token=None, exp=0.0)
        log.warning("FCM: ответ %s", e.code)
        return "error"
    except OSError as e:
        log.warning("FCM: нет связи (%s)", e)
        return "error"


def pending(db, last_id):
    """Новые события после last_id вместе с FCM-токенами телефонов их владельцев."""
    rows = db.execute("SELECT id,user_id,kind,title,body FROM notifications WHERE id>? ORDER BY id LIMIT ?",
                      (last_id, BATCH)).fetchall()
    out = []
    for nid, uid, kind, title, body in rows:
        tokens = [t for (t,) in db.execute(
            "SELECT push_token FROM app_devices WHERE owner_id=? AND push_token IS NOT NULL", (str(uid),))]
        out.append(({"id": nid, "kind": kind, "title": title, "body": body}, tokens))
    return out


async def deliver(db) -> int:
    """Один проход: отправить новые события. Возвращает, сколько сообщений ушло.

    База — в потоке сервера (соединение SQLite общее), в отдельный поток уходит
    только сетевой запрос к Google."""
    import partner
    acc = account()
    newest = db.execute("SELECT COALESCE(MAX(id),0) FROM notifications").fetchone()[0]
    raw = partner.kv_get(db, KEY_LAST)
    if acc is None or raw is None:
        # первый запуск (или ключа нет): не рассылаем накопленную историю
        partner.kv_set(db, KEY_LAST, str(newest))
        return 0
    last, sent = int(raw), 0
    for event, tokens in pending(db, last):
        for tok in tokens:
            result = await asyncio.to_thread(send, acc, tok, event)
            if result == "gone":
                with db:
                    db.execute("UPDATE app_devices SET push_token=NULL WHERE push_token=?", (tok,))
            sent += result == "ok"
        last = event["id"]
        partner.kv_set(db, KEY_LAST, str(last))
    return sent


async def loop(app):
    """Фоновая рассылка, пока работает сервер."""
    db = app["db"]
    while True:
        try:
            await deliver(db)
        except asyncio.CancelledError:
            raise
        except Exception:             # сбой одной рассылки не должен останавливать остальные
            log.exception("push: рассылка не удалась")
        await asyncio.sleep(EVERY)


async def start(app):
    app["push_task"] = asyncio.create_task(loop(app))


async def stop(app):
    task = app.get("push_task")
    if task:
        task.cancel()
