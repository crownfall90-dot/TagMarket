"""Зарплата: до трёх зачислений в месяц — аванс, зарплата и премия.

Каждое зачисление — сумма и число месяца (1–31; в коротком месяце 31-е
становится последним днём). Если выбрана карта и включено «зачислять на
карту», в день выплаты Platformer сам прибавляет сумму к балансу счёта и
пишет операцию в его историю — один раз за каждую дату, начиная с дня, когда
зачисление добавили. Всё вместе считается доходом: в месяц и в день.
"""
from datetime import date, datetime, time, timedelta, timezone
import calendar
import uuid

import banks
from spend import CURRENCIES, _cents, _text, today

KINDS = {"advance": "Аванс", "salary": "Зарплата", "bonus": "Премия"}
ZONE = timezone(timedelta(hours=3))
PAY_TIME = time(9, 0)
UPCOMING_DAYS = 31


def setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS income_items (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            amount_cents INTEGER NOT NULL,
            currency TEXT NOT NULL,
            day INTEGER NOT NULL,
            account_id TEXT,
            credit INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            since TEXT NOT NULL,
            credited TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(owner_id, kind)
        );
    """)
    # у зачислений, которым сменили тип, прежнее название («Зарплата») осталось
    # от старого типа: «Премия» показывалась как «Зарплата»
    for kind, label in KINDS.items():
        marks = ",".join("?" for _ in KINDS if _ != kind)
        db.execute(f"UPDATE income_items SET title='' WHERE kind=? AND title IN ({marks})",
                   (kind, *[v for k, v in KINDS.items() if k != kind]))
    db.commit()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pay_date(year, month, day):
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def pay_dates(day, start, end):
    """Даты выплат с числом day в отрезке [start, end]."""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        at = pay_date(y, m, day)
        if start <= at <= end:
            out.append(at)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def next_pay(day, on):
    at = pay_date(on.year, on.month, day)
    if at >= on:
        return at
    y, m = (on.year + 1, 1) if on.month == 12 else (on.year, on.month + 1)
    return pay_date(y, m, day)


COLUMNS = "id,kind,title,amount_cents,currency,day,account_id,credit,active,since,credited,created_at,updated_at"


def _row(r, on, accounts):
    acc = accounts.get(r[6])
    return {"id": r[0], "kind": r[1], "kind_label": KINDS.get(r[1], r[1]), "title": r[2] or KINDS.get(r[1], ""),
            "amount": r[3] / 100, "currency": r[4], "day": r[5], "account_id": r[6] if acc else None,
            "account": {"bank": acc["bank"], "title": acc["title"], "last4": acc["last4"], "kind": acc["kind"]} if acc else None,
            "credit": bool(r[7]), "active": bool(r[8]), "since": r[9], "credited": r[10],
            "next": next_pay(r[5], on).isoformat() if r[8] else None, "created_at": r[11], "updated_at": r[12]}


def _accounts(db, owner):
    return {a["id"]: a for a in banks.accounts(db, owner)}


def get(db, owner, item_id, on=None):
    row = db.execute(f"SELECT {COLUMNS} FROM income_items WHERE id=? AND owner_id=?", (item_id, str(owner))).fetchone()
    if row is None:
        raise LookupError("Зачисление не найдено")
    return _row(row, on or today(), _accounts(db, owner))


def save(db, owner, data, item_id=None):
    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-объект")
    allowed = {"kind", "title", "amount", "currency", "day", "account_id", "credit", "active"}
    if set(data) - allowed:
        raise ValueError("Неизвестное поле: " + ", ".join(sorted(set(data) - allowed)))
    old = get(db, owner, item_id) if item_id else None
    # название по умолчанию — название типа; своё сохраняем только если его задали,
    # иначе при смене типа к новому типу прилипало бы название старого
    own_title = "" if not old or old["title"] == KINDS.get(old["kind"]) else old["title"]
    merged = {**(old or {}), "title": own_title, **data}
    kind = merged.get("kind")
    if kind not in KINDS:
        raise ValueError("Выберите: аванс, зарплата или премия")
    taken = db.execute("SELECT id FROM income_items WHERE owner_id=? AND kind=?", (str(owner), kind)).fetchone()
    if taken and taken[0] != item_id:
        raise ValueError(f"{KINDS[kind]} уже добавлен — измените его")
    title = _text(merged.get("title"), 48, "Название")
    cents = _cents(data["amount"]) if "amount" in data else (round(old["amount"] * 100) if old else _cents(None))
    day = merged.get("day")
    if isinstance(day, str) and day.strip().isdigit():
        day = int(day)
    if type(day) is not int or not 1 <= day <= 31:
        raise ValueError("Число месяца: от 1 до 31")
    account_id = merged.get("account_id") or None
    currency = merged.get("currency")
    if account_id:
        acc = banks.account(db, owner, account_id)       # LookupError, если карта чужая или удалена
        currency = acc["currency"]
    if currency not in CURRENCIES:
        raise ValueError("Валюта: " + ", ".join(CURRENCIES))
    credit, active = merged.get("credit", True), merged.get("active", True)
    if type(credit) is not bool or type(active) is not bool:
        raise ValueError("Некорректная отметка")
    stamp, on = _now(), today()
    with db:
        if item_id:
            # сменили число, карту или включили зачисление — новые даты считаем с сегодняшнего дня,
            # чтобы не зачислить задним числом уже прошедшие выплаты
            restart = (day != old["day"] or account_id != old["account_id"] or (credit and not old["credit"])
                       or (active and not old["active"]))
            db.execute("UPDATE income_items SET kind=?,title=?,amount_cents=?,currency=?,day=?,account_id=?,credit=?,active=?,"
                       "since=CASE WHEN ? THEN ? ELSE since END,updated_at=? WHERE id=? AND owner_id=?",
                       (kind, title, cents, currency, day, account_id, int(credit), int(active),
                        int(restart), on.isoformat(), stamp, item_id, str(owner)))
        else:
            item_id = uuid.uuid4().hex
            db.execute(f"INSERT INTO income_items ({COLUMNS},owner_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (item_id, kind, title, cents, currency, day, account_id, int(credit), int(active),
                        on.isoformat(), None, stamp, stamp, str(owner)))
    credit_due(db, owner, on)
    return get(db, owner, item_id)


def delete(db, owner, item_id):
    with db:
        get(db, owner, item_id)
        db.execute("DELETE FROM income_items WHERE id=? AND owner_id=?", (item_id, str(owner)))


def credit_due(db, owner, on=None):
    """Зачисляет на карты выплаты, чей день уже наступил. Возвращает число зачислений."""
    on = on or today()
    rows = db.execute("SELECT id,kind,title,amount_cents,day,account_id,since,credited FROM income_items "
                      "WHERE owner_id=? AND active=1 AND credit=1 AND account_id IS NOT NULL", (str(owner),)).fetchall()
    done = 0
    for item_id, kind, title, cents, day, account_id, since, credited in rows:
        start = date.fromisoformat(since)
        if credited:
            start = max(start, date.fromisoformat(credited) + timedelta(days=1))
        due = pay_dates(day, start, on)
        if not due:
            continue
        with db:
            try:
                acc = banks.account(db, owner, account_id)
            except LookupError:
                db.execute("UPDATE income_items SET account_id=NULL WHERE id=?", (item_id,))
                continue
            balance = round(acc["balance"] * 100)
            for at in due:
                balance += cents
                stamp = datetime.combine(at, PAY_TIME, ZONE).astimezone(timezone.utc).isoformat(timespec="seconds")
                banks.credit(db, account_id, cents, balance, title or KINDS.get(kind, "Зарплата"), "salary", stamp)
                done += 1
            db.execute("UPDATE income_items SET credited=? WHERE id=?", (due[-1].isoformat(), item_id))
    if done:
        import live
        live.bump(db, owner, "banks", "income")     # зарплата пришла на карту — видно сразу
    return done


def overview(db, owner, on=None):
    """Зачисления и сводка: доход в месяц по валютам, этот месяц (получено/ждём), ближайшая выплата."""
    on = on or today()
    accounts = _accounts(db, owner)
    rows = db.execute(f"SELECT {COLUMNS} FROM income_items WHERE owner_id=? ORDER BY day", (str(owner),)).fetchall()
    items = [_row(r, on, accounts) for r in rows]
    monthly, received, expected, upcoming = {}, {}, {}, []
    for it in items:
        if not it["active"]:
            continue
        cents = round(it["amount"] * 100)
        monthly[it["currency"]] = monthly.get(it["currency"], 0) + cents
        paid = pay_date(on.year, on.month, it["day"])
        bucket = received if paid <= on else expected
        bucket[it["currency"]] = bucket.get(it["currency"], 0) + cents
        nxt = date.fromisoformat(it["next"])
        if (nxt - on).days <= UPCOMING_DAYS:
            upcoming.append({"id": it["id"], "kind": it["kind"], "title": it["title"], "amount": it["amount"],
                             "currency": it["currency"], "date": it["next"], "in_days": (nxt - on).days})
    upcoming.sort(key=lambda u: (u["date"], u["kind"]))
    money = lambda d: {cur: round(v / 100, 2) for cur, v in sorted(d.items())}
    return {"items": items, "monthly": money(monthly), "received": money(received), "expected": money(expected),
            "upcoming": upcoming, "kinds": KINDS, "currencies": list(CURRENCIES), "limit": len(KINDS)}
