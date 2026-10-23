"""Раздел «Активности»: шаги, вес, сон, вода, пульс и тренировки по дням.

Записи хранятся в серверной SQLite (STATE_DB) рядом с проектами и видны
только владельцу. Дневные показатели — одно значение на день (новое значение
заменяет прежнее), тренировок за день может быть сколько угодно.

Данные приходят сами: Mini App не может читать «Здоровье» iPhone или Health
Connect напрямую, поэтому у каждого пользователя есть личный ключ
синхронизации. Автоматизация на телефоне («Команды» на iPhone, приложение-
автоматизатор на Android) отправляет показатели на /api/activity/sync — без
Telegram и без участия человека. Такие записи помечены source="auto"; вручную
можно добавить или поправить всё то же самое.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import math
import re
import secrets
import uuid

# показатель: (название, единица, допустимый диапазон, шаг округления)
DAILY = {
    "steps": ("Шаги", "шагов", (0, 200_000), 1),
    "weight": ("Вес", "кг", (1, 500), 0.1),
    "sleep": ("Сон", "ч", (0, 24), 0.1),
    "water": ("Вода", "л", (0, 20), 0.1),
    "pulse": ("Пульс покоя", "уд/мин", (20, 250), 1),
    "hr_avg": ("Средний пульс", "уд/мин", (20, 250), 1),
    "hr_max": ("Максимальный пульс", "уд/мин", (20, 250), 1),
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
        CREATE TABLE IF NOT EXISTS activity_hc_steps (
            owner_id TEXT NOT NULL,
            origin TEXT NOT NULL,
            start_time TEXT NOT NULL,
            rid TEXT NOT NULL DEFAULT '',
            day TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY (owner_id, origin, start_time)
        );
        CREATE INDEX IF NOT EXISTS activity_hc_steps_day ON activity_hc_steps(owner_id, day);
        CREATE TABLE IF NOT EXISTS activity_sync (
            owner_id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            last_sync TEXT,
            last_saved TEXT
        );
    """)
    existing = {r[1] for r in db.execute("PRAGMA table_info(activity_entries)")}
    if "source" not in existing:
        db.execute("ALTER TABLE activity_entries ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
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


COLUMNS = "id,owner_id,day,kind,value,minutes,title,note,created_at,source"


def _row(r):
    kind = r[3]
    entry = {"id": r[0], "day": r[2], "kind": kind, "value": r[4], "minutes": r[5],
             "title": r[6], "note": r[7], "created_at": r[8], "source": r[9]}
    if kind in DAILY:
        entry["label"], entry["unit"] = DAILY[kind][0], DAILY[kind][1]
    else:
        entry["label"], entry["unit"] = "Тренировка", "мин"
    return entry


def add(db, owner, data, source="manual"):
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
            db.execute("INSERT INTO activity_entries (id,owner_id,day,kind,value,minutes,title,note,created_at,source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (entry_id, str(owner), day, kind, value, minutes, title, note, now, source))
        else:
            label, _, (low, high), step = DAILY[kind]
            value = _number(data.get("value"), low, high, label)
            value = round(value) if step == 1 else round(value, 1)
            old = db.execute("SELECT id FROM activity_entries WHERE owner_id=? AND day=? AND kind=?",
                             (str(owner), day, kind)).fetchone()
            entry_id = old[0] if old else uuid.uuid4().hex
            db.execute("DELETE FROM activity_entries WHERE owner_id=? AND day=? AND kind=?", (str(owner), day, kind))
            db.execute("INSERT INTO activity_entries (id,owner_id,day,kind,value,minutes,title,note,created_at,source) VALUES (?,?,?,?,?,NULL,'',?,?,?)",
                       (entry_id, str(owner), day, kind, value, note, now, source))
    return get_entry(db, owner, entry_id)


def replace(db, owner, entry_id, data):
    """Исправить запись: те же проверки, что у новой; показатель записи не меняется.

    Дневное значение, перенесённое на другой день, заменяет то, что там было.
    """
    old = get_entry(db, owner, entry_id)
    merged = {"day": old["day"], "note": old["note"],
              **({"minutes": old["minutes"], "title": old["title"], "value": old["value"]}
                 if old["kind"] == WORKOUT else {"value": old["value"]}),
              **data, "kind": old["kind"]}
    if set(data) - {"day", "note", "value", "minutes", "title"}:
        raise ValueError("Неизвестное поле записи")
    with db:
        db.execute("DELETE FROM activity_entries WHERE id=? AND owner_id=?", (entry_id, str(owner)))
        return add(db, owner, merged)


def get_entry(db, owner, entry_id):
    row = db.execute(f"SELECT {COLUMNS} FROM activity_entries WHERE id=? AND owner_id=?",
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
    rows = db.execute(f"SELECT {COLUMNS} FROM activity_entries WHERE owner_id=? AND day BETWEEN ? AND ? ORDER BY day DESC, created_at DESC",
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


# ── автосинхронизация с телефона ─────────────────────────────────────────

# Как поля называют разные автоматизации: «Команды» iOS, Tasker, MacroDroid…
SYNC_FIELDS = {
    "steps": ("steps", "step_count", "шаги"),
    "weight": ("weight", "body_mass", "вес"),
    "sleep": ("sleep", "sleep_hours", "сон"),
    "water": ("water", "вода"),
    "pulse": ("pulse", "resting_heart_rate", "heart_rate", "пульс"),
    "hr_avg": ("hr_avg", "heart_rate_avg"),
    "hr_max": ("hr_max", "heart_rate_max"),
}
NUMBER_RE = re.compile(r"-?\d[\d\s  ]*(?:[.,]\d+)?")
MAX_SYNC_DAYS = 31


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(db, owner):
    """Новый личный ключ синхронизации; прежний перестаёт работать. Сам ключ
    показывается один раз — в базе только его хэш."""
    token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db:
        db.execute("INSERT INTO activity_sync (owner_id,token_hash,created_at) VALUES (?,?,?) "
                   "ON CONFLICT(owner_id) DO UPDATE SET token_hash=excluded.token_hash, created_at=excluded.created_at",
                   (str(owner), _hash(token), now))
    return token


def revoke_token(db, owner):
    with db:
        db.execute("DELETE FROM activity_sync WHERE owner_id=?", (str(owner),))


def owner_for(db, token):
    if not isinstance(token, str) or not 16 <= len(token) <= 128:
        return None
    row = db.execute("SELECT owner_id FROM activity_sync WHERE token_hash=?", (_hash(token),)).fetchone()
    return row[0] if row else None


def sync_status(db, owner):
    row = db.execute("SELECT created_at,last_sync,last_saved FROM activity_sync WHERE owner_id=?", (str(owner),)).fetchone()
    if row is None:
        return {"connected": False, "last_sync": None, "last_saved": None}
    return {"connected": True, "created_at": row[0], "last_sync": row[1], "last_saved": row[2]}


def loose_number(value):
    """Число из того, что прислала автоматизация: 8123, "8 123", "72,4 кг", "7.5"."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        found = NUMBER_RE.search(value)
        if found:
            raw = re.sub(r"[\s  ]", "", found.group()).replace(",", ".")
            try:
                return float(raw)
            except ValueError:
                return None
    return None


def _sync_day(value):
    """День из «2026-10-21», «2026-10-21T22:00:00+03:00» или пусто — сегодня."""
    if value in (None, ""):
        return today().isoformat()
    return _day(str(value)[:10])


# ── HC Webhook (Android, Health Connect) ───────────────────────────────
# Приложение раз в 15+ минут присылает не итог дня, а отрезки шагов, появившиеся
# с прошлой отправки (или правки старых): {"steps": [{"count", "start_time",
# "end_time", "metadata": {"id", "data_origin"}}], "deleted": [{"type", "id"}]}.
# Поэтому отрезки храним и складываем по дням сами. Ключ отрезка — источник и
# начало: так повтор (правка) или пересобранный итог дня заменяют прежний.
# Шаги одного дня от двух источников (счётчик телефона и Google Fit) — это одни
# и те же шаги, поэтому за день берём больший из итогов источников, а не сумму.
HC_ZONE = timezone(timedelta(hours=3))


def _hc_day(value):
    """День отрезка: со смещением телефона — по нему, время в UTC — по UTC+3."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None or moment.utcoffset() == timedelta(0):
        moment = moment.replace(tzinfo=moment.tzinfo or timezone.utc).astimezone(HC_ZONE)
    return moment.date().isoformat()


def is_health_connect(payload):
    return isinstance(payload, dict) and (isinstance(payload.get("steps"), list)
                                          or ("app_version" in payload and "timestamp" in payload))


def ingest_health_connect(db, owner, payload):
    touched, skipped = set(), []
    owner = str(owner)
    with db:
        for gone in payload.get("deleted") or []:
            if isinstance(gone, dict) and gone.get("type") == "steps" and isinstance(gone.get("id"), str) and gone["id"]:
                for (day,) in db.execute("SELECT day FROM activity_hc_steps WHERE owner_id=? AND rid=?", (owner, gone["id"])).fetchall():
                    touched.add(day)
                db.execute("DELETE FROM activity_hc_steps WHERE owner_id=? AND rid=?", (owner, gone["id"]))
        for item in payload.get("steps") or []:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            count, start = loose_number(item.get("count")), item.get("start_time")
            day = _hc_day(start)
            if count is None or not 0 <= count <= 200_000 or day is None:
                skipped.append("steps")
                continue
            origin = str(meta.get("data_origin") or "")[:120]
            db.execute("INSERT INTO activity_hc_steps (owner_id,origin,start_time,rid,day,count) VALUES (?,?,?,?,?,?) "
                       "ON CONFLICT(owner_id,origin,start_time) DO UPDATE SET rid=excluded.rid, day=excluded.day, count=excluded.count",
                       (owner, origin, start, str(meta.get("id") or "")[:200], day, round(count)))
            touched.add(day)
    saved = {}
    for day in sorted(touched):
        rows = db.execute("SELECT origin, SUM(count) FROM activity_hc_steps WHERE owner_id=? AND day=? GROUP BY origin",
                          (owner, day)).fetchall()
        total = max((r[1] for r in rows), default=0)
        try:
            add(db, owner, {"kind": "steps", "day": day, "value": float(min(total, 200_000))}, source="auto")
            saved.setdefault(day, {})["steps"] = total
        except ValueError:          # день из будущего или старше 2000 года — не наш
            skipped.append(f"{day}:steps")
    return saved, skipped


def ingest(db, owner, payload):
    """Сохраняет присланные показатели за день (или за несколько дней в "days").

    Пустые и непонятные поля пропускаются, а не роняют всю отправку: если у
    человека нет весов, «Команды» пришлют пустой вес вместе с нормальными шагами.
    Сон больше 24 считается присланным в минутах.
    """
    if not isinstance(payload, dict):
        raise ValueError("Ожидается JSON-объект")
    if is_health_connect(payload):
        saved, skipped = ingest_health_connect(db, owner, payload)
        return _synced(db, owner, saved, skipped)
    days = payload.get("days")
    batches = days if isinstance(days, list) else [payload]
    if not batches or len(batches) > MAX_SYNC_DAYS:
        raise ValueError(f"За раз — от 1 до {MAX_SYNC_DAYS} дней")
    saved, skipped = {}, []
    for batch in batches:
        if not isinstance(batch, dict):
            raise ValueError("Каждый день — JSON-объект")
        day = _sync_day(batch.get("day", batch.get("date")))
        for kind, names in SYNC_FIELDS.items():
            raw = next((batch[n] for n in names if n in batch), None)
            if raw in (None, ""):
                continue
            value = loose_number(raw)
            if kind == "sleep" and value is not None and 24 < value <= 1440:
                value = value / 60
            try:
                if value is None:
                    raise ValueError
                add(db, owner, {"kind": kind, "day": day, "value": value}, source="auto")
                saved.setdefault(day, {})[kind] = value
            except ValueError:
                skipped.append(f"{day}:{kind}")
        for workout in batch.get("workouts") or []:
            if not isinstance(workout, dict):
                continue
            minutes = loose_number(workout.get("minutes", workout.get("duration")))
            title = str(workout.get("title") or workout.get("type") or "Тренировка")[:64]
            if minutes is None or not 1 <= round(minutes) <= 1440:
                skipped.append(f"{day}:workout")
                continue
            minutes = round(minutes)
            # та же тренировка придёт и при следующей синхронизации — второй раз не пишем
            if db.execute("SELECT 1 FROM activity_entries WHERE owner_id=? AND day=? AND kind=? AND source='auto' AND title=? AND minutes=?",
                          (str(owner), day, WORKOUT, title, minutes)).fetchone():
                continue
            calories = loose_number(workout.get("calories"))
            add(db, owner, {"kind": WORKOUT, "day": day, "minutes": minutes, "title": title,
                            "value": calories if calories is not None and 0 <= calories <= 20000 else None},
                source="auto")
            saved.setdefault(day, {}).setdefault("workouts", 0)
            saved[day]["workouts"] += 1
    return _synced(db, owner, saved, skipped)


def _synced(db, owner, saved, skipped):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db:
        db.execute("UPDATE activity_sync SET last_sync=?, last_saved=? WHERE owner_id=?",
                   (now, ", ".join(sorted({k for d in saved.values() for k in d})) or None, str(owner)))
    return {"ok": True, "saved": saved, "skipped": skipped}
