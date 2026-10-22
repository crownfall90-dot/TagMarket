"""Траты: подписки, регулярные списания и разовые покупки.

Регулярная трата задаётся датой ближайшего (или первого) списания и периодом —
неделя, месяц или год. Следующее списание Platformer считает сам, поэтому
запись не устаревает: Netflix от 15 марта «каждый месяц» в мае покажет
15 мая. В месяц у короткого месяца 31-е число становится последним днём.

Разовая покупка — сумма и дата. Суммы хранятся в целых копейках, итоги идут
по валютам: в одну валюту их сводит Mini App по курсу, как и всё остальное.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import calendar
import uuid

CURRENCIES = ("USD", "EUR", "RUB", "BYN")
CATEGORIES = {
    "subs": "Подписки", "connect": "Связь и интернет", "home": "Жильё и ЖКУ", "transport": "Транспорт",
    "food": "Еда", "shopping": "Покупки", "health": "Здоровье", "fun": "Развлечения",
    "learn": "Обучение", "other": "Другое",
}
PERIODS = {"week": "раз в неделю", "month": "раз в месяц", "year": "раз в год"}
KINDS = ("recurring", "once")
MAX_CENTS = 10**11
MAX_ITEMS = 300
UPCOMING_DAYS = 30


def setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS spend_items (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            title TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            currency TEXT NOT NULL,
            category TEXT NOT NULL,
            kind TEXT NOT NULL,
            period TEXT,
            day TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS spend_owner ON spend_items(owner_id, kind, day);
    """)
    db.commit()


