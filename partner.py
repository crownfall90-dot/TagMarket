"""Партнёрский кабинет TagMarkets: события, их оформление и общее состояние.

Отдельно от trades.py, потому что тут нет MetaTrader5 — этот модуль работает
и на Linux-сервере, где живут вебхуки и опрос партнёрского API.
"""

import hashlib
import html
import json
import os
import sqlite3
from datetime import datetime, timezone

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


def remember_client_name(db, row: dict) -> None:
    """Запомнить ФИО клиента по номеру кабинета — берётся из вебхука On
    Registration (fname/lname). On Deposit присылает только customer_no,
    без имени вовсе, поэтому без этой записи депозиту неоткуда его взять."""
    number = str(pick(row, "customer_no", "customer", "client_no") or "").strip()
    name = who(row)
    if number and name and name != "—":
        kv_set(db, f"client_name:{number}", name)


def whose(row, db=None) -> tuple[str, bool]:
    """Чей это кабинет: имя владельца и свой ли он.

    Портал присылает номер вида CU261780 — сам по себе он ничего не говорит.
    Если такой кабинет заведён у НАС (владельца бота, TELEGRAM_CHAT_ID) —
    подставляем имя человека, а событие перестаёт быть «депозитом клиента»:
    это перемещение собственных денег. Бот многопользовательский: гость тоже
    может завести свой счёт с любым cabinet — было бы ошибкой посчитать
    депозит клиента «своим» только потому, что кто-то чужой ввёл тот же номер.

    Для чужого кабинета (не наш) подставляем ФИО, если оно раньше пришло с
    регистрацией того же customer_no (db передан) — иначе только номер.
    """
    number = str(pick(row, "customer_no", "customer", "client_no") or "").strip()
    if number:
        try:
            import accounts
            operator = str(os.getenv("TELEGRAM_CHAT_ID", "")).strip()
            for acc in accounts.load():
                if (str(acc.get("cabinet") or "").strip() == number
                        and (not operator or str(acc.get("owner")) == operator)):
                    return (acc.get("holder") or number), True
        except Exception:       # счета недоступны — обойдёмся номером
            pass
        if db is not None:
            known = kv_get(db, f"client_name:{number}")
            if known:
                return known, False
    return (number or who(row)), False


def whose_label(row, db=None) -> str:
    """Строка «от кого»: ФИО клиента, если известно (своё или запомненное по
    регистрации) — иначе номер кабинета явной подписью («Кабинет CU261825»),
    чтобы не читаться именем человека."""
    name, _ = whose(row, db)
    number = str(pick(row, "customer_no", "customer", "client_no") or "").strip()
    return f"Кабинет {name}" if name == number else name


def pretty_money(row: dict, signed: bool = False) -> str:
    """Сумма в том же виде, что и в остальных уведомлениях: «+0.31 $»."""
    raw = money(row)                # «0.31 USD» — после разбора мусора портала
    number, _, currency = raw.rpartition(" ")
    try:
        import trades
        return trades.amount(float(number.replace(" ", "")), currency, signed=signed)
    except Exception:               # непонятная сумма — отдаём как пришла
        return raw


def cabinet_state(row) -> str:
    """Что сейчас на стратегиях этого кабинета — капитал и накопленный профит.

    Вебхук говорит только про сумму движения. Рядом полезно видеть, сколько
    денег работает: тогда уведомление отвечает и на вопрос «сколько всего»,
    а не только «сколько пришло».
    """
    number = str(pick(row, "customer_no", "customer", "client_no") or "").strip()
    if not number:
        return ""
    try:
        import accounts
        import trades
        cap = kept = 0.0
        seen = set()        # счёт роздан гостям копиями — считаем его один раз
        for acc in accounts.load():
            if str(acc.get("cabinet") or "").strip() != number:
                continue
            if int(acc["login"]) in seen:
                continue
            seen.add(int(acc["login"]))
            trades.use(acc)
            cap += trades.capital()
            kept += trades.retained()
        if not cap:
            return ""
        # сколько стратегий сложили — иначе сумма по кабинету читается как
        # капитал одной стратегии и спорит с уведомлением о сделке
        where = f"на {len(seen)} стратегиях" if len(seen) > 1 else "на стратегии"
        line = f"💎 {where} <b>{trades.amount(cap, 'USD')}</b>"
        if kept >= 0.01:
            line += f" + <b>{trades.amount(kept)}</b> профит"
        return line
    except Exception:       # счета или база недоступны — обойдёмся без строки
        return ""


