"""Круг жизни: оценки сфер и живые наблюдения по данным пользователя.

Чистая функция над тем, что уже лежит в Platformer: проекты и TagMarket,
задачи, календарь и вишлисты. Никаких внешних сервисов —
считается мгновенно на каждом обновлении приложения. Оценка сферы 0–100 —
не приговор, а «насколько тут всё в порядке» по понятным правилам; если
данных о сфере нет, оценки нет (None) и круг показывает её пустой.
"""
from datetime import date, timedelta
import math

SPHERES = (
    ("finance", "Финансы", "#projects"),
    ("tasks", "Дела", "#plans/tasks"),
    ("plans", "Планы", "#plans/calendar"),
    ("dreams", "Мечты", "#plans/wish"),
)
SIGNS = {"USD": "$", "RUB": "₽", "BYN": "Br", "EUR": "€"}


def money(value, cur="USD", cents=False):
    sign = SIGNS.get(cur, cur)
    text = f"{abs(value):,.{2 if cents else 0}f}".replace(",", " ").replace(".", ",")
    return f"{'−' if value < 0 else ''}{text} {sign}"


def num(value, digits=0):
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text


def plural(n, one, few, many):
    n = abs(int(n)) % 100
    if 10 < n < 20:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


def _clamp(value):
    return None if value is None else max(0, min(100, round(value)))



