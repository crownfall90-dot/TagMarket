"""Цели накоплений: на что копим, сколько нужно, сколько уже отложено и к какому сроку.

Отложенное копится взносами («отложил 100») — их можно и забрать обратно
минусом. По сроку Platformer считает, сколько откладывать в месяц, а
сводка месяца сравнивает это с тем, что остаётся после трат.
"""
from datetime import date, datetime, timezone
import uuid

from spend import CURRENCIES, _cents, _text, today

MAX_GOALS = 30
MAX_CENTS = 10**11


def setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            title TEXT NOT NULL,
            emoji TEXT NOT NULL DEFAULT '',
            target_cents INTEGER NOT NULL,
            saved_cents INTEGER NOT NULL DEFAULT 0,
            currency TEXT NOT NULL,
            deadline TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS goals_owner ON goals(owner_id, created_at);
    """)
    db.commit()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def months_left(deadline: date, on: date) -> int:
    """Сколько ещё взносов «раз в месяц» до срока, включая текущий месяц; минимум 1."""
    return max(1, (deadline.year - on.year) * 12 + deadline.month - on.month + (deadline.day >= on.day))


COLUMNS = "id,title,emoji,target_cents,saved_cents,currency,deadline,created_at,updated_at"


def _row(r, on):
    target, saved = r[3], r[4]
    left = max(0, target - saved)
    item = {"id": r[0], "title": r[1], "emoji": r[2], "target": target / 100, "saved": saved / 100,
            "left": left / 100, "currency": r[5], "deadline": r[6], "created_at": r[7], "updated_at": r[8],
            "progress": round(min(1.0, saved / target), 4) if target else 0, "done": saved >= target,
            "per_month": None, "months_left": None, "late": False}
    if r[6] and left:
        deadline = date.fromisoformat(r[6])
        n = months_left(deadline, on)
        item.update(months_left=n, per_month=round(left / n / 100, 2), late=deadline < on)
    return item


def get(db, owner, goal_id, on=None):
    row = db.execute(f"SELECT {COLUMNS} FROM goals WHERE id=? AND owner_id=?", (goal_id, str(owner))).fetchone()
    if row is None:
        raise LookupError("Цель не найдена")
    return _row(row, on or today())


def _deadline(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("Некорректный срок")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Некорректный срок") from None
    if parsed.isoformat() != value or not date(2000, 1, 1) <= parsed <= date(2100, 12, 31):
        raise ValueError("Некорректный срок")
    return value


def save(db, owner, data, goal_id=None):
    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-объект")
    allowed = {"title", "emoji", "target", "saved", "currency", "deadline"}
    if set(data) - allowed:
        raise ValueError("Неизвестное поле: " + ", ".join(sorted(set(data) - allowed)))
    old = get(db, owner, goal_id) if goal_id else None
    merged = {**(old or {}), **data}
    title = _text(merged.get("title"), 64, "Название", required=True)
    emoji = _text(merged.get("emoji"), 8, "Значок")
    target = _cents(data["target"]) if "target" in data else (round(old["target"] * 100) if old else _cents(None))
    saved = 0
    if "saved" in data and data["saved"] not in (None, "", 0, "0"):
        saved = _cents(data["saved"])
    elif old and "saved" not in data:
        saved = round(old["saved"] * 100)
    currency = merged.get("currency")
    if currency not in CURRENCIES:
        raise ValueError("Валюта: " + ", ".join(CURRENCIES))
    if old and currency != old["currency"] and old["saved"]:
        raise ValueError("Валюту цели с накоплениями менять нельзя")
    deadline = _deadline(merged.get("deadline"))
    stamp = _now()
    with db:
        if goal_id:
            db.execute("UPDATE goals SET title=?,emoji=?,target_cents=?,saved_cents=?,currency=?,deadline=?,updated_at=? "
                       "WHERE id=? AND owner_id=?", (title, emoji, target, saved, currency, deadline, stamp, goal_id, str(owner)))
        else:
            if db.execute("SELECT COUNT(*) FROM goals WHERE owner_id=?", (str(owner),)).fetchone()[0] >= MAX_GOALS:
                raise ValueError(f"Не больше {MAX_GOALS} целей")
            goal_id = uuid.uuid4().hex
            db.execute(f"INSERT INTO goals ({COLUMNS},owner_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (goal_id, title, emoji, target, saved, currency, deadline, stamp, stamp, str(owner)))
    return get(db, owner, goal_id)


def contribute(db, owner, goal_id, amount):
    """Отложить (amount > 0) или забрать (amount < 0); отложенное не уходит в минус."""
    if isinstance(amount, bool) or not isinstance(amount, (int, float, str)):
        raise ValueError("Укажите сумму")
    raw = str(amount).strip()
    sign = -1 if raw.startswith("-") else 1
    cents = sign * _cents(raw.lstrip("-+"))
    with db:
        goal = get(db, owner, goal_id)
        saved = round(goal["saved"] * 100) + cents
        if saved < 0:
            raise ValueError("Забрать можно не больше отложенного")
        if saved > MAX_CENTS:
            raise ValueError("Слишком большая сумма")
        db.execute("UPDATE goals SET saved_cents=?,updated_at=? WHERE id=? AND owner_id=?", (saved, _now(), goal_id, str(owner)))
    return get(db, owner, goal_id)


def delete(db, owner, goal_id):
    with db:
        get(db, owner, goal_id)
        db.execute("DELETE FROM goals WHERE id=? AND owner_id=?", (goal_id, str(owner)))


def overview(db, owner, on=None):
    on = on or today()
    items = [_row(r, on) for r in db.execute(f"SELECT {COLUMNS} FROM goals WHERE owner_id=? ORDER BY created_at", (str(owner),))]
    items.sort(key=lambda g: (g["done"], g["deadline"] or "9999", g["created_at"]))
    per_month, saved = {}, {}
    for g in items:
        saved[g["currency"]] = round(saved.get(g["currency"], 0) + g["saved"], 2)
        if g["per_month"]:
            per_month[g["currency"]] = round(per_month.get(g["currency"], 0) + g["per_month"], 2)
    return {"items": items, "per_month": per_month, "saved": saved, "currencies": list(CURRENCIES)}