def wallet_add(db, cabinet: str, amount: float) -> None:
    """Запомнить приход на баланс кабинета (вывод профита со стратегии).

    Портал шлёт вебхук только на пополнение кошелька; сколько там лежало до
    того, как бот начал слушать, он не сообщает и отдельного метода «покажи
    остаток» у кабинета нет. Поэтому копим сами — с оговоркой, что это
    «пришло с такой-то даты», а не истинный остаток.
    """
    if not cabinet or not amount:
        return
    key = f"wallet_in:{cabinet}"
    was = float(kv_get(db, key, 0) or 0)
    kv_set(db, key, f"{was + amount:.2f}")
    if not kv_get(db, f"wallet_since:{cabinet}"):
        import trades
        kv_set(db, f"wallet_since:{cabinet}", trades.clock().isoformat())


def site_move_add(db, cabinet: str, kind: str, amount: float, currency: str = "USD") -> None:
    """Запись в журнал движений на сайте брокера (пополнение кабинета).

    Портал присылает событие, но не отдаёт историю — поэтому журнал ведём сами,
    начиная с момента, когда бот его слышит. Вывод с сайта портал не сообщает
    вообще, его здесь взять неоткуда.
    """
    if not cabinet or not amount:
        return
    import trades
    stamp = trades.clock().replace(microsecond=0).isoformat()
    kv_set(db, f"site_move:{cabinet}:{stamp}:{kind}:{amount:.2f}",
           json.dumps({"kind": kind, "amount": round(float(amount), 2),
                       "currency": (currency or "USD").upper(), "time": stamp}))


def site_moves(db, cabinet: str, since=None, until=None) -> list[dict]:
    """Движения по кабинету на сайте за период, новые сверху."""
    prefix = f"site_move:{cabinet}:"
    out = []
    for key in kv_keys(db, prefix + "%"):
        if not key.startswith(prefix):      # «_» в LIKE — любой символ
            continue
        try:
            item = json.loads(kv_get(db, key) or "")
            moment = datetime.fromisoformat(item["time"])
        except (ValueError, KeyError, TypeError):
            continue
        if (since and moment < since) or (until and moment > until):
            continue
        out.append(item)
    return sorted(out, key=lambda i: i["time"], reverse=True)


def wallet_reset(db, cabinet: str) -> None:
    """Обнулить накопленный баланс кошелька вручную.

    Портал не сообщает о внешних выводах с кошелька Tag Markets (на карту,
    крипту — куда угодно мимо стратегии), поэтому wallet_balance() может
    показывать больше, чем реально лежит там сейчас. Когда человек забрал
    деньги внешне, это единственный способ привести цифру в порядок —
    считаем «с этого момента копим заново», а не пытаемся угадать остаток.
    """
    if not cabinet:
        return
    kv_set(db, f"wallet_in:{cabinet}", "0")
    import trades
    kv_set(db, f"wallet_since:{cabinet}", trades.clock().isoformat())