def analyze(data, today, hour=12):
    """data: finance, activity, tasks, events, wishlists, friends — см. miniapp.insights_data.

    Возвращает {"overall", "spheres": [...], "insights": [...]}; наблюдения
    отсортированы по важности, не больше восьми.
    """
    out = []                 # (приоритет, сфера, тон, текст, ссылка)
    scores = {}
    iso = today.isoformat()

    # ── финансы ──
    fin = data.get("finance") or {}
    cur = fin.get("currency") or "USD"
    projects = fin.get("projects") or []
    tag = fin.get("tag")
    bank = fin.get("banks")
    if projects or tag or bank is not None:
        score = 0
        daily = sum(p["daily_income"] or 0 for p in projects if not p.get("paused"))
        if projects:
            score += 35 if daily > 0 else 10
            if daily > 0:
                out.append((40, "finance", "good",
                            f"Проекты приносят ≈ {money(daily, cur)} в день — около {money(daily * 30, cur)} за месяц", "#projects"))
        if tag:
            month, today_net = tag.get("month") or 0, tag.get("today")
            score += 35 if month >= 0 else 10
            if today_net:
                out.append((30, "finance", "good" if today_net > 0 else "warn",
                            f"TagMarket сегодня {'+' if today_net > 0 else ''}{money(today_net, cur, True)}"
                            + (f" · за месяц {'+' if month > 0 else ''}{money(month, cur)}" if month else ""), "#tagmarket"))
            elif month < 0:
                out.append((35, "finance", "warn", f"TagMarket в этом месяце {money(month, cur)}", "#tagmarket"))
        else:
            score += 25
        paused = [p for p in projects if p.get("paused")]
        waiting = [p for p in projects if p.get("income_starts")]
        score += 30 if not paused else 15
        for p in paused[:2]:
            out.append((50, "finance", "info", f"«{p['name']}» на паузе — в доход и баланс не входит", "#projects"))
        for p in waiting[:2]:
            out.append((55, "finance", "info", f"Начисления по «{p['name']}» начнутся {_date(p['income_starts'])}", "#projects"))
        if bank is not None:
            out.append((44, "finance", "info", f"На банковских счетах: {money(bank, cur)}", "#banks"))
            if not projects and not tag:
                score = 60 if bank >= 0 else 25
        scores["finance"] = score
        fin_status = (f"≈ {money(daily, cur)} в день" if daily > 0 else
                      "есть проекты на паузе" if paused else
                      f"на счетах {money(bank, cur)}" if bank is not None else "без дохода в день")
    else:
        fin_status = "добавьте проект или счёт"
        daily = 0

    # ── дела ──
    tasks = data.get("tasks") or []
    open_tasks = [t for t in tasks if not t["done"]]
    overdue = [t for t in open_tasks if t.get("due") and t["due"] < iso]
    due_today = [t for t in open_tasks if t.get("due") == iso]
    week_ago = (today - timedelta(days=7)).isoformat()
    done_week = [t for t in tasks if t["done"] and (t.get("done_at") or "")[:10] >= week_ago]
    if tasks:
        scores["tasks"] = 100 * (len(done_week) + 1) / (len(done_week) + len(open_tasks) + 1) - 12 * len(overdue)
        if overdue:
            out.append((5, "tasks", "warn", f"Просрочено: {len(overdue)} {plural(len(overdue), 'задача', 'задачи', 'задач')} — «{overdue[0]['title']}»", "#plans/tasks"))
        if due_today:
            out.append((8, "tasks", "info", f"На сегодня: {', '.join('«' + t['title'] + '»' for t in due_today[:3])}", "#plans/tasks"))
        if done_week:
            out.append((48, "tasks", "good", f"За неделю закрыто {len(done_week)} {plural(len(done_week), 'задача', 'задачи', 'задач')}", "#plans/tasks"))
    tasks_status = (f"просрочено {len(overdue)}" if overdue else f"на сегодня {len(due_today)}" if due_today
                    else f"открыто {len(open_tasks)}" if open_tasks else "задач нет")

    # ── планы ──
    events = data.get("events") or []
    soon = [e for e in events if e["date"] <= (today + timedelta(days=7)).isoformat()]
    if events or open_tasks:
        scores["plans"] = 45 + min(len(soon), 4) * 10 + (15 if any(t.get("due") for t in open_tasks) else 0)
    for e in events:
        if e["date"] == iso:
            out.append((6, "plans", "info", f"Сегодня{(' в ' + e['time']) if e.get('time') else ''}: {e['title']}", "#plans/calendar"))
        elif e["date"] == (today + timedelta(days=1)).isoformat():
            gift = any(w in e["title"].lower() for w in ("др", "день рождения", "birthday"))
            out.append((10, "plans", "info", f"Завтра: {e['title']}" + (" — подарок уже выбран?" if gift else ""), "#plans/calendar"))
    plans_status = f"{len(soon)} {plural(len(soon), 'событие', 'события', 'событий')} на неделе" if soon else "неделя свободна"

    # ── мечты ──
    wishlists = data.get("wishlists") or []
    items = [i for w in wishlists for i in w["items"]]
    if wishlists:
        done = sum(i["done"] for i in items)
        scores["dreams"] = 40 + (60 * done / len(items) if items else 0)
        priced = sorted((i for i in items if not i["done"] and i.get("price") and (i.get("currency") or "USD") == cur), key=lambda i: i["price"])
        if priced and daily > 0:
            first = priced[0]
            days = math.ceil(first["price"] / daily)
            out.append((42, "dreams", "good", f"«{first['title']}» за {money(first['price'], cur)} — это ≈ {days} {plural(days, 'день', 'дня', 'дней')} дохода проектов", "#plans/wish"))
    dreams_status = (f"{sum(not i['done'] for i in items)} {plural(sum(not i['done'] for i in items), 'желание', 'желания', 'желаний')}"
                     if wishlists else "создайте первый вишлист")

    statuses = {"finance": fin_status, "tasks": tasks_status,
                "plans": plans_status, "dreams": dreams_status}
    spheres = [{"id": key, "label": label, "href": href, "score": _clamp(scores.get(key)), "status": statuses[key]}
               for key, label, href in SPHERES]
    known = [s["score"] for s in spheres if s["score"] is not None]
    out.sort(key=lambda x: x[0])
    return {"overall": round(sum(known) / len(known)) if known else None, "spheres": spheres,
            "insights": [{"sphere": s, "tone": t, "text": text, "href": h} for _, s, t, text, h in out[:8]]}


def _date(iso):
    months = ("янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек.")
    d = date.fromisoformat(iso)
    return f"{d.day} {months[d.month - 1]}"