def today():
    return datetime.now(timezone(timedelta(hours=3))).date()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cents(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("Укажите сумму")
    try:
        amount = Decimal(str(value).replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        raise ValueError("Некорректная сумма") from None
    if not amount.is_finite():
        raise ValueError("Некорректная сумма")
    cents = int((amount * 100).quantize(Decimal(1)))
    if not 0 < cents <= MAX_CENTS:
        raise ValueError("Сумма: больше нуля")
    return cents


def _date(value):
    if not isinstance(value, str):
        raise ValueError("Укажите дату")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Некорректная дата") from None
    if parsed.isoformat() != value or not date(2000, 1, 1) <= parsed <= today() + timedelta(days=3660):
        raise ValueError("Некорректная дата")
    return value


def _text(value, limit, label, required=False):
    value = "" if value is None else value
    if not isinstance(value, str) or "\x00" in value or len(value.strip()) > limit:
        raise ValueError(f"{label}: до {limit} символов")
    if required and not value.strip():
        raise ValueError(f"Укажите: {label.lower()}")
    return value.strip()


def add_months(day: date, months: int, anchor_day: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def charges(anchor: date, period: str, start: date, end: date):
    """Даты списаний регулярной траты в отрезке [start, end]."""
    out, n = [], 0
    while True:
        if period == "week":
            at = anchor + timedelta(days=7 * n)
        elif period == "month":
            at = add_months(anchor, n, anchor.day)
        else:
            at = add_months(anchor, 12 * n, anchor.day)
        if at > end:
            return out
        if at >= start:
            out.append(at)
        n += 1
        if n > 20000:           # якорь в 2000 году и неделя — всё равно конечно
            return out


def next_charge(anchor: date, period: str, on: date) -> date:
    if anchor >= on:
        return anchor
    if period == "week":
        return anchor + timedelta(days=-(-(on - anchor).days // 7) * 7)
    step = 12 if period == "year" else 1
    months = (on.year - anchor.year) * 12 + on.month - anchor.month
    months -= months % step
    at = add_months(anchor, months, anchor.day)
    return at if at >= on else add_months(anchor, months + step, anchor.day)


def monthly_cents(cents: int, period: str) -> float:
    return cents * 52 / 12 if period == "week" else cents / 12 if period == "year" else float(cents)


COLUMNS = "id,title,amount_cents,currency,category,kind,period,day,active,note,created_at,updated_at"


def _row(r, on=None):
    on = on or today()
    item = {"id": r[0], "title": r[1], "amount": r[2] / 100, "currency": r[3], "category": r[4],
            "category_label": CATEGORIES.get(r[4], "Другое"), "kind": r[5], "period": r[6], "day": r[7],
            "active": bool(r[8]), "note": r[9], "created_at": r[10], "updated_at": r[11]}
    if r[5] == "recurring":
        item["period_label"] = PERIODS.get(r[6], "")
        item["next"] = next_charge(date.fromisoformat(r[7]), r[6], on).isoformat() if r[8] else None
        item["monthly"] = round(monthly_cents(r[2], r[6]) / 100, 2)
    return item


def get(db, owner, item_id):
    row = db.execute(f"SELECT {COLUMNS} FROM spend_items WHERE id=? AND owner_id=?", (item_id, str(owner))).fetchone()
    if row is None:
        raise LookupError("Трата не найдена")
    return _row(row)


def save(db, owner, data, item_id=None):
    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-объект")
    old = get(db, owner, item_id) if item_id else None
    merged = {**(old or {}), **data}
    title = _text(merged.get("title"), 80, "Название", required=True)
    cents = _cents(data["amount"]) if "amount" in data else (round(old["amount"] * 100) if old else _cents(None))
    currency = merged.get("currency")
    if currency not in CURRENCIES:
        raise ValueError("Валюта: USD, EUR, RUB или BYN")
    category = merged.get("category") or "other"
    if category not in CATEGORIES:
        raise ValueError("Неизвестная категория")
    kind = merged.get("kind")
    if kind not in KINDS:
        raise ValueError("Выберите: регулярная трата или разовая покупка")
    period = merged.get("period") if kind == "recurring" else None
    if kind == "recurring" and period not in PERIODS:
        raise ValueError("Как часто списывается: неделя, месяц или год")
    day = _date(merged.get("day") or today().isoformat())
    active = merged.get("active", True)
    if type(active) is not bool:
        raise ValueError("Некорректная отметка «активна»")
    note = _text(merged.get("note"), 300, "Заметка")
    stamp = _now()
    with db:
        if item_id:
            db.execute("UPDATE spend_items SET title=?,amount_cents=?,currency=?,category=?,kind=?,period=?,day=?,active=?,note=?,updated_at=? "
                       "WHERE id=? AND owner_id=?",
                       (title, cents, currency, category, kind, period, day, int(active), note, stamp, item_id, str(owner)))
        else:
            if db.execute("SELECT COUNT(*) FROM spend_items WHERE owner_id=?", (str(owner),)).fetchone()[0] >= MAX_ITEMS:
                raise ValueError(f"Не больше {MAX_ITEMS} трат")
            item_id = uuid.uuid4().hex
            db.execute(f"INSERT INTO spend_items ({COLUMNS},owner_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (item_id, title, cents, currency, category, kind, period, day, int(active), note, stamp, stamp, str(owner)))
    return get(db, owner, item_id)


def delete(db, owner, item_id):
    with db:
        get(db, owner, item_id)
        db.execute("DELETE FROM spend_items WHERE id=? AND owner_id=?", (item_id, str(owner)))


def overview(db, owner, on=None):
    """Траты пользователя и сводка: в месяц по регулярным, этот месяц, ближайшие списания."""
    on = on or today()
    rows = db.execute(f"SELECT {COLUMNS} FROM spend_items WHERE owner_id=? ORDER BY kind, day DESC", (str(owner),)).fetchall()
    items = [_row(r, on) for r in rows]
    month_start = on.replace(day=1)
    month_end = month_start.replace(day=calendar.monthrange(on.year, on.month)[1])
    monthly, this_month, by_category, upcoming = {}, {}, {}, []

    def put(bucket, key, cur, cents):
        bucket.setdefault(key, {}).setdefault(cur, 0)
        bucket[key][cur] += cents

    for r in rows:
        cents, cur, category, kind, period, anchor, active = r[2], r[3], r[4], r[5], r[6], date.fromisoformat(r[7]), r[8]
        if kind == "once":
            if month_start <= anchor <= month_end:
                this_month[cur] = this_month.get(cur, 0) + cents
                put(by_category, category, cur, cents)
            continue
        if not active:
            continue
        monthly[cur] = monthly.get(cur, 0) + monthly_cents(cents, period)
        for _ in charges(anchor, period, month_start, month_end):
            this_month[cur] = this_month.get(cur, 0) + cents
            put(by_category, category, cur, cents)
        nxt = next_charge(anchor, period, on)
        if (nxt - on).days <= UPCOMING_DAYS:
            upcoming.append({"id": r[0], "title": r[1], "amount": cents / 100, "currency": cur,
                             "category": category, "date": nxt.isoformat(), "in_days": (nxt - on).days})
    upcoming.sort(key=lambda u: (u["date"], u["title"]))
    money = lambda d: {cur: round(v / 100, 2) for cur, v in sorted(d.items())}
    return {
        "items": items,
        "monthly": money(monthly),
        "this_month": money(this_month),
        "by_category": [{"category": key, "label": CATEGORIES[key], "totals": money(v)}
                        for key, v in sorted(by_category.items(), key=lambda kv: -sum(kv[1].values()))],
        "upcoming": upcoming[:12],
        "categories": CATEGORIES,
        "periods": PERIODS,
        "currencies": list(CURRENCIES),
        "month": month_start.isoformat()[:7],
    }