def wallet_balance(db, cabinet: str) -> tuple[float, str]:
    """Сколько на балансе кабинета и с какой даты считаем. (сумма, дата ISO).

    Приход — из вебхуков портала, расход — то, что вернулось на стратегию
    (это видно в истории MT5 как пополнение капитала). Внешние выводы с
    кошелька портал никак не сообщает, поэтому их тут нет — о чём и
    предупреждаем подписью рядом с цифрой.
    """
    since = kv_get(db, f"wallet_since:{cabinet}")
    if not since:
        return 0.0, ""
    came_in = float(kv_get(db, f"wallet_in:{cabinet}", 0) or 0)

    went_out = 0.0
    try:
        import accounts
        import trades
        from datetime import datetime, timedelta
        start = datetime.fromisoformat(since)
        seen = set()
        for acc in accounts.load():
            if str(acc.get("cabinet") or "").strip() != cabinet:
                continue
            if int(acc["login"]) in seen:
                continue
            seen.add(int(acc["login"]))
            trades.use(acc)
            for r in trades.fetch(start, trades.clock() + timedelta(days=1)):
                # деньги вернулись с кошелька в стратегию: для кошелька это расход
                if (r["is_balance"] and trades.is_transfer(r)
                        and not trades.is_profit_side(r)):
                    own = trades.own_amount(r)
                    if own > 0:
                        went_out += own
    except Exception:
        pass        # счета недоступны — покажем хотя бы приход
    return max(came_in - went_out, 0.0), since


def _event(head: str, row, note: str = "", sign: str = "", extra: str = "", db=None) -> str:
    """Тот же визуальный порядок, что и в trades.fmt_notification() —
    время сверху жирным, заголовок, разделитель, крупная сумма, пояснение
    «от кого» строкой ниже. Разные типы уведомлений (сделка, реинвест,
    депозит в кабинет) должны читаться как одна система, а не вразнобой."""
    stamp = str(when(row) or "").strip()
    if not stamp:
        # вебхуки On Deposit/On Registration не присылают момент операции
        # (webhook_urls() их не запрашивает — портал такого поля не отдаёт) —
        # время получения ботом всё равно понятнее, чем полное отсутствие строки
        import trades
        stamp = trades.clock().strftime("%d.%m.%Y  %H:%M:%S") + " · получено"
    out = [f"🕒 <b>{stamp}</b>", head, THIN, f"<b>{pretty_money(row, bool(sign))}</b>",
           f"👤 {html.escape(whose_label(row, db))}"]
    if note:
        out.append(f"<i>{note}</i>")
    if extra:
        out.append(extra)
    state = cabinet_state(row)
    if state:
        out.append(state)
    return "\n".join(out)


def fmt_deposit(db, row):
    ftd = str(pick(row, "is_ftd", "ftd")).lower() in ("true", "1", "yes")
    _, mine = whose(row)
    if ftd:
        return _event("🔥 <b>Первый депозит клиента</b>", row, db=db)
    if mine:
        # деньги пришли на баланс собственного кабинета: обычно это вывод
        # профита со стратегии, и «депозит клиента» тут прямо врал
        return _event("💰 <b>Пополнение баланса кабинета</b>", row,
                      "на балансе Tag Markets — можно вывести "
                      "или вернуть в стратегию", sign="+", db=db)
    cabinet = str(pick(row, "customer_no", "customer", "client_no") or "").strip()
    total = client_deposits_add(db, cabinet, row) if cabinet else None
    extra = (f"📈 Пополнений от этого клиента: <b>{total[0]}</b>, всего "
             f"<b>{trades_amount(total[1])}</b>" if total else "")
    return _event("💰 <b>Депозит клиента</b>", row, extra=extra, db=db)


def trades_amount(v: float) -> str:
    import trades
    return trades.amount(v, "USD")


def client_deposits_add(db, cabinet: str, row: dict) -> tuple[int, float] | None:
    """Копит счётчик и сумму депозитов чужого клиента — портал не отдаёт его
    историю, поэтому это единственный способ ответить «сколько от него всего
    пришло», не только «сколько сейчас». Отдельно от wallet_*: там речь о
    собственном кошельке владельца, тут — о чужом кабинете."""
    number, _, currency = money(row).rpartition(" ")
    try:
        amount = float(number.replace(" ", ""))
    except ValueError:
        return None
    key = f"client_deposits:{cabinet}"
    count_key = f"client_deposits_count:{cabinet}"
    total = float(kv_get(db, key, 0) or 0) + amount
    count = int(kv_get(db, count_key, 0) or 0) + 1
    kv_set(db, key, f"{total:.2f}")
    kv_set(db, count_key, str(count))
    return count, total


