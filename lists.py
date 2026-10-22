"""Раздел «Планы»: заметки, задачи и календарь событий.

Всё хранится в серверной SQLite (STATE_DB) и видно только владельцу.
Календарь принимает событие на любое число; повтор раз в неделю, месяц или
год (дни рождения, оплаты) разворачивается при запросе диапазона.
"""
from datetime import date, datetime, timedelta, timezone
import calendar
import math
import re
import uuid

MAX_AMOUNT = 1_000_000_000_000
CURRENCIES = {"USD", "RUB", "BYN", "EUR"}
REPEATS = {"none", "weekly", "monthly", "yearly"}
AREAS = {"work": "Работа", "personal": "Личное", "home": "Дом", "study": "Учёба"}
COLORS = {"accent", "green", "purple", "orange", "pink", "blue"}
MAX_RANGE_DAYS = 400
TIME_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


def setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            pinned INTEGER NOT NULL DEFAULT 0,
            color TEXT NOT NULL DEFAULT 'accent',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS notes_owner ON notes(owner_id, pinned, updated_at);
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            day TEXT NOT NULL,
            time TEXT,
            title TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            color TEXT NOT NULL DEFAULT 'accent',
            repeat TEXT NOT NULL DEFAULT 'none',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS events_owner_day ON events(owner_id, day);
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            title TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            due TEXT,
            area TEXT NOT NULL DEFAULT 'personal',
            done_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(owner_id, done_at, due);
    """)
    db.commit()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today():
    return datetime.now(timezone(timedelta(hours=3))).date()


def text(value, limit, label, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str) or "\x00" in value or len(value.strip()) > limit:
        raise ValueError(f"{label}: до {limit} символов")
    if required and not value.strip():
        raise ValueError(f"Укажите {label.lower()}")
    return value.strip()


def link(value):
    value = text(value, 500, "Ссылка")
    if value and not re.match(r"https?://[^\s]+$", value):
        raise ValueError("Ссылка должна начинаться с http:// или https://")
    return value


def price(value):
    if value is None or value == "":
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= MAX_AMOUNT:
        raise ValueError("Цена — неотрицательное число")
    return round(value * 100)


def day_value(value, label="Дата"):
    if not isinstance(value, str):
        raise ValueError(f"Укажите: {label.lower()}")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Некорректная {label.lower()}") from None
    if parsed.isoformat() != value or not date(1900, 1, 1) <= parsed <= date(2200, 12, 31):
        raise ValueError(f"{label}: с 1900 по 2200 год")
    return value


def choice(value, allowed, default, label):
    if value is None:
        return default
    if value not in allowed:
        raise ValueError(f"Некорректное значение: {label}")
    return value


def _patch(old, data, fields):
    unknown = set(data) - set(fields)
    if unknown:
        raise ValueError("Неизвестное поле: " + ", ".join(sorted(unknown)))
    return {**old, **data}


# ── заметки ─────────────────────────────────────────────────────────────

def _note(r):
    return {"id": r[0], "title": r[1], "body": r[2], "pinned": bool(r[3]), "color": r[4],
            "created_at": r[5], "updated_at": r[6]}


def note(db, owner, note_id):
    row = db.execute("SELECT id,title,body,pinned,color,created_at,updated_at FROM notes WHERE id=? AND owner_id=?",
                     (note_id, str(owner))).fetchone()
    if row is None:
        raise LookupError("Заметка не найдена")
    return _note(row)


def notes(db, owner):
    return [_note(r) for r in db.execute(
        "SELECT id,title,body,pinned,color,created_at,updated_at FROM notes WHERE owner_id=? ORDER BY pinned DESC, updated_at DESC",
        (str(owner),))]


def save_note(db, owner, data, note_id=None):
    with db:
        old = note(db, owner, note_id) if note_id else {"title": "", "body": "", "pinned": False, "color": "accent"}
        merged = _patch(old, data, ("title", "body", "pinned", "color"))
        title = text(merged.get("title"), 120, "Заголовок")
        body = text(merged.get("body"), 20000, "Текст")
        if not title and not body:
            raise ValueError("Заметка пустая")
        pinned = merged.get("pinned", False)
        if type(pinned) is not bool:
            raise ValueError("Некорректная отметка «закрепить»")
        color = choice(merged.get("color"), COLORS, "accent", "цвет")
        stamp = now()
        if note_id:
            db.execute("UPDATE notes SET title=?,body=?,pinned=?,color=?,updated_at=? WHERE id=? AND owner_id=?",
                       (title, body, int(pinned), color, stamp, note_id, str(owner)))
        else:
            note_id = uuid.uuid4().hex
            db.execute("INSERT INTO notes (id,owner_id,title,body,pinned,color,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                       (note_id, str(owner), title, body, int(pinned), color, stamp, stamp))
        return note(db, owner, note_id)


IMPORT_LIMIT = 500   # заметок за один импорт


def import_notes(db, owner, items):
    """Пачка заметок с телефона за один раз.

    Каждая — {"title", "body"}; пустые пропускаются, длинный заголовок
    обрезается, а заметка, которая уже есть (тот же заголовок и текст),
    второй раз не создаётся — повторный импорт того же файла безопасен.
    """
    if not isinstance(items, list) or not items:
        raise ValueError("Нет заметок для импорта")
    if len(items) > IMPORT_LIMIT:
        raise ValueError(f"За один раз — не больше {IMPORT_LIMIT} заметок")
    seen = {(r[0], r[1]) for r in db.execute("SELECT title,body FROM notes WHERE owner_id=?", (str(owner),))}
    imported = skipped = 0
    stamp = now()
    with db:
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Некорректная заметка")
            title = item.get("title") if isinstance(item.get("title"), str) else ""
            body = item.get("body") if isinstance(item.get("body"), str) else ""
            title, body = " ".join(title.split())[:120], body.strip()[:20000]
            if not title and not body:
                skipped += 1
                continue
            if (title, body) in seen:
                skipped += 1
                continue
            seen.add((title, body))
            db.execute("INSERT INTO notes (id,owner_id,title,body,pinned,color,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                       (uuid.uuid4().hex, str(owner), title, body, 0, "accent", stamp, stamp))
            imported += 1
    return {"imported": imported, "skipped": skipped, "notes": notes(db, owner)}


def delete_note(db, owner, note_id):
    with db:
        note(db, owner, note_id)
        db.execute("DELETE FROM notes WHERE id=? AND owner_id=?", (note_id, str(owner)))


# ── календарь ───────────────────────────────────────────────────────────

def _event(r):
    return {"id": r[0], "day": r[1], "time": r[2], "title": r[3], "note": r[4], "color": r[5],
            "repeat": r[6], "created_at": r[7]}


def event(db, owner, event_id):
    row = db.execute("SELECT id,day,time,title,note,color,repeat,created_at FROM events WHERE id=? AND owner_id=?",
                     (event_id, str(owner))).fetchone()
    if row is None:
        raise LookupError("Событие не найдено")
    return _event(row)


def save_event(db, owner, data, event_id=None):
    with db:
        old = event(db, owner, event_id) if event_id else {"time": None, "note": "", "color": "accent", "repeat": "none"}
        merged = _patch(old, data, ("day", "time", "title", "note", "color", "repeat"))
        day = day_value(merged.get("day"))
        moment = merged.get("time") or None
        if moment is not None and (not isinstance(moment, str) or not TIME_RE.fullmatch(moment)):
            raise ValueError("Время в формате ЧЧ:ММ")
        title = text(merged.get("title"), 120, "Название", required=True)
        body = text(merged.get("note"), 2000, "Заметка")
        color = choice(merged.get("color"), COLORS, "accent", "цвет")
        repeat = choice(merged.get("repeat"), REPEATS, "none", "повтор")
        if event_id:
            db.execute("UPDATE events SET day=?,time=?,title=?,note=?,color=?,repeat=? WHERE id=? AND owner_id=?",
                       (day, moment, title, body, color, repeat, event_id, str(owner)))
        else:
            event_id = uuid.uuid4().hex
            db.execute("INSERT INTO events (id,owner_id,day,time,title,note,color,repeat,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (event_id, str(owner), day, moment, title, body, color, repeat, now()))
        return event(db, owner, event_id)


def delete_event(db, owner, event_id):
    with db:
        event(db, owner, event_id)
        db.execute("DELETE FROM events WHERE id=? AND owner_id=?", (event_id, str(owner)))


def _shift(start, repeat, n):
    """n-е повторение события, начавшегося start; 31-е число в коротком месяце — последний день."""
    if repeat == "weekly":
        return start + timedelta(days=7 * n)
    months = n * (12 if repeat == "yearly" else 1)
    month = start.month - 1 + months
    year, month = start.year + month // 12, month % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def occurrences(item, since, until):
    """Даты события в [since, until] с учётом повтора."""
    start = date.fromisoformat(item["day"])
    if item["repeat"] == "none":
        return [start] if since <= start <= until else []
    if start > until:
        return []
    out = []
    if item["repeat"] == "weekly":
        n = max(0, (since - start).days // 7)
    elif item["repeat"] == "monthly":
        n = max(0, (since.year - start.year) * 12 + since.month - start.month - 1)
    else:
        n = max(0, since.year - start.year - 1)
    while True:
        when = _shift(start, item["repeat"], n)
        if when > until:
            return out
        if when >= since:
            out.append(when)
        n += 1


def events_between(db, owner, since, until):
    since, until = date.fromisoformat(day_value(since, "Начало")), date.fromisoformat(day_value(until, "Конец"))
    if until < since or (until - since).days > MAX_RANGE_DAYS:
        raise ValueError(f"Диапазон календаря: до {MAX_RANGE_DAYS} дней")
    rows = db.execute("SELECT id,day,time,title,note,color,repeat,created_at FROM events WHERE owner_id=? AND (day BETWEEN ? AND ? OR (repeat!='none' AND day<=?))",
                      (str(owner), since.isoformat(), until.isoformat(), until.isoformat())).fetchall()
    out = []
    for item in map(_event, rows):
        for when in occurrences(item, since, until):
            out.append({**item, "date": when.isoformat(), "original_day": item["day"]})
    out.sort(key=lambda e: (e["date"], e["time"] or "", e["title"]))
    return {"from": since.isoformat(), "to": until.isoformat(), "events": out}


def upcoming(db, owner, days=14, limit=5):
    """Ближайшие события для главной."""
    start = today()
    return events_between(db, owner, start.isoformat(), (start + timedelta(days=days)).isoformat())["events"][:limit]


# ── задачи ──────────────────────────────────────────────────────────────

def _task(r):
    return {"id": r[0], "title": r[1], "note": r[2], "due": r[3], "area": r[4],
            "done": r[5] is not None, "done_at": r[5], "created_at": r[6]}


def task(db, owner, task_id):
    row = db.execute("SELECT id,title,note,due,area,done_at,created_at FROM tasks WHERE id=? AND owner_id=?",
                     (task_id, str(owner))).fetchone()
    if row is None:
        raise LookupError("Задача не найдена")
    return _task(row)


def tasks(db, owner, done_days=14):
    """Открытые задачи (сначала со сроком, по сроку) и выполненные за последние done_days дней."""
    since = (datetime.now(timezone.utc) - timedelta(days=done_days)).isoformat(timespec="seconds")
    rows = db.execute("SELECT id,title,note,due,area,done_at,created_at FROM tasks WHERE owner_id=? AND (done_at IS NULL OR done_at>=?) "
                      "ORDER BY done_at IS NOT NULL, due IS NULL, due, created_at", (str(owner), since)).fetchall()
    return [_task(r) for r in rows]


def save_task(db, owner, data, task_id=None):
    with db:
        old = task(db, owner, task_id) if task_id else {"title": "", "note": "", "due": None, "area": "personal", "done": False}
        merged = _patch(old, data, ("title", "note", "due", "area", "done"))
        title = text(merged.get("title"), 200, "Задачу", required=True)
        body = text(merged.get("note"), 2000, "Заметка")
        due = day_value(merged["due"], "Срок") if merged.get("due") else None
        area = choice(merged.get("area"), set(AREAS), "personal", "сфера")
        done = merged.get("done", False)
        if type(done) is not bool:
            raise ValueError("Некорректная отметка «готово»")
        done_at = (old.get("done_at") or now()) if done else None
        if task_id:
            db.execute("UPDATE tasks SET title=?,note=?,due=?,area=?,done_at=? WHERE id=? AND owner_id=?",
                       (title, body, due, area, done_at, task_id, str(owner)))
        else:
            task_id = uuid.uuid4().hex
            db.execute("INSERT INTO tasks (id,owner_id,title,note,due,area,done_at,created_at) VALUES (?,?,?,?,?,?,?,?)",
                       (task_id, str(owner), title, body, due, area, done_at, now()))
        return task(db, owner, task_id)


def delete_task(db, owner, task_id):
    with db:
        task(db, owner, task_id)
        db.execute("DELETE FROM tasks WHERE id=? AND owner_id=?", (task_id, str(owner)))
