"""Раздел «Активности»: шаги, вес, сон, вода, пульс и тренировки по дням.

Записи хранятся в серверной SQLite (STATE_DB) рядом с проектами и видны
только владельцу. Дневные показатели — одно значение на день (новое значение
заменяет прежнее), тренировок за день может быть сколько угодно. Данные
вводятся вручную: так раздел одинаково работает на iPhone, Android и в
браузере, без доступа к Apple Health или Health Connect.
"""
from datetime import date, datetime, timedelta, timezone
import math
import uuid

# показатель: (название, единица, допустимый диапазон, шаг округления)
DAILY = {
    "steps": ("Шаги", "шагов", (0, 200_000), 1),
    "weight": ("Вес", "кг", (1, 500), 0.1),
    "sleep": ("Сон", "ч", (0, 24), 0.1),
    "water": ("Вода", "л", (0, 20), 0.1),
    "pulse": ("Пульс покоя", "уд/мин", (20, 250), 1),
}
WORKOUT = "workout"
KINDS = set(DAILY) | {WORKOUT}
DEFAULT_GOALS = {"steps": 10000, "sleep": 8, "water": 2}
MAX_DAYS = 366


def setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS activity_entries (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            day TEXT NOT NULL,
            kind TEXT NOT NULL,
            value REAL,
            minutes INTEGER,
            title TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS activity_owner_day ON activity_entries(owner_id, day);
        CREATE TABLE IF NOT EXISTS activity_goals (
            owner_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            target REAL NOT NULL,
            PRIMARY KEY (owner_id, kind)
        );
    """)
    db.commit()


def today():
    return datetime.now(timezone(timedelta(hours=3))).date()


def _day(value):
    if value is None or value == "":
        return today().isoformat()
    if not isinstance(value, str):
        raise ValueError("Укажите дату")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Некорректная дата") from None
    if parsed.isoformat() != value or not date(2000, 1, 1) <= parsed <= today():
        raise ValueError("Дата: с 2000 года до сегодняшнего дня")
    return value


def _number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label}: от {low:g} до {high:g}")
    return float(value)


def _text(value, limit, label):
    if value is None:
        return ""
    if not isinstance(value, str) or "\x00" in value or len(value.strip()) > limit:
        raise ValueError(f"{label}: до {limit} символов")
    return value.strip()


def _row(r):
    kind = r[3]
    entry = {"id": r[0], "day": r[2], "kind": kind, "value": r[4], "minutes": r[5],
             "title": r[6], "note": r[7], "created_at": r[8]}
    if kind in DAILY:
        entry["label"], entry["unit"] = DAILY[kind][0], DAILY[kind][1]
    else:
        entry["label"], entry["unit"] = "Тренировка", "мин"
    return entry


def add(db, owner, data):
    """Новая запись. Дневной показатель за тот же день заменяет прежний."""
    kind = data.get("kind")
    if kind not in KINDS:
        raise ValueError("Выберите показатель")
    day = _day(data.get("day"))
    note = _text(data.get("note"), 500, "Заметка")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db:
        if kind == WORKOUT:
            title = _text(data.get("title"), 64, "Тренировка") or "Тренировка"
            minutes = data.get("minutes")
            if type(minutes) is not int or not 1 <= minutes <= 1440:
                raise ValueError("Длительность тренировки: от 1 до 1440 минут")
            calories = data.get("value")
            value = None if calories in (None, "") else _number(calories, 0, 20000, "Калории")
            entry_id = uuid.uuid4().hex
            db.execute("INSERT INTO activity_entries (id,owner_id,day,kind,value,minutes,title,note,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (entry_id, str(owner), day, kind, value, minutes, title, note, now))
        else:
            label, _, (low, high), step = DAILY[kind]
            value = _number(data.get("value"), low, high, label)
            value = round(value) if step == 1 else round(value, 1)
            old = db.execute("SELECT id FROM activity_entries WHERE owner_id=? AND day=? AND kind=?",
                             (str(owner), day, kind)).fetchone()
            entry_id = old[0] if old else uuid.uuid4().hex
            db.execute("DELETE FROM activity_entries WHERE owner_id=? AND day=? AND kind=?", (str(owner), day, kind))
            db.execute("INSERT INTO activity_entries (id,owner_id,day,kind,value,minutes,title,note,created_at) VALUES (?,?,?,?,?,NULL,'',?,?)",
                       (entry_id, str(owner), day, kind, value, note, now))
    return get_entry(db, owner, entry_id)


def get_entry(db, owner, entry_id):
    row = db.execute("SELECT id,owner_id,day,kind,value,minutes,title,note,created_at FROM activity_entries WHERE id=? AND owner_id=?",
                     (entry_id, str(owner))).fetchone()
    if row is None:
        raise LookupError("Запись не найдена")
    return _row(row)


def delete(db, owner, entry_id):
    with db:
        get_entry(db, owner, entry_id)
        db.execute("DELETE FROM activity_entries WHERE id=? AND owner_id=?", (entry_id, str(owner)))


def goals(db, owner):
    saved = dict(db.execute("SELECT kind,target FROM activity_goals WHERE owner_id=?", (str(owner),)).fetchall())
    return {**DEFAULT_GOALS, **saved}


def set_goals(db, owner, data):
    if not isinstance(data, dict) or set(data) - set(DAILY):
        raise ValueError("Цели задаются для шагов, веса, сна, воды и пульса")
    with db:
        for kind, target in data.items():
            if target is None:
                db.execute("DELETE FROM activity_goals WHERE owner_id=? AND kind=?", (str(owner), kind))
                continue
            label, _, (low, high), _ = DAILY[kind]
            minimum = low or 0.1        # нулевая цель смысла не имеет
            db.execute("INSERT OR REPLACE INTO activity_goals (owner_id,kind,target) VALUES (?,?,?)",
                       (str(owner), kind, _number(target, minimum, high, f"Цель «{label}»")))
    return goals(db, owner)


def overview(db, owner, days=30):
    """Записи за последние days дней и сводка по каждому показателю."""
    if type(days) is not int or not 1 <= days <= MAX_DAYS:
        raise ValueError(f"Период: от 1 до {MAX_DAYS} дней")
    end = today()
    start = end - timedelta(days=days - 1)
    rows = db.execute("SELECT id,owner_id,day,kind,value,minutes,title,note,created_at FROM activity_entries WHERE owner_id=? AND day BETWEEN ? AND ? ORDER BY day DESC, created_at DESC",
                      (str(owner), start.isoformat(), end.isoformat())).fetchall()
    entries = [_row(r) for r in rows]
    week_from = (end - timedelta(days=6)).isoformat()
    summary = {}
    for kind, (label, unit, _, _) in DAILY.items():
        points = sorted(((e["day"], e["value"]) for e in entries if e["kind"] == kind))
        week = [v for d, v in points if d >= week_from]
        # последний известный вес — даже если он старше окна, иначе карточка пустеет
        last = points[-1] if points else db.execute(
            "SELECT day,value FROM activity_entries WHERE owner_id=? AND kind=? ORDER BY day DESC LIMIT 1",
            (str(owner), kind)).fetchone()
        summary[kind] = {
            "label": label, "unit": unit,
            "today": next((v for d, v in points if d == end.isoformat()), None),
            "last": last[1] if last else None, "last_day": last[0] if last else None,
            "week_avg": sum(week) / len(week) if week else None,
            "week_total": sum(week) if week else None,
            "series": [{"day": d, "value": v} for d, v in points],
        }
    workouts = [e for e in entries if e["kind"] == WORKOUT]
    week_workouts = [e for e in workouts if e["day"] >= week_from]
    summary[WORKOUT] = {
        "label": "Тренировки", "unit": "мин",
        "today": sum(e["minutes"] for e in workouts if e["day"] == end.isoformat()) or None,
        "week_count": len(week_workouts), "week_minutes": sum(e["minutes"] for e in week_workouts),
        "series": [{"day": d, "value": sum(e["minutes"] for e in workouts if e["day"] == d)}
                   for d in sorted({e["day"] for e in workouts})],
    }
    return {"from": start.isoformat(), "to": end.isoformat(), "days": days,
            "entries": entries, "summary": summary, "goals": goals(db, owner)}
