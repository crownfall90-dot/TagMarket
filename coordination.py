"""Server-clock, non-preemptive polling lease shared by all agent machines."""
import json
import time

KEY = "polling_lease"
TTL = 180


def read(db):
    row = db.execute("SELECT value FROM kv WHERE key=?", (KEY,)).fetchone()
    return json.loads(row[0]) if row else None


def claim(db, host, session, role, now=None):
    now = time.time() if now is None else now
    # BEGIN IMMEDIATE serializes claims even across multiple web workers.
    db.execute("BEGIN IMMEDIATE")
    try:
        current = read(db)
        own = current and (current["host"], current["session"]) == (host, session)
        expired = current and current["expires"] <= now
        # A process that stopped producing data gives another machine a full
        # lease window to take over instead of reacquiring on each retry.
        granted = (not current or (own and not expired)
                   or (expired and (not own or now >= current["expires"] + TTL)))
        if granted and (not own or expired):
            current = {"host": host, "session": session, "role": role,
                       "expires": now + TTL}
            db.execute("INSERT OR REPLACE INTO kv(key,value) VALUES (?,?)",
                       (KEY, json.dumps(current)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"granted": bool(granted), "owner": current["host"],
            "ttl": TTL, "retry_after": max(1, int(current["expires"] - now))}


def renew(db, host, session, now=None):
    """Only successful uploads extend ownership; heartbeat alone is not health."""
    now = time.time() if now is None else now
    db.execute("BEGIN IMMEDIATE")
    try:
        current = read(db)
        if current and current["expires"] > now and (current["host"], current["session"]) == (host, session or LEGACY):
            current["expires"] = now + TTL
            db.execute("UPDATE kv SET value=? WHERE key=?", (json.dumps(current), KEY))
        db.commit()
    except Exception:
        db.rollback()
        raise


LEGACY = "legacy"


def permits(db, host, session, now=None):
    lease = read(db)
    now = time.time() if now is None else now
    # Before rollout starts, legacy clients continue working. Once elected,
    # the owner is fenced: stale/legacy uploads cannot overwrite its data.
    return not lease or (lease["expires"] > now and
                         (lease["host"], lease["session"]) == (host, session or LEGACY))


def may_poll_anonymously(db, now=None):
    """Может ли получить список счетов клиент без сессии (агент до аренды).

    Такой клиент не присылает ни хоста, ни сессии, поэтому «кто он» неизвестно;
    пока аренда у живого владельца — он отстранён, а когда её нет или она
    истекла (основная машина офлайн) — пускаем, дальше его закрепит authorize().
    """
    lease = read(db)
    now = time.time() if now is None else now
    return not lease or lease["expires"] <= now or lease["session"] == LEGACY


def authorize(db, host, session, now=None):
    """Право писать данные. Клиент с сессией — по аренде, как раньше.

    Клиент без сессии — резерв на коде до аренды: до этого сервер отстранял его
    навсегда, и когда основная машина уходила офлайн, заменить её было некому
    (аренда истекала, /agent/claim он не знает, любая его загрузка получала
    409). Теперь он захватывает аренду обычным образом: только если её нет
    или она истекла, и тогда держит её на общих основаниях — вернувшаяся
    основная его не вытесняет.
    """
    if session:
        return permits(db, host, session, now)
    return claim(db, host, LEGACY, "legacy", now)["granted"]
