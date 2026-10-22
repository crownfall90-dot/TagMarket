"""Живая синхронизация: у каждого пользователя есть номер версии его данных.

Любое изменение — из Mini App, из приложения для Android, с телефона (шаги,
SMS банка), от друга (общая трата), по расписанию (зарплата) или от бота и
агента MT5 (TagMarket) — поднимает номер в общей базе. Открытое приложение
держит запрос /api/live: сервер отвечает, как только номер вырос, и экран
обновляется сразу, без ожидания фонового круга. База общая для бота,
вебхуков и Mini App, поэтому изменения видны между процессами.

Номер — миллисекунды времени: растёт сам и одинаков по смыслу во всех
процессах; раздел (section) подсказывает, что именно изменилось.
"""
import time

SECTIONS = ("finance", "banks", "spend", "income", "goals", "plans", "activity", "friends",
            "tagmarket", "notifications", "settings", "data")


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS live_revisions (
        owner_id TEXT NOT NULL,
        section TEXT NOT NULL,
        rev INTEGER NOT NULL,
        PRIMARY KEY (owner_id, section))""")
    db.commit()


def bump(db, owners, *sections):
    """Отметить изменение у одного или нескольких владельцев. Ошибки синхронизации данные не ломают."""
    if isinstance(owners, (str, int)):
        owners = [owners]
    owners = {str(o) for o in owners if o is not None and str(o)}
    if not owners:
        return
    rev = int(time.time() * 1000)
    sections = [s for s in sections if s in SECTIONS] or ["data"]
    try:
        for owner in owners:
            for section in sections:
                db.execute("INSERT INTO live_revisions (owner_id,section,rev) VALUES (?,?,?) "
                           "ON CONFLICT(owner_id,section) DO UPDATE SET rev=MAX(rev+1, excluded.rev)",
                           (owner, section, rev))
        db.commit()
    except Exception:       # таблицы ещё нет (старая база) или она занята — обновится фоновым кругом
        try:
            db.rollback()
        except Exception:
            pass


def state(db, owner, since=0):
    """(последний номер, разделы, изменившиеся после since)."""
    rows = db.execute("SELECT section, rev FROM live_revisions WHERE owner_id=?", (str(owner),)).fetchall()
    latest = max((r[1] for r in rows), default=0)
    return latest, sorted(r[0] for r in rows if r[1] > since)


# разделы API → что изменилось; всё остальное — «data»
PATH_SECTIONS = (
    ("/api/banks", "banks"), ("/api/spend", "spend"), ("/api/income", "income"), ("/api/goals", "goals"),
    ("/api/projects", "finance"), ("/api/tasks", "plans"), ("/api/notes", "plans"), ("/api/events", "plans"),
    ("/api/lists", "plans"), ("/api/activity", "activity"), ("/api/friends", "friends"),
    ("/api/accounts", "tagmarket"), ("/api/notifications", "notifications"), ("/api/preferences", "settings"),
    ("/api/settings", "settings"),
)


def section_for(path):
    return next((section for prefix, section in PATH_SECTIONS if path.startswith(prefix)), "data")
