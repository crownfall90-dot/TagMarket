"""Сводка месяца: сколько пришло (зарплата), сколько ушло (траты), что осталось.

Доход проектов и результат TagMarket Mini App добавляет сама — они
считаются в валюте отображения из того, что у неё уже есть. Здесь — то, что
хранится по датам: выплаты зарплаты и списания трат, по валютам, за месяц и
за полгода назад для графика.
"""
from datetime import date, timedelta
import calendar

import income
import spend

HISTORY = 6


def month_bounds(month: str):
    try:
        y, m = (int(x) for x in month.split("-"))
        start = date(y, m, 1)
    except (ValueError, AttributeError):
        raise ValueError("Месяц: ГГГГ-ММ") from None
    if month != start.isoformat()[:7]:
        raise ValueError("Месяц: ГГГГ-ММ")
    return start, start.replace(day=calendar.monthrange(y, m)[1])


def _add(bucket, cur, cents):
    bucket[cur] = bucket.get(cur, 0) + cents


def _money(d):
    return {cur: round(v / 100, 2) for cur, v in sorted(d.items()) if v}


def _spent(rows, start, end, on):
    """(списано, ещё спишется до конца отрезка, по категориям) — копейки по валютам."""
    done, ahead, cats = {}, {}, {}
    for r in rows:
        cents, cur, category, kind, period, anchor, active = r
        anchor = date.fromisoformat(anchor)
        if kind == "once":
            if start <= anchor <= end:
                _add(done if anchor <= on else ahead, cur, cents)
                _add(cats.setdefault(category, {}), cur, cents)
            continue
        if not active:
            continue
        for at in spend.charges(anchor, period, start, end):
            _add(done if at <= on else ahead, cur, cents)
            _add(cats.setdefault(category, {}), cur, cents)
    return done, ahead, cats


def _paid(rows, start, end, on):
    """(пришло, ещё придёт) — выплаты зарплаты в отрезке, начиная со дня, когда её добавили."""
    got, ahead = {}, {}
    for cents, cur, day, created in rows:
        first = max(start, date.fromisoformat(created[:10]))
        for at in income.pay_dates(day, first, end):
            _add(got if at <= on else ahead, cur, cents)
    return got, ahead


def report(db, owner, month=None, on=None):
    on = on or spend.today()
    start, end = month_bounds(month or on.isoformat()[:7])
    spend_rows = db.execute("SELECT amount_cents,currency,category,kind,period,day,active FROM spend_items WHERE owner_id=?",
                            (str(owner),)).fetchall()
    pay_rows = db.execute("SELECT amount_cents,currency,day,created_at FROM income_items WHERE owner_id=? AND active=1",
                          (str(owner),)).fetchall()
    spent, spent_ahead, cats = _spent(spend_rows, start, end, on)
    got, got_ahead = _paid(pay_rows, start, end, on)
    history = []
    cursor = start
    for _ in range(HISTORY):
        m_start, m_end = month_bounds(cursor.isoformat()[:7])
        s, sa, _c = _spent(spend_rows, m_start, m_end, on)
        g, ga = _paid(pay_rows, m_start, m_end, on)
        for cur, v in sa.items():
            _add(s, cur, v)
        for cur, v in ga.items():
            _add(g, cur, v)
        history.append({"month": m_start.isoformat()[:7], "income": _money(g), "spend": _money(s),
                        "current": m_start <= on <= m_end})
        cursor = (m_start - timedelta(days=1)).replace(day=1)
    history.reverse()
    return {
        "month": start.isoformat()[:7],
        "days": (end - start).days + 1,
        "day": max(0, min((on - start).days + 1, (end - start).days + 1)),
        "income": _money(got), "income_ahead": _money(got_ahead),
        "spend": _money(spent), "spend_ahead": _money(spent_ahead),
        "by_category": [{"category": k, "label": spend.CATEGORIES.get(k, "Другое"), "totals": _money(v)}
                        for k, v in sorted(cats.items(), key=lambda kv: -sum(kv[1].values()))],
        "history": history,
    }
