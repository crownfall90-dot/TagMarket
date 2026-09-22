"""Партнёрский кабинет TagMarkets: события, их оформление и общее состояние.

Отдельно от trades.py, потому что тут нет MetaTrader5 — этот модуль работает
и на Linux-сервере, где живут вебхуки и опрос партнёрского API.
"""

import hashlib
import html
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

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


def parsed_amount(row: dict) -> tuple[float, str] | None:
    """Сумма события как число и валюта, или None, если не разобрать.

    money(row) отдаёт «1234.56 USD» — общий для всех событий портала формат;
    rpartition по последнему пробелу устойчивее, чем split по первому, если
    в самой сумме вдруг окажется внутренний пробел. Портал иногда шлёт
    разделитель тысяч узким неразрывным пробелом (U+202F), а не обычным —
    снимаем оба, иначе float() падает на «3 073.00» с этим пробелом внутри.
    """
    number, _, currency = money(row).rpartition(" ")
    try:
        return float(number.replace(" ", "").replace(" ", "")), currency
    except ValueError:
        return None


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


def whose_label(row, name: str) -> str:
    """Строка «от кого»: ФИО клиента, если известно (своё или запомненное по
    регистрации) — иначе номер кабинета явной подписью («Кабинет CU261825»),
    чтобы не читаться именем человека. `name` — уже вычисленный whose(row, db)[0],
    чтобы не читать и не расшифровывать accounts.json второй раз на тот же вызов."""
    number = str(pick(row, "customer_no", "customer", "client_no") or "").strip()
    return f"Кабинет {name}" if name == number else name


