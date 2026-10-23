"""Баланс жизни: оценки сфер и живые наблюдения по данным пользователя.

Чистая функция над тем, что уже лежит в Platformer: проекты и TagMarket,
задачи, календарь и вишлисты. Никаких внешних сервисов —
считается мгновенно на каждом обновлении приложения. Оценка сферы 0–100 —
не приговор, а «насколько тут всё в порядке» по понятным правилам; если
данных о сфере нет, оценки нет (None) и круг показывает её пустой.
"""
from datetime import date, timedelta

SPHERES = (
    ("finance", "Финансы", "#projects"),
    ("tasks", "Дела", "#plans/tasks"),
    ("plans", "Планы", "#plans/calendar"),
    ("dreams", "Мечты", "#projects"),
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
    """data: finance, activity, tasks, events, goals, friends — см. miniapp.insights_data.

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
    salary = fin.get("salary") or 0
    if projects or tag or bank is not None or salary:
        score = 0
        daily = sum(p["daily_income"] or 0 for p in projects if not p.get("paused"))
        if salary > 0:
            score += 20
            out.append((38, "finance", "good", f"Зарплата: {money(salary, cur)} в месяц", "#income"))
        for u in fin.get("paydays") or []:
            when = "сегодня" if u["in_days"] == 0 else "завтра" if u["in_days"] == 1 else f"через {u['in_days']} {plural(u['in_days'], 'день', 'дня', 'дней')}"
            amount = money(u["converted"], cur, True) if u.get("converted") is not None else money(u["amount"], u["currency"], True)
            out.append((9 + u["in_days"], "finance", "good", f"{when.capitalize()} {u['title'].lower()} — {amount}", "#income"))
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
        for c in fin.get("charges") or []:
            when = "сегодня" if c["in_days"] == 0 else "завтра" if c["in_days"] == 1 else f"через {c['in_days']} {plural(c['in_days'], 'день', 'дня', 'дней')}"
            amount = money(c["converted"], cur, True) if c.get("converted") is not None else money(c["amount"], c["currency"], True)
            out.append((10 + c["in_days"], "finance", "info", f"{when.capitalize()} спишется «{c['title']}» — {amount}", "#spend"))
        if bank is not None:
            # банки и счета — главное в финансах: этот вывод идёт раньше проектов
            out.append((28, "finance", "info" if bank >= 0 else "warn", f"На банковских счетах: {money(bank, cur)}", "#banks"))
            if not projects and not tag:
                score = (60 if bank >= 0 else 25) + (20 if salary > 0 else 0)
        scores["finance"] = min(score, 100)
        daily += salary * 12 / 365
        income = f"≈ {money(daily, cur)} в день" if daily > 0 else ""
        fin_status = (" · ".join(x for x in (f"на счетах {money(bank, cur)}", income) if x) if bank is not None else
                      income or ("есть проекты на паузе" if paused else "без дохода в день"))
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

    # ── мечты: цели накоплений ──
    goals = data.get("goals") or []
    if goals:
        scores["dreams"] = sum(g["progress"] for g in goals) / len(goals) * 100
        pending = sorted((g for g in goals if not g["done"] and g.get("deadline")), key=lambda g: g["deadline"])
        if pending and pending[0].get("per_month"):
            g = pending[0]
            out.append((44, "dreams", "info", f"«{g['title']}»: откладывайте ≈ {money(g['per_month'], g['currency'])} в месяц, чтобы успеть к сроку", "#projects"))
        for g in goals:
            if g["done"]:
                out.append((46, "dreams", "good", f"Цель «{g['title']}» накоплена", "#projects"))
                break
    n_open = sum(not g["done"] for g in goals)
    dreams_status = (f"{n_open} {plural(n_open, 'цель', 'цели', 'целей')} копится" if n_open else "все цели накоплены") if goals else "добавьте цель накоплений"

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
