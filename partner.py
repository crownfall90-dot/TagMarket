"""Партнёрский кабинет TagMarkets: события, их оформление и общее состояние.

Отдельно от trades.py, потому что тут нет MetaTrader5 — этот модуль работает
и на Linux-сервере, где живут вебхуки и опрос партнёрского API.
"""

import hashlib
import html
import json
import os
import sqlite3

THIN = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"
DB = os.getenv("STATE_DB", os.path.join("data", "state.db"))


# ── схема ответов API не документирована, поэтому берём первое подходящее
# ── поле из списка кандидатов (probe.py показывает реальные имена)
def pick(row: dict, *names, default=""):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return v
    return default


def row_id(row: dict) -> str:
    # tx_id/customer_no — так эти поля называет вебхук (раздел Web Hooks в доках),
    # остальные — как называет их get_leads/get_transactions. Имена должны
    # совпадать, иначе одно событие придёт дважды: из вебхука и из опроса
    key = pick(row, "id", "transaction_id", "trans_id", "tx_id",
               "lead_id", "customer_no", "activity_id", "record_id")
    if key:
        return str(key)
    return hashlib.sha1(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


def money(row: dict) -> str:
    amount = str(pick(row, "amount", "amount_usd", "value", "total"))
    currency = pick(row, "currency", "currency_code", "curr", default="")

    # Портал склеивает параметры: "&currency=" читается как HTML-сущность
    # &curren; и приходит "3073.00¤cy=ZAR" — достаём валюту оттуда.
    if "¤" in amount:
        amount, _, tail = amount.partition("¤")
        currency = currency or tail.partition("=")[2]

    return f"{amount.strip()} {(currency or 'USD').strip()}".strip()


def when(row: dict) -> str:
    return str(pick(row, "date_time", "datetime", "trans_date", "date", "created", "reg_date"))


def who(row: dict) -> str:
    # fname/lname — так называет их вебхук, first_name/last_name — методы API
    name = " ".join(str(pick(row, a, b)) for a, b in (("first_name", "fname"), ("last_name", "lname"))
                    if pick(row, a, b))
    return name or str(pick(row, "name", "full_name", "email", "customer_no", default="—"))


def fmt_deposit(row):
    ftd = str(pick(row, "is_ftd", "ftd")).lower() in ("true", "1", "yes")
    head = "🔥 <b>ПЕРВЫЙ депозит клиента (FTD)</b>" if ftd else "💰 <b>Депозит клиента</b>"
    return f"{head}\n{THIN}\n<b>{money(row)}</b>\n👤 {html.escape(who(row))}\n🕒 {when(row)}"


def fmt_withdrawal(row):
    return (f"💸 <b>Вывод у клиента</b>\n{THIN}\n<b>{money(row)}</b>\n"
            f"👤 {html.escape(who(row))}\n🕒 {when(row)}")


def fmt_lead(row):
    country = pick(row, "country", "country_name")
    tail = f"\n🌍 {html.escape(str(country))}" if country else ""
    return f"👤 <b>Новый реферал</b>\n{THIN}\n{html.escape(who(row))}{tail}\n🕒 {when(row)}"


def fmt_activity(row):
    profit = pick(row, "commission", "ib_commission", "rebate", "net", "profit")
    volume = pick(row, "volume", "lots", "traded_volume")
    lines = ["📈 <b>Активность клиента</b>", THIN, f"👤 {html.escape(who(row))}"]
    if profit:
        lines.append(f"➕ Начислено: <b>{profit}</b>")
    if volume:
        lines.append(f"📊 Объём: {volume}")
    lines.append(f"🕒 {when(row)}")
    return "\n".join(lines)


# ── состояние ─────────────────────────────────────────────────────────────

def open_db(path: str = None):
    db = sqlite3.connect(path or DB)
    db.execute("CREATE TABLE IF NOT EXISTS seen (kind TEXT, id TEXT, PRIMARY KEY (kind, id))")
    db.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
    db.commit()
    return db


def kv_get(db, key, default=None):
    row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


# События кабинета. TRADE_CLOSED здесь — не наши сделки, а доход с сети: чужой
# счёт закрыл сделку, и партнёру капнула доля. Таких событий много и они мелкие
# (бывает 0.06 USD), поэтому их не шлём поштучно, а копим на дневную сводку.
PORTAL_ICONS = {
    "COMMISSION_PAID": "💸",
    "USER_ENROLLED": "🎉",
    "INCENTIVE_ACHIEVED": "🏆",
    "BIRTHDAY": "🎂",
    "MANUAL": "📢",
}
PORTAL_INCOME = "TRADE_CLOSED"      # копится в сводку, а не летит сразу


def portal_amount(row: dict) -> float:
    """Сколько партнёр заработал на этом событии."""
    tv = row.get("templateVariables") or {}
    try:
        return float(tv.get("amount") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def fmt_portal(row: dict) -> str:
    """Событие партнёрского кабинета для Telegram."""
    icon = PORTAL_ICONS.get(row.get("eventType"), "🔔")
    title = html.escape(str(row.get("title") or "Событие кабинета"))
    body = html.escape(str(row.get("body") or "")).strip()
    when = str(row.get("createdAt") or row.get("created") or "")[:16].replace("T", " ")
    out = [f"{icon} <b>{title}</b>"]
    if body:
        out.append(body)
    if when:
        out.append(f"<i>{when}</i>")
    return "\n".join(out)


def kv_keys(db, like: str) -> list[str]:
    """Ключи по шаблону SQL LIKE, напр. 'invite:%'."""
    return [r[0] for r in db.execute("SELECT key FROM kv WHERE key LIKE ?", (like,)).fetchall()]


def kv_del(db, like: str) -> int:
    """Удалить ключи по шаблону. Возвращает, сколько удалено."""
    n = db.execute("DELETE FROM kv WHERE key LIKE ?", (like,)).rowcount
    db.commit()
    return n


def kv_set(db, key, value):
    db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, str(value)))
    db.commit()


SEEN_KEEP = 5000    # сколько последних событий каждого вида помним для дедупликации


def unseen(db, kind: str, rows: list[dict]) -> tuple[list[dict], bool]:
    """Новые записи + признак первого запуска (тогда только запоминаем, не шлём)."""
    first_run = db.execute("SELECT 1 FROM seen WHERE kind=? LIMIT 1", (kind,)).fetchone() is None
    fresh = []
    for row in rows:
        rid = row_id(row)
        cur = db.execute("INSERT OR IGNORE INTO seen VALUES (?, ?)", (kind, rid))
        if cur.rowcount:
            fresh.append(row)

    if fresh:   # держим таблицу в разумных рамках: для дедупликации хватает
        db.execute(   # свежих записей, а старые копились бы годами
            "DELETE FROM seen WHERE kind=? AND rowid NOT IN "
            "(SELECT rowid FROM seen WHERE kind=? ORDER BY rowid DESC LIMIT ?)",
            (kind, kind, SEEN_KEEP))
    db.commit()
    return fresh, first_run