def pretty_money(row: dict, signed: bool = False) -> str:
    """Сумма в том же виде, что и в остальных уведомлениях: «+0.31 $»."""
    parsed = parsed_amount(row)
    if not parsed:                  # непонятная сумма — отдаём как пришла
        return money(row)
    import trades
    return trades.amount(parsed[0], parsed[1], signed=signed)


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
    # случайный хвост ключа: два одинаковых пополнения в одну секунду иначе
    # ложились в одну запись, и журнал терял второе
    kv_set(db, f"site_move:{cabinet}:{stamp}:{kind}:{amount:.2f}:{uuid.uuid4().hex[:8]}",
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


def _event(head: str, row, name: str, note: str = "", sign: str = "", extra: str = "") -> str:
    """Тот же визуальный порядок, что и в trades.fmt_notification() —
    время сверху жирным, заголовок, разделитель, крупная сумма, пояснение
    «от кого» строкой ниже. Разные типы уведомлений (сделка, реинвест,
    депозит в кабинет) должны читаться как одна система, а не вразнобой.
    `name` — уже вычисленный whose(row, db)[0], см. whose_label."""
    stamp = str(when(row) or "").strip()
    if not stamp:
        # вебхуки On Deposit/On Registration не присылают момент операции
        # (webhook_urls() их не запрашивает — портал такого поля не отдаёт) —
        # время получения ботом всё равно понятнее, чем полное отсутствие строки
        import trades
        stamp = trades.clock().strftime("%d.%m.%Y  %H:%M:%S") + " · получено"
    # время и сумма приходят из параметров вебхука как есть — экранируем:
    # «<» или «&» в них ломали разметку, и Telegram отвергал сообщение целиком
    out = [f"🕒 <b>{html.escape(stamp)}</b>", head, THIN,
           f"<b>{html.escape(pretty_money(row, bool(sign)))}</b>",
           f"👤 {html.escape(whose_label(row, name))}"]
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
    name, mine = whose(row, db)
    if ftd:
        return _event("🔥 <b>Первый депозит клиента</b>", row, name)
    if mine:
        # деньги пришли на баланс собственного кабинета: обычно это вывод
        # профита со стратегии, и «депозит клиента» тут прямо врал
        return _event("💰 <b>Пополнение баланса кабинета</b>", row, name,
                      "на балансе Tag Markets — можно вывести "
                      "или вернуть в стратегию", sign="+")
    cabinet = str(pick(row, "customer_no", "customer", "client_no") or "").strip()
    total = client_deposits_add(db, cabinet, row) if cabinet else None
    import trades
    extra = (f"📈 Пополнений от этого клиента: <b>{total[0]}</b>, всего "
             f"<b>{trades.amount(total[1], 'USD')}</b>" if total else "")
    return _event("💰 <b>Депозит клиента</b>", row, name, extra=extra)


def client_deposits_add(db, cabinet: str, row: dict) -> tuple[int, float] | None:
    """Копит счётчик и сумму депозитов чужого клиента — портал не отдаёт его
    историю, поэтому это единственный способ ответить «сколько от него всего
    пришло», не только «сколько сейчас». Отдельно от wallet_*: там речь о
    собственном кошельке владельца, тут — о чужом кабинете."""
    parsed = parsed_amount(row)
    if not parsed or not parsed[0]:
        return None
    amount = parsed[0]
    key = f"client_deposits:{cabinet}"
    count_key = f"client_deposits_count:{cabinet}"
    total = float(kv_get(db, key, 0) or 0) + amount
    count = int(kv_get(db, count_key, 0) or 0) + 1
    kv_set(db, key, f"{total:.2f}")
    kv_set(db, count_key, str(count))
    return count, total


def fmt_withdrawal(row, db=None):
    # имя передаётся в _event явно (см. whose_label) — без него вызов падал
    # TypeError на первом же выводе
    name, mine = whose(row, db)
    return _event("💸 <b>Вывод с баланса кабинета</b>" if mine
                  else "💸 <b>Вывод у клиента</b>", row, name)


def fmt_lead(row):
    country = pick(row, "country", "country_name")
    tail = f"\n🌍 {html.escape(str(country))}" if country else ""
    return (f"👤 <b>Новый реферал</b>\n{THIN}\n{html.escape(who(row))}{tail}"
            f"\n🕒 {html.escape(when(row))}")


def fmt_activity(row):
    profit = pick(row, "commission", "ib_commission", "rebate", "net", "profit")
    volume = pick(row, "volume", "lots", "traded_volume")
    lines = ["📈 <b>Активность клиента</b>", THIN, f"👤 {html.escape(who(row))}"]
    if profit:
        lines.append(f"➕ Начислено: <b>{html.escape(str(profit))}</b>")
    if volume:
        lines.append(f"📊 Объём: {html.escape(str(volume))}")
    lines.append(f"🕒 {html.escape(when(row))}")
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


def update_notification(db, user_id, event_key, title, body, kind=None) -> bool:
    """Переписать уже сохранённое событие ленты — когда уточнились подробности."""
    cur = db.execute("UPDATE notifications SET title=?, body=?, kind=COALESCE(?, kind) "
                     "WHERE user_id=? AND event_key=?",
                     (str(title)[:160], str(body)[:1200], str(kind)[:32] if kind else None,
                      str(user_id), str(event_key)[:180]))
    db.commit()
    return bool(cur.rowcount)


# ── одно событие — одно сообщение ─────────────────────────────────────────
# Перевод денег между стратегией и балансом Tag Markets виден с двух сторон:
# вебхук портала «пополнение баланса кабинета» приходит через секунды, строка
# истории MT5 («профит списан со стратегии», «заведено на стратегию») — когда
# агент дойдёт до счёта, через минуту-две. Человеку это одно событие, а в чат
# падали два сообщения. Теперь сообщает тот, кто увидел событие первым;
# второй молчит, а если знает больше (MT5 точнее вебхука), доводит уже
# отправленное сообщение до своего вида. Реестр общий для процессов вебхука
# и бота — в KV, под BEGIN IMMEDIATE.
TWIN_WINDOW = 600           # секунд между двумя сигналами одного перевода
TWIN_KEEP = 7 * 86400       # столько помним сигналы (агент бывает офлайн днями)


def _twin_items(db, key) -> list:
    try:
        items = json.loads(kv_get(db, key) or "[]")
    except (TypeError, ValueError):
        return []
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _twin_time(item):
    try:
        return datetime.fromisoformat(item.get("t") or "")
    except (TypeError, ValueError):
        return None


def _twin_write(db, key, change):
    """Прочитать реестр, поправить и записать одной транзакцией: бот и вебхук
    заявляют сигналы из разных процессов, и без BEGIN IMMEDIATE оба могли бы
    прочитать пустой реестр и оба решить, что сообщают первыми."""
    if db.in_transaction:
        db.commit()
    db.execute("BEGIN IMMEDIATE")
    try:
        items = _twin_items(db, key)
        result = change(items)
        db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, json.dumps(items)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def twin_claim(db, cabinet: str, cents: int, when: datetime, source: str, exact: bool,
               ref: str = "", fields: dict = None, edit: dict = None) -> tuple[str, dict | None]:
    """Заявить сигнал о переводе суммы cents (в центах) между стратегией и
    балансом кабинета. source — "hook" или "mt5"; exact — текст сигнала уже
    в точном виде MT5.

    (id, None) — сигнал первый, вызывающий сообщает сам. Так же при повторе
    своего сигнала с тем же ref (тикет MT5): прошлая отправка не удалась.
    (id двойника, его запись до изменений) — другая сторона уже заявила этот
    перевод в пределах TWIN_WINDOW, второе сообщение не нужно. Если свой
    текст точнее, а двойник ещё не отправил сообщение, edit ложится в его
    запись — двойник поправит текст сам, как только узнает id сообщения.
    """
    import trades
    horizon = trades.clock() - timedelta(seconds=TWIN_KEEP)

    def gap(item):
        return abs((_twin_time(item) - when).total_seconds())

    def change(items):
        items[:] = [i for i in items if (_twin_time(i) or horizon) > horizon]
        mine = next((i for i in items if ref and i.get("s") == source
                     and i.get("ref") == ref), None)
        if mine:
            mine.pop("failed", None)
            return mine["id"], None
        twins = [i for i in items if i.get("c") == cents and i.get("s") != source
                 and not i.get("m") and not i.get("failed") and _twin_time(i)
                 and gap(i) <= TWIN_WINDOW]
        if twins:
            twin = min(twins, key=gap)      # ближайший по времени — тот же перевод
            before = dict(twin)
            twin["m"] = True
            if exact and not twin.get("exact"):
                twin["exact"] = True        # дальше текст — этого сигнала
                if not twin.get("msg"):
                    twin["edit"] = edit
            return twin["id"], before
        item = {**(fields or {}), "id": uuid.uuid4().hex[:10], "c": cents,
                "t": when.isoformat(), "s": source, "ref": ref, "exact": bool(exact),
                "m": False}
        items.append(item)
        return item["id"], None

    return _twin_write(db, f"wallet_twins:{cabinet}", change)


def twin_update(db, cabinet: str, twin_id: str, **changes) -> dict | None:
    """Дописать в запись сигнала (id сообщения, снятый edit); вернуть её целиком."""
    def change(items):
        item = next((i for i in items if i.get("id") == twin_id), None)
        if item is None:
            return None
        item.update(changes)
        return dict(item)

    return _twin_write(db, f"wallet_twins:{cabinet}", change)


async def announce_once(db, cabinet: str, cents: int, when: datetime, source: str,
                        exact: bool, text: str, feed: tuple, chat: str, send, edit,
                        ref: str = "") -> str:
    """Сообщить о переводе, если о нём ещё не сообщила другая сторона.

    feed — (kind, event_key, title, body) для ленты Mini App; chat — кому:
    и чат для Telegram, и владелец ленты. send(text) отправляет и возвращает
    id сообщения (None — не удалось, 0 — ушло, но id неизвестен),
    edit(chat, msg, text) правит уже отправленное. Транспорт у бота и у
    вебхука свой, порядок — общий.
    Возвращает "sent", "merged" (второй сигнал: промолчали или поправили
    первое сообщение) или "failed".
    """
    kind, event_key, title, body = feed
    target = {"text": text, "kind": kind, "title": title, "body": body}
    tid, twin = twin_claim(db, cabinet, cents, when, source, exact, ref=ref,
                           fields={"chat": str(chat), "feed": event_key}, edit=target)
    if twin is not None:
        if exact and not twin.get("exact") and twin.get("msg"):
            await _twin_apply(db, edit, twin, target)
        return "merged"
    record_notification(db, chat, event_key, kind, title, body)
    msg = await send(text)
    rec = twin_update(db, cabinet, tid,
                      **({"failed": True} if msg is None else {"msg": msg})) or {}
    pending = rec.get("edit")
    if pending:
        # точный сигнал пришёл, пока это сообщение ещё отправлялось
        twin_update(db, cabinet, tid, edit=None)
        if msg:
            await _twin_apply(db, edit, rec, pending)
        elif msg is None:
            # своё не ушло, а двойник молчит, полагаясь на нас, — шлём его текст
            msg = await send(pending["text"])
            if msg is not None:
                twin_update(db, cabinet, tid, msg=msg, failed=False)
                update_notification(db, chat, event_key, pending["title"],
                                    pending["body"], pending["kind"])
    return "failed" if msg is None else "sent"


async def _twin_apply(db, edit, rec: dict, target: dict) -> None:
    """Довести первое сообщение и запись ленты до точного вида."""
    await edit(rec["chat"], rec["msg"], target["text"])
    if rec.get("feed"):
        update_notification(db, rec["chat"], rec["feed"], target["title"],
                            target["body"], target["kind"])


def own_income_notice(db, row: dict) -> dict | None:
    """Приход на баланс своего кабинета — готовое к announce_once сообщение.

    Если агент уже прислал строку MT5 об этом же переводе, текст сразу точный:
    ровно такой, какой прислал бы бот (и под тем же ключом ленты). Иначе —
    в том же стиле, но с нейтральным заголовком (fmt_wallet_income): бот
    поправит сообщение, когда дойдёт до строки. None — сообщать некому или
    сумму не разобрать, тогда вебхук пишет по-старому.
    """
    import accounts
    import trades
    chat = str(os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    cabinet = str(pick(row, "customer_no", "customer", "client_no") or "").strip()
    parsed = parsed_amount(row)
    if not chat or not cabinet or not parsed or parsed[0] <= 0:
        return None
    cents = round(parsed[0] * 100)
    when = trades.clock()
    accs = accounts.dedup([a for a in accounts.load()
                           if str(a.get("cabinet") or "").strip() == cabinet
                           and str(a.get("owner")) == chat])
    notice = {"cabinet": cabinet, "cents": cents, "when": when, "chat": chat}
    found = None
    window = timedelta(seconds=TWIN_WINDOW)
    try:
        for acc in accs:
            trades.use(acc)
            for r in trades.fetch(when - window, when + window):
                if round(trades.wallet_transfer(r) * 100) == cents:
                    gap = abs((r["time"] - when).total_seconds())
                    if found is None or gap < found[0]:
                        found = (gap, acc, r)
        if found:
            _, acc, r = found
            trades.use(acc)         # текст берёт капитал текущего счёта
            text, title, body = trades.fmt_account_event(acc, r, trades.currency())
            if text:
                return {**notice, "exact": True, "text": text,
                        "feed": (trades.event_kind(r), f"trade:{acc['login']}:{r['ticket']}",
                                 title, body)}
    except Exception:       # история недоступна — хватит и нейтрального текста
        pass
    text, title, body = fmt_wallet_income(row, whose(row, db)[0], when, accs)
    return {**notice, "exact": False, "text": text,
            "feed": ("deposits", f"wallet:{cabinet}:{row_id(row)}", title, body)}


def fmt_wallet_income(row: dict, name: str, when: datetime,
                      accs: list[dict]) -> tuple[str, str, str]:
    """Приход на баланс своего кабинета — в том же виде, что уведомления MT5:
    (текст для Telegram, заголовок и текст для ленты).

    Пока строки MT5 нет, неизвестно, вывод это со стратегии или пополнение
    с карты, — поэтому заголовок нейтральный. Когда агент пришлёт операцию,
    это же сообщение правится до точного вида MT5 (см. announce_once).
    accs — свои счета в этом кабинете: если он один, шапка та же, что у
    уведомлений MT5 (стратегия, владелец и номер счёта).
    """
    import trades
    parsed = parsed_amount(row)
    cabinet = str(pick(row, "customer_no", "customer", "client_no") or "").strip()
    holder = name if name != cabinet else ""
    if len(accs) == 1:
        acc = accs[0]
        title = acc.get("strategy") or acc["name"]
        sub = f"{html.escape(acc.get('holder') or holder or cabinet)} · <code>{acc['login']}</code>"
    else:
        title = holder or f"Кабинет {cabinet}"
        sub = f"кабинет {html.escape(cabinet)}"
    total = (f"{trades.money(parsed[0])}{trades.sign(parsed[1])}" if parsed else money(row))
    body = [f"🕒 <b>{when:%d.%m.%Y  %H:%M:%S}</b>", "💰 <b>Пополнение баланса Tag Markets</b>",
            THIN, f"<b>{html.escape(total)}</b>",
            "➡️ На балансе Tag Markets — можно вывести или вернуть в стратегию"]
    state = cabinet_state(row)
    if state:
        body.append(state)
    body = "\n".join(body)
    text = f"🏷 <b>{html.escape(title)}</b>\n<i>{sub}</i>\n{THIN}\n{body}"
    return text, f"{title} · Пополнение", html.unescape(re.sub(r"<[^>]+>", "", body))


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
        out.append(f"<i>{html.escape(when)}</i>")
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