def fmt_withdrawal(row):
    _, mine = whose(row)
    return _event("💸 <b>Вывод с баланса кабинета</b>" if mine
                  else "💸 <b>Вывод у клиента</b>", row)


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
    # bot.py и webhook_server.py пишут сюда из разных процессов одновременно
    # (seen/kv — общая дедупликация вебхука и поллинга); WAL + busy_timeout —
    # см. тот же приём и объяснение в store.open_db()
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("CREATE TABLE IF NOT EXISTS seen (kind TEXT, id TEXT, PRIMARY KEY (kind, id))")
    db.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
    db.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        event_key TEXT NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        read_at TEXT,
        UNIQUE(user_id, event_key)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS notifications_user_time ON notifications(user_id, id DESC)")
    db.commit()
    return db


def record_notification(db, user_id, event_key, kind, title, body) -> bool:
    """Persist a user-visible event once, across bot/webhook retries."""
    if not str(user_id).lstrip("-").isdigit() or not event_key:
        raise ValueError("invalid notification recipient or key")
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute("INSERT OR IGNORE INTO notifications "
                     "(user_id,event_key,kind,title,body,created_at) VALUES (?,?,?,?,?,?)",
                     (str(user_id), str(event_key)[:180], str(kind)[:32],
                      str(title)[:160], str(body)[:1200], now))
    if cur.rowcount:
        # Keep a bounded personal history while preserving the latest events.
        db.execute("DELETE FROM notifications WHERE user_id=? AND id NOT IN "
                   "(SELECT id FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 200)",
                   (str(user_id), str(user_id)))
    db.commit()
    return bool(cur.rowcount)


def notifications_for(db, user_id, limit=50) -> dict:
    uid = str(user_id)
    # удержание доли брокера (PF Deduction) — не событие; старые записи о нём
    # прячем здесь же, чтобы не переписывать историю в базе
    quiet = "AND body NOT LIKE '%PF Deduction%' AND title NOT LIKE '%PF Deduction%'"
    rows = db.execute("SELECT id,kind,title,body,created_at,read_at,event_key FROM notifications "
                      f"WHERE user_id=? {quiet} ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
    unread = db.execute("SELECT COUNT(*) FROM notifications "
                        f"WHERE user_id=? AND read_at IS NULL {quiet}", (uid,)).fetchone()[0]
    return {"items": [dict(zip(("id","kind","title","body","created_at","read_at","event_key"), row))
                      for row in rows], "unread": unread}


def read_notifications(db, user_id, ids=None) -> int:
    uid = str(user_id)
    now = datetime.now(timezone.utc).isoformat()
    if ids is None:
        cur = db.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL",
                         (now, uid))
    else:
        safe = [int(x) for x in ids if type(x) is int and x > 0][:50]
        if not safe:
            return 0
        cur = db.execute("UPDATE notifications SET read_at=? WHERE user_id=? "
                         f"AND id IN ({','.join('?' * len(safe))}) AND read_at IS NULL",
                         (now, uid, *safe))
    db.commit()
    return cur.rowcount


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


def kv_del_exact(db, key: str) -> int:
    """Удалить ровно один ключ, без толкования % и _ как шаблона LIKE.

    Нужен отдельно от kv_del: у него это спецсимволы, а полученный из
    kv_keys() ключ (например, токен приглашения) может содержать «_»
    случайно — тогда LIKE удалил бы заодно и чужие совпавшие записи.
    """
    n = db.execute("DELETE FROM kv WHERE key = ?", (key,)).rowcount
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
