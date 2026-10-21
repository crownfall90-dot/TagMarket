"""Круг жизни: оценки сфер и живые наблюдения по данным пользователя.

Чистая функция над тем, что уже лежит в Станции: проекты и TagMarket,
активности, задачи, календарь, вишлисты, друзья. Никаких внешних сервисов —
считается мгновенно на каждом обновлении приложения. Оценка сферы 0–100 —
не приговор, а «насколько тут всё в порядке» по понятным правилам; если
данных о сфере нет, оценки нет (None) и круг показывает её пустой.
"""
from datetime import date, timedelta
import math

SPHERES = (
    ("finance", "Финансы", "#projects"),
    ("health", "Здоровье", "#activity"),
    ("tasks", "Дела", "#plans/tasks"),
    ("plans", "Планы", "#plans/calendar"),
    ("dreams", "Мечты", "#plans/wish"),
    ("people", "Люди", "#people"),
)
SIGNS = {"USD": "$", "RUB": "₽", "BYN": "Br", "EUR": "€"}
STEPS_PER_MINUTE = 100      # обычный шаг прогулки


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


def _streak(series, goal, today):
    by = {p["day"]: p["value"] for p in series}
    day = today
    if by.get(day.isoformat(), 0) < goal:
        day -= timedelta(days=1)
    n = 0
    while by.get(day.isoformat(), 0) >= goal:
        n += 1
        day -= timedelta(days=1)
    return n


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
    if projects or tag:
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
        scores["finance"] = score
        fin_status = (f"≈ {money(daily, cur)} в день" if daily > 0 else
                      "есть проекты на паузе" if paused else "без дохода в день")
    else:
        fin_status = "добавьте проект или счёт"
        daily = 0

    # ── здоровье ──
    act = data.get("activity") or {}
    summary, goals, sync = act.get("summary") or {}, act.get("goals") or {}, act.get("sync") or {}
    parts, weights = [], []
    steps = summary.get("steps") or {}
    steps_goal = goals.get("steps") or 10000
    if steps.get("series"):
        avg = steps.get("week_avg") or 0
        parts.append(min(avg / steps_goal, 1))
        weights.append(.4)
        now_steps = steps.get("today") or 0
        streak = _streak(steps["series"], steps_goal, today)
        if streak >= 3:
            out.append((15, "health", "good", f"🔥 {streak} {plural(streak, 'день', 'дня', 'дней')} подряд с выполненной целью по шагам", "#activity"))
        if now_steps < steps_goal and hour >= 12:
            left = steps_goal - now_steps
            out.append((20, "health", "info",
                        f"До цели {num(left)} шагов — это ≈ {math.ceil(left / STEPS_PER_MINUTE)} мин прогулки", "#activity"))
        elif now_steps >= steps_goal:
            out.append((25, "health", "good", f"Цель по шагам на сегодня выполнена: {num(now_steps)}", "#activity"))
    sleep = summary.get("sleep") or {}
    sleep_goal = goals.get("sleep") or 8
    if sleep.get("week_avg") is not None:
        parts.append(min(sleep["week_avg"] / sleep_goal, 1))
        weights.append(.3)
        if sleep["week_avg"] < sleep_goal - .4:
            short = round((sleep_goal - sleep["week_avg"]) * 60)
            out.append((18, "health", "warn",
                        f"Сон в среднем {num(sleep['week_avg'], 1)} ч при цели {num(sleep_goal, 0 if sleep_goal == int(sleep_goal) else 1)} — ложитесь на {short} мин раньше", "#activity"))
    workout = summary.get("workout") or {}
    if workout.get("series") is not None and (workout.get("series") or steps.get("series")):
        parts.append(min((workout.get("week_count") or 0) / 3, 1))
        weights.append(.3)
        last = max((p["day"] for p in workout.get("series") or []), default=None)
        gap = (today - date.fromisoformat(last)).days if last else None
        if gap is not None and gap >= 5:
            out.append((22, "health", "warn", f"Тренировок не было {gap} {plural(gap, 'день', 'дня', 'дней')}", "#activity"))
    weight = summary.get("weight") or {}
    series = weight.get("series") or []
    if len(series) >= 2 and (date.fromisoformat(series[-1]["day"]) - date.fromisoformat(series[0]["day"])).days >= 7:
        diff = series[-1]["value"] - series[0]["value"]
        if abs(diff) >= .3:
            out.append((45, "health", "info", f"Вес {'+' if diff > 0 else '−'}{num(abs(diff), 1)} кг за месяц", "#activity"))
    if parts:
        scores["health"] = sum(p * w for p, w in zip(parts, weights)) / sum(weights) * 100
    if not sync.get("connected"):
        out.append((60, "health", "info", "Подключите автосинхронизацию — шаги, вес и сон будут приходить с телефона сами", "#activity"))
    elif sync.get("last_sync") is None or sync.get("stale"):
        out.append((12, "health", "warn", "Данные с телефона давно не приходили — проверьте автоматизацию", "#activity"))

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

    # ── люди ──
    friends = data.get("friends") or 0
    scores["people"] = min(100, 30 + 20 * friends)
    birthdays = [e for e in events if any(w in e["title"].lower() for w in ("др", "день рождения", "birthday"))]
    if friends == 0:
        out.append((70, "people", "info", "Пригласите друзей — у каждого будет своя Станция", "#people"))
    people_status = (f"{friends} {plural(friends, 'друг', 'друга', 'друзей')}" if friends else "пока один") + (
        f" · дней рождения: {len(birthdays)}" if birthdays else "")

    statuses = {"finance": fin_status, "health": _health_status(summary, goals), "tasks": tasks_status,
                "plans": plans_status, "dreams": dreams_status, "people": people_status}
    spheres = [{"id": key, "label": label, "href": href, "score": _clamp(scores.get(key)), "status": statuses[key]}
               for key, label, href in SPHERES]
    known = [s["score"] for s in spheres if s["score"] is not None]
    out.sort(key=lambda x: x[0])
    return {"overall": round(sum(known) / len(known)) if known else None, "spheres": spheres,
            "insights": [{"sphere": s, "tone": t, "text": text, "href": h} for _, s, t, text, h in out[:8]]}


def _health_status(summary, goals):
    steps = (summary.get("steps") or {}).get("today")
    if steps is not None:
        return f"{num(steps)} шагов сегодня"
    if (summary.get("weight") or {}).get("last") is not None:
        return f"вес {num(summary['weight']['last'], 1)} кг"
    return "нет данных"


def _date(iso):
    months = ("янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек.")
    d = date.fromisoformat(iso)
    return f"{d.day} {months[d.month - 1]}"
