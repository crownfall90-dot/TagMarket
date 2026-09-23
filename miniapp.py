"""Telegram Mini App API. Shares accounts, reports and preferences with the bot.

Handlers do not yield while using the legacy trades calculation context.
Only signed Telegram initData is accepted; no browser/demo authentication bypass.
"""
import hashlib
import hmac
import html
from html.parser import HTMLParser
import json
import math
import os
import time
import calendar
import logging
import sqlite3
import tempfile
import uuid
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl
from account_lock import locked

from aiohttp import web
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile

os.environ["TRADES_SOURCE"] = "store"
import accounts
import bot as logic
import coordination
import partner
import store
import trades

STATIC = Path(__file__).parent / "web"
MAX_AUTH_AGE = 86400
_rates = OrderedDict()
_broadcast_active = set()


def plain_report(markup):
    """Turn Telegram formatting into text without parsing HTML in the WebView."""
    class Text(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)

    parser = Text()
    parser.feed(markup)
    return "".join(parser.parts)


def telegram_length(value):
    """Telegram caption/message limits count UTF-16 code units, not Python characters."""
    return len(value.encode("utf-16-le")) // 2


class _BroadcastHTML(HTMLParser):
    """Keep only Telegram HTML formatting supported by the broadcast editor."""
    ALLOWED = {"b", "strong", "i", "em", "u", "s", "code", "pre", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        tag = {"strong": "b", "em": "i"}.get(tag, tag)
        if tag not in self.ALLOWED:
            return
        self.parts.append(f"<{tag}>")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        tag = {"strong": "b", "em": "i"}.get(tag, tag)
        if tag in self.stack:
            while self.stack:
                opened = self.stack.pop()
                self.parts.append(f"</{opened}>")
                if opened == tag:
                    break

    def handle_data(self, data):
        self.parts.append(html.escape(data))

    def finish(self):
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")


def sanitize_broadcast_html(value, limit=4096):
    value = str(value or "")
    if len(value) > limit:
        raise ValueError("text")
    parser = _BroadcastHTML()
    parser.feed(value)
    parser.close()
    parser.finish()
    result = "".join(parser.parts).strip()
    if len(result) > limit:
        raise ValueError("text")
    return result


def validate_init_data(raw, token, now=None):
    now = time.time() if now is None else now
    if not token or not raw or len(raw) > 16384:
        raise ValueError("Откройте приложение через Telegram")
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError("Повторяющиеся поля авторизации")
    supplied = data.pop("hash", "")
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise ValueError("Подпись Telegram недействительна")
    age = now - int(data.get("auth_date", "0"))
    if age < -30 or age > MAX_AUTH_AGE:
        raise ValueError("Сессия истекла. Откройте приложение заново")
    user = json.loads(data.get("user", "{}"))
    if type(user.get("id")) is not int or user["id"] <= 0:
        raise ValueError("Не удалось определить пользователя")
    return user


def authorize(request):
    try:
        user = validate_init_data(request.headers.get("X-Telegram-Init-Data", ""),
                                  os.getenv("TELEGRAM_BOT_TOKEN", ""))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise web.HTTPUnauthorized(text="Откройте приложение заново через Telegram")
    uid, db = str(user["id"]), request.app["db"]
    allowed = {x.strip() for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()}
    if (partner.kv_get(db, f"left:{uid}") == "1" or
            (allowed and uid not in allowed and partner.kv_get(db, f"guest:{uid}") != "1")):
        raise web.HTTPForbidden(text="Доступ закрыт. Запросите приглашение в боте")
    now = time.monotonic()
    start, count = _rates.pop(uid, (now, 0))
    if now - start >= 60:
        start, count = now, 0
    _rates[uid] = (start, count + 1)
    while len(_rates) > 4096:
        _rates.popitem(last=False)
    if count >= 120:
        raise web.HTTPTooManyRequests(text="Слишком много запросов. Подождите минуту")
    return uid, user


@web.middleware
async def api_errors(request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        if "/api/" not in request.path:
            raise
        response = web.json_response({"error": exc.text}, status=exc.status)
    except (ValueError, TypeError, KeyError):
        if "/api/" not in request.path:
            raise
        response = web.json_response({"error": "Некорректные данные запроса"}, status=400)
    except (sqlite3.OperationalError, sqlite3.IntegrityError) as exc:
        if "/api/" not in request.path:
            raise
        logging.getLogger("miniapp").warning("Temporary database failure on %s: %s", request.path, exc)
        response = web.json_response({"error": "Данные временно заняты. Повторите запрос через несколько секунд"}, status=503)
    except Exception:
        if "/api/" not in request.path:
            raise
        logging.getLogger("miniapp").exception("API request failed: %s", request.path)
        response = web.json_response({"error": "Не удалось выполнить запрос. Повторите позже"}, status=500)
    if "/api/" in request.path:
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    return response


async def json_object(request) -> dict:
    """Тело запроса — JSON-объект, иначе 400.

    Массив или строка вместо объекта раньше доходили до data.get(...) и
    падали AttributeError — 500 с трассировкой вместо понятного 400.
    Битый JSON — ValueError, его middleware api_errors тоже превращает в 400.
    """
    data = await request.json()
    if not isinstance(data, dict):
        raise ValueError("object required")
    return data


def mt5_login(value) -> int:
    """Номер счёта MT5 из тела запроса: целое число или строка из цифр.

    int() молча принимал true (счёт 1) и 123.9 (счёт 123): опечаткой типа
    можно было занять чужой номер, и настоящий владелец потом получал
    «Счёт уже подключён».
    """
    if type(value) is int:
        login = value
    elif type(value) is str and value.isascii() and value.isdigit():
        login = int(value)
    else:
        raise ValueError("login")
    if not 0 < login < 2**63:
        raise ValueError("login")
    return login


def owned(uid, login):
    acc = next((a for a in accounts.load(uid) if int(a["login"]) == int(login)), None)
    if not acc:
        # The public copy-trading account is read-only shared data. It is
        # visible to every cabinet without creating a personal account row.
        acc = next((a for a in accounts.load() if a.get("demo") and int(a["login"]) == int(login)), None)
    if not acc:
        raise web.HTTPNotFound(text="Счёт не найден")
    return acc


def public_account(acc, db):
    result = {k: acc.get(k) for k in ("login", "name", "strategy", "cabinet", "holder",
              "server", "enabled", "notify", "demo", "base", "base_at")}
    # У копий общего демо-счёта номер в accounts.json лежит строкой, у остальных —
    # числом. Интерфейс сравнивает его строго, и «Настроить» на такой записи
    # молча ничего не делало
    result["login"] = int(acc["login"])
    result["shared"] = bool(acc.get("shared_by"))
    state = store.get_state(db, acc["login"])
    result["synced"] = (state or {}).get("synced")
    result["status"] = "pending"
    result["totals"] = None
    if state:
        age = (logic.utcnow() - datetime.fromisoformat(state["synced"])).total_seconds()
        result["status"] = "fresh" if age < logic.TERMINAL_STALE else "stale"
        result["totals"] = logic.account_totals(acc)
    return result


async def bootstrap(request):
    uid, user = authorize(request)
    db = request.app["db"]
    items = [public_account(a, request.app["trades"]) for a in accounts.dedup(accounts.load(uid))]
    # Show the single public copy-trading account without cloning it into
    # every invited user's personal cabinet.
    if logic.DEMO_ON and not any(a.get("demo") for a in items):
        source = next((a for a in accounts.load() if a.get("demo") and int(a.get("login", 0)) == int(logic.DEMO_LOGIN)), None)
        if source:
            demo_view = public_account(source, request.app["trades"])
            demo_view["enabled"] = logic.kv_get(db, f"public_demo:{uid}:enabled") != "0"
            saved_notify = logic.kv_get(db, f"public_demo:{uid}:notify")
            if saved_notify:
                try: demo_view["notify"] = {**(demo_view.get("notify") or {}), **json.loads(saved_notify)}
                except (TypeError, ValueError, json.JSONDecodeError): pass
            items.append(demo_view)
    # Never combine currencies or include demonstration capital in personal totals.
    totals = {}
    for a in items:
        t = a["totals"]
        if a["demo"] or a.get("shared") or not t:
            continue
        bucket = totals.setdefault(t["cur"], {"capital": 0, "pnl": 0, "month": 0, "today": 0, "kept": 0})
        for key, source in (("capital", "now"), ("pnl", "pnl"), ("month", "month_net"),
                            ("today", "today_net"), ("kept", "kept")):
            bucket[key] += t[source]
    own_accounts = [a for a in items if not a["demo"] and not a.get("shared")]
    inviter = partner.kv_get(db, f"guest_by:{uid}")
    registration_url = (logic.partner_link(db, inviter) if inviter else logic.partner_registration_url())
    return web.json_response({"user": {"id": user["id"], "name": user.get("first_name", "Инвестор")},
        "accounts": items, "totals": totals,
        "onboarding": {"needed": not own_accounts,
                        "registration_url": registration_url,
                        "progress": logic.onboarding_status(db, uid),
                        "partner_url": logic.partner_link(request.app["db"], uid)},
        "founder": logic.is_founder(uid), "update_alerts": logic.update_alerts_on(db),
        "server_time": logic.utcnow().isoformat() + "Z",
        # интервал фонового обновления Mini App; клиент ждёт не меньше 30 с
        "refresh_seconds": 60})


async def notifications(request):
    uid, _ = authorize(request)
    db = request.app["db"]
    if request.method == "POST":
        data = await request.json()
        if not isinstance(data, dict) or data.get("action") != "read":
            raise ValueError("action")
        ids = data.get("ids")
        if ids is not None and (not isinstance(ids, list) or len(ids) > 50 or
                                any(type(x) is not int or x <= 0 for x in ids)):
            raise ValueError("ids")
        partner.read_notifications(db, uid, ids)
    return web.json_response(partner.notifications_for(db, uid))


async def onboarding_progress(request):
    uid, _ = authorize(request)
    data = await json_object(request)
    steps = ("registered", "verified", "broker_account")
    step = data.get("step")
    if step not in steps or type(data.get("done")) is not bool:
        raise web.HTTPBadRequest(text="Некорректный шаг")
    db = request.app["db"]
    progress = logic.onboarding_status(db, uid)
    index = steps.index(step)
    if data["done"] and index and not progress[steps[index - 1]]:
        raise web.HTTPConflict(text="Сначала завершите предыдущий шаг")
    if not data["done"]:
        for later in steps[index:]:
            partner.kv_set(db, f"onboard:{uid}:{later}", "0")
    else:
        partner.kv_set(db, f"onboard:{uid}:{step}", "1")
    return web.json_response({"progress": logic.onboarding_status(db, uid)})


def report_period(query):
    period = query.get("period", "month")
    if period == "custom":
        since = datetime.combine(date.fromisoformat(query["from"]), datetime.min.time())
        until = datetime.combine(date.fromisoformat(query["to"]), datetime.max.time())
        if since > until:
            raise ValueError("invalid period")
        return "Выбранный период", since, until
    if period not in ("today", "yesterday", "week", "lastweek", "month", "lastmonth", "all"):
        raise ValueError("invalid period")
    title, since, until, _ = logic.period(period)
    return title, since, until


def report_archive(since, until):
    archived = trades.archive(since, until)
    kept = []
    for month in archived:
        start = datetime.fromisoformat(month["month"] + "-01")
        end = start.replace(day=calendar.monthrange(start.year, start.month)[1],
                            hour=23, minute=59, second=59, microsecond=999999)
        # период (например, "эта неделя") может начинаться внутри уже свёрнутого
        # месяца — сам месяц в выборку не попадает целиком, отбрасываем его тут,
        # а не роняем весь отчёт: клетки внутри свёрнутого месяца просто не в него
        if start >= since and end <= until:
            kept.append(month)
    return kept


async def overview_report(request):
    uid, _ = authorize(request)
    title, since, until = report_period(request.query)
    currency = request.query.get("currency", "USD").upper()
    if not 3 <= len(currency) <= 5 or not currency.isalpha():
        raise ValueError("currency")
    db = request.app["trades"]
    chart = {}
    total = count = account_count = archived_count = pending_count = 0
    current_capital = weighted = 0
    for acc in accounts.dedup(accounts.load(uid)):
        if acc.get("demo") or acc.get("shared_by"):
            continue
        state = store.get_state(db, acc["login"])
        if not state:
            pending_count += 1
            continue
        if state["currency"].upper() != currency:
            continue
        trades.use(acc)
        cap = trades.capital()
        current_capital += max(0, cap)
        rows = trades.fetch(since, until)
        archived = report_archive(since, until)
        summary = trades.summary(rows)
        # процент «Обзора» — средний по счетам, взвешенный капиталом, той же
        # мерой, что карточки (как в сводке бота), а не сумма ÷ общий капитал
        weighted += max(0, cap) * trades.period_growth(
            rows, trades.fetch(datetime(2000, 1, 1), logic.utcnow() + timedelta(days=1)), archived, cap)
        total += trades.net_of_fee(trades.mine(
            summary["total"] + sum((m["gross"] or 0) + (m["platform"] or 0) for m in archived)))
        count += summary["count"] + sum(m["trades"] or 0 for m in archived)
        account_count += 1
        archived_count += len(archived)
        for row in rows:
            if row["is_closing"] or (row["is_balance"] and not trades.is_transfer(row)
                                      and not trades.is_perf_fee(row)):
                day = row["time"].strftime("%Y-%m-%d")
                chart[day] = chart.get(day, 0) + trades.net_of_fee(trades.mine(row["net"]))
        for month in archived:
            last_day = calendar.monthrange(*map(int, month["month"].split("-")))[1]
            day = f'{month["month"]}-{last_day:02d}'
            chart[day] = chart.get(day, 0) + trades.net_of_fee(trades.mine(
                (month["gross"] or 0) + (month["platform"] or 0)))
    return web.json_response({"title": title, "summary": {"count": count, "net_income": total,
        "pct_capital": round(weighted / current_capital, 3) if current_capital > 0 else None},
        "currency": currency, "chart": [{"day": k, "value": v} for k, v in sorted(chart.items())],
        "archived": bool(archived_count), "accounts": account_count, "pending_accounts": pending_count})


CAPITAL_MOVES = ("deposit", "reinvest", "capital_out")


def move_kind(row):
    """Что это за операция на счёте — теми же словами, что в боте."""
    if trades.is_perf_fee(row):
        return "commission"
    own = trades.own_amount(row)
    if trades.is_profit_side(row):
        return "profit_out" if own < 0 else "profit_in"
    if own < 0:
        return "capital_out"
    return "reinvest" if "upgrade" in (row["comment"] or "").lower() else "deposit"


def moves_list(rows):
    """Движения средств без удержаний брокера и без половинок реинвеста.

    Реинвест приходит парой строк в один момент: Adjust списывает из профита,
    Upgrade кладёт ту же сумму в капитал. Человеку это одно событие.
    """
    balance = [r for r in rows if r["is_balance"] and not trades.is_perf_fee(r)]
    upgrades = [r["time"] for r in balance if move_kind(r) == "reinvest"]
    # половины пары бывают разнесены на секунду — сравниваем окном, а не
    # точным равенством времени, иначе реинвест показывался двумя событиями
    return [r for r in balance
            if not ("adjust" in (r["comment"] or "").lower()
                    and any(trades.same_moment(r["time"], t) for t in upgrades))]


def capital_steps(moves):
    """Капитал до и после каждого его изменения: пополнение, реинвест, вывод.

    Та же арифметика, что в trades.capital_around(): от сегодняшнего капитала
    отматываются назад все движения капитала позже строки. Только одним
    проходом по истории вместо отдельной выборки и пересчёта капитала на
    каждую строку — из-за их цены список раньше резался до последних 300,
    и начиная с седьмой страницы «Капитал было → стало» молча пропадал.
    """
    wanted = sorted((r for r in moves if move_kind(r) in CAPITAL_MOVES),
                    key=lambda r: (r["time"], r["ticket"]), reverse=True)
    if not wanted:
        return {}
    later = trades.fetch(wanted[-1]["time"], trades.clock() + timedelta(days=1))
    flows = sorted((r for r in later if r["is_balance"] and trades.is_transfer(r)
                    and not trades.is_profit_side(r)),
                   key=lambda r: (r["time"], r.get("ticket", 0)), reverse=True)
    current = trades.capital()
    steps, after, i = {}, 0.0, 0
    for row in wanted:
        mark = (row["time"], row["ticket"])
        while i < len(flows) and (flows[i]["time"], flows[i].get("ticket", 0)) > mark:
            after += trades.own_amount(flows[i])
            i += 1
        became = current - after
        was = became if trades.is_profit_side(row) else became - trades.own_amount(row)
        steps[row["ticket"]] = (was, became, row["time"])
    return steps


async def report(request):
    uid, _ = authorize(request)
    acc = owned(uid, request.match_info["login"])
    if not store.get_state(request.app["trades"], acc["login"]):
        return web.json_response({"pending": True, "deals": [], "months": [], "chart": []})
    trades.use(acc)
    title, since, until = report_period(request.query)
    rows = trades.fetch(since, until)
    summary = trades.summary(rows)
    archived = report_archive(since, until)
    total = summary["total"] + sum((m["gross"] or 0) + (m["platform"] or 0) for m in archived)
    summary["net_income"] = trades.net_of_fee(trades.mine(total))
    # один раз на запрос: капитал на дату сделки/месяца — это он же минус
    # позднейшие движения (trades.capital_at с current), а не новый пересчёт
    raw_capital = trades.capital()
    current_capital = max(0, raw_capital)
    # проценты — единой мерой trades.period_growth, как у карточек счёта: вся
    # история движений нужна, чтобы найти капитал на момент каждой сделки
    all_rows = trades.fetch(datetime(2000, 1, 1), logic.utcnow() + timedelta(days=1))
    summary["pct_capital"] = round(trades.period_growth(rows, all_rows, archived, raw_capital), 3)
    summary["count"] += sum(m["trades"] or 0 for m in archived)
    summary["wins"] += sum(m["wins"] or 0 for m in archived)
    chart = {}
    for row in rows:
        if row["is_closing"] or (row["is_balance"] and not trades.is_transfer(row)
                                  and not trades.is_perf_fee(row)):
            day = row["time"].strftime("%Y-%m-%d")
            chart[day] = chart.get(day, 0) + trades.net_of_fee(trades.mine(row["net"]))
    for month in archived:
        last_day = calendar.monthrange(*map(int, month["month"].split("-")))[1]
        day = f'{month["month"]}-{last_day:02d}'
        chart[day] = chart.get(day, 0) + trades.net_of_fee(trades.mine((month["gross"] or 0) + (month["platform"] or 0)))
    offset = max(0, int(request.query.get("offset", 0)))
    kind = request.query.get("kind", "trades")
    filtered = moves_list(rows) if kind == "moves" else [r for r in rows if r["is_closing"]]
    filtered.sort(key=lambda x: (x["time"], x["ticket"]), reverse=True)
    steps = capital_steps(filtered) if kind == "moves" else {}
    page = filtered[offset:offset + 50]
    flows = (trades.fetch(min(r["time"] for r in page), logic.utcnow() + timedelta(days=1))
             if page and kind != "moves" else [])
    deals = []
    for row in page:
        net_income = trades.own_amount(row) if row["is_balance"] else trades.net_of_fee(trades.mine(row["net"]))
        capital_then = (trades.capital_at(row["time"], flows, raw_capital)
                        if not row["is_balance"] else 0)
        item = {**row, "time": row["time"].isoformat() + "Z", "net_income": net_income,
                "pct_capital": round(net_income / capital_then * 100, 4) if capital_then > 0 else None}
        if row["is_balance"]:
            item["move"] = move_kind(row)
            if row["ticket"] in steps:
                item["capital_was"], item["capital_now"] = steps[row["ticket"]][:2]
        deals.append(item)
    # процент месяца — к капиталу на момент каждой сделки (свёрнутый — тем, что
    # сохранили при свёртке), а не к сегодняшнему: счёт, с которого капитал
    # потом вывели, делил прошлую прибыль на остаток около нуля (+4 550 067%)
    months = []
    for m in trades.monthly(120):
        live = [r for r in all_rows if f"{r['time']:%Y-%m}" == m["month"]] if m.get("_live") else []
        months.append({"month": m["month"], "count": m["trades"] or 0,
                       "net": trades.net_of_fee(trades.mine((m["gross"] or 0) + (m["platform"] or 0))),
                       "pct_capital": round(trades.period_growth(
                           live, all_rows, () if m.get("_live") else (m,), raw_capital), 3)})
    starts = {key: logic.period(key)[1] for key in ("week", "lastweek", "month")}
    recent = trades.fetch(min(starts.values()), logic.utcnow() + timedelta(days=1))
    insights = {}
    for key in ("week", "lastweek", "month"):
        _, first, last, _ = logic.period(key)
        old = report_archive(first, last)
        selected = [r for r in recent if first <= r["time"] <= last]
        summary_for_period = trades.summary(selected)
        amount = summary_for_period["total"] + sum((m["gross"] or 0) + (m["platform"] or 0) for m in old)
        insights[key] = {"available": True, "count": summary_for_period["count"] +
                         sum(m["trades"] or 0 for m in old),
                         "net": trades.net_of_fee(trades.mine(amount)),
                         "pct_capital": round(trades.period_growth(selected, all_rows, old, raw_capital), 3)}
    insights["all"] = {"available": True, "count": sum(m["count"] for m in months),
                       "net": sum(m["net"] for m in months),
                       "pct_capital": round(trades.growth_all(), 3)}   # тот же ROI, что на карточке
    # итоги дня — только для сделок: у движений средств интерфейс их не
    # показывает, а «процент от капитала» у суммы пополнений смысла не имеет
    by_day = {}
    for row in (rows if kind != "moves" else ()):
        by_day.setdefault(row["time"].strftime("%Y-%m-%d"), []).append(row)
    day_totals = {}
    for day, day_rows in by_day.items():
        day_summary = trades.summary(day_rows)
        day_net = trades.net_of_fee(trades.mine(day_summary["total"]))
        day_totals[day] = {"count": day_summary["count"], "net": day_net,
                           "pct_capital": round(trades.growth_pct(day_rows, all_rows, raw_capital), 3)}
    extra = {}
    if kind == "moves":
        # общая сумма удержанной комиссии брокера (30%) — одной цифрой вместо
        # еженедельных строк PF Deduction в списке
        fees = [abs(r["net"]) for r in rows if r["is_balance"] and trades.is_perf_fee(r)]
        ordered = sorted(steps.values(), key=lambda v: v[2])
        series = ([{"time": ordered[0][2].isoformat() + "Z", "capital": ordered[0][0]}] if ordered else []) + [
            {"time": v[2].isoformat() + "Z", "capital": v[1]} for v in ordered]
        site = (partner.site_moves(request.app["db"], acc.get("cabinet") or "", since, until)
                if acc.get("cabinet") else [])
        extra = {"commission_total": round(sum(fees), 2), "commission_count": len(fees),
                 "capital_series": series,
                 "site_moves": [{**m, "time": m["time"] + "Z"} for m in site]}
    return web.json_response({**extra, "title": title, "summary": summary, "currency": trades.currency(),
        "deals": deals, "has_more": offset + 50 < len(filtered), "offset": offset,
        "insights": insights, "day_totals": day_totals,
        "chart": [{"day": k, "value": v} for k, v in sorted(chart.items())],
        "months": months, "archived": bool(archived),
        "report": plain_report(trades.fmt_report(title, rows, trades.currency(), since=since, until=until))})


async def price_chart(request):
    """Свечи XAUUSD за период + точки входа/выхода сделок счёта — для графика
    цены на карточке стратегии. Свечи хранятся только CANDLE_KEEP_DAYS дней
    (см. store.trim_candles), поэтому глубокие периоды обрезаются по факту.
    """
    uid, _ = authorize(request)
    acc = owned(uid, request.match_info["login"])
    if not store.get_state(request.app["trades"], acc["login"]):
        return web.json_response({"pending": True, "candles": [], "trades": []})
    trades.use(acc)
    title, since, until = report_period(request.query)
    edge = trades.clock() - timedelta(days=store.CANDLE_KEEP_DAYS)
    since = max(since, edge)
    db = request.app["trades"]
    candles = store.get_candles(db, since, until)
    rows = [r for r in trades.fetch(since, until) if r["is_closing"] or r["is_opening"]]
    # сравниваем по базовому имени: у брокера тикеры с суффиксом (XAUUSD.f),
    # и он может смениться — маркеры сделок не должны из-за этого пропадать
    base = trades.CHART_SYMBOL.split(".")[0]
    rows = [r for r in rows if (r["symbol"] or "").split(".")[0] == base]
    markers = [{"time": r["time"].isoformat() + "Z", "side": r["side"], "price": r["price"],
               "kind": "in" if r["is_opening"] else "out", "symbol": r["symbol"]} for r in rows]
    return web.json_response({"title": title, "symbol": trades.CHART_SYMBOL,
        "candles": [{**c, "time": c["time"] + "Z"} for c in candles], "trades": markers,
        "pairs": trade_pairs(rows)})


def trade_pairs(rows: list[dict]) -> list[dict]:
    """Вход → выход, как линии сделок в терминале MT5.

    Связываем по номеру позиции. У сделок, сохранённых до того, как сервер
    начал его хранить, номера нет — там закрытие забирает самую раннюю ещё
    открытую позицию противоположной стороны (закрывающая сделка BUY-позиции
    в MT5 — SELL). Вход до начала периода — пара без входа, только выход.
    """
    queue = {"BUY": [], "SELL": []}
    by_position, pairs = {}, []
    for r in sorted(rows, key=lambda r: (r["time"], r["ticket"])):
        if r["is_opening"]:
            queue.setdefault(r["side"], []).append(r)
            if r.get("position"):
                by_position[r["position"]] = r
            continue
        entry = by_position.pop(r.get("position"), None) if r.get("position") else None
        waiting = queue.get("SELL" if r["side"] == "BUY" else "BUY", [])
        if entry is not None and entry in waiting:
            waiting.remove(entry)
        elif entry is None and waiting:
            entry = waiting.pop(0)
        pairs.append({"side": entry["side"] if entry else ("SELL" if r["side"] == "BUY" else "BUY"),
                      "in_time": entry["time"].isoformat() + "Z" if entry else None,
                      "in_price": entry["price"] if entry else None,
                      "out_time": r["time"].isoformat() + "Z", "out_price": r["price"],
                      "net": r["net"], "volume": r["volume"]})
    return pairs


def bounded_text(data, key, maximum=64, required=False):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(key)
    return value.strip()


async def add_account(request):
    uid, _ = authorize(request)
    data = await json_object(request)
    login = mt5_login(data.get("login"))
    cabinet = bounded_text(data, "cabinet", 32)
    # новый номер кабинета — в том же виде, что принимает бот (латиница и
    # цифры): он уходит в callback_data кнопок бота и сверяется с порталом.
    # Уже существующий кабинет владельца принимаем как есть, чтобы старые
    # записи не откололись от своей группы
    if cabinet and cabinet not in {a.get("cabinet") for a in accounts.load(uid)}:
        try:
            cabinet = accounts.normalize_cabinet(cabinet)
        except ValueError as error:
            raise web.HTTPBadRequest(text="Номер кабинета — латинские буквы и цифры, "
                                          "например CU228816") from error
    # The terminal is the source of truth for broker server and account name.
    # Keep an optional deployment default only for the first login handshake;
    # agent_sync replaces it with the values reported by MT5.
    server = os.getenv("MT5_SERVER", "").strip()
    if not server:
        known = next((a.get("server") for a in accounts.load() if a.get("server")), "")
        server = known or "TMFinancials-Server"
    # Keep the global claim check and write in one cross-process transaction.
    # account_lock.locked is reentrant for accounts.add() in this thread.
    with locked(accounts.PATH):
        if any(int(a["login"]) == login for a in accounts.load()):
            raise web.HTTPConflict(text="Счёт уже подключён. Попросите владельца прислать приглашение")
        # Do not reveal abandoned trading history until credentials are verified.
        if store.get_state(request.app["trades"], login):
            raise web.HTTPConflict(text="Для повторного подключения этого счёта обратитесь к владельцу бота")
        accounts.add({"owner": uid, "login": login, "server": server,
            "name": bounded_text(data, "name", 48, True),
            "strategy": bounded_text(data, "name", 48, True),
            "holder": bounded_text(data, "holder", 96),
            "cabinet": cabinet,
            "password": bounded_text(data, "password", 128, True),
            "multiplier": logic.DEFAULT_MULTIPLIER})
    return web.json_response({"ok": True, "pending": True}, status=201)


async def change_account(request):
    uid, _ = authorize(request)
    data = await json_object(request) if request.method != "DELETE" else {}
    with locked(accounts.PATH):
        return _change_account(uid, request.match_info["login"], request.method, data, request.app["db"])


def _change_account(uid, login, method, data, db=None):
    acc = owned(uid, login)
    public_demo = acc.get("demo") and not any(int(a.get("login", 0)) == int(login) and str(a.get("owner")) == str(uid) for a in accounts.load(uid))
    if public_demo:
        if method == "DELETE":
            raise web.HTTPForbidden(text="Публичный счёт нельзя удалить")
        if set(data) - {"enabled", "notify"}:
            raise ValueError("unknown field")
        if "enabled" in data:
            if type(data["enabled"]) is not bool: raise ValueError("enabled")
            logic.kv_set(db, f"public_demo:{uid}:enabled", "1" if data["enabled"] else "0")
        if "notify" in data:
            values = data["notify"]
            if not isinstance(values, dict) or set(values) - {"all", *accounts.NOTIFY_KINDS} or any(type(v) is not bool for v in values.values()):
                raise ValueError("notify")
            logic.kv_set(db, f"public_demo:{uid}:notify", json.dumps(values))
        return web.json_response({"ok": True})
    if method == "DELETE":
        if acc.get("demo"):
            raise web.HTTPForbidden(text="Демо-счёт можно скрыть, но нельзя удалить")
        accounts.remove(acc["name"], uid)
    else:
        if set(data) - {"name", "enabled", "notify", "base"}:
            raise ValueError("unknown field")
        if "name" in data:
            if acc.get("demo"):
                raise web.HTTPForbidden(text="Демо-счёт доступен только для наблюдения")
            bounded_text(data, "name", 48, True)
        changes = {}
        if "enabled" in data:
            if acc.get("shared_by"):
                raise web.HTTPForbidden(text="Опрос этого счёта включает и выключает только владелец")
            if type(data["enabled"]) is not bool:
                raise ValueError("enabled")
            changes["enabled"] = data["enabled"]
        if "notify" in data:
            values = data["notify"]
            if not isinstance(values, dict) or set(values) - {"all", *accounts.NOTIFY_KINDS} or any(type(v) is not bool for v in values.values()):
                raise ValueError("notify")
            changes["notify"] = {**acc["notify"], **values}
        if "base" in data:
            if acc.get("demo") or acc.get("shared_by"):
                raise web.HTTPForbidden(text="Капитал этого счёта доступен только для чтения")
            if data["base"] is None:
                changes.update(base=None, base_at=None)
            else:
                value = float(data["base"])
                if not math.isfinite(value) or not 0 <= value <= 1e12:
                    raise ValueError("base")
                changes.update(base=value, base_at=trades.clock().isoformat())
        if "name" in data:
            acc["name"] = accounts.rename(acc["name"], uid, data["name"])
        if changes:
            accounts.update(acc["name"], uid, **changes)
    return web.json_response({"ok": True})


async def people(request):
    uid, _ = authorize(request)
    db = request.app["db"]
    guests = [{"id": guest, "name": name, "since": logic.when_joined(db, guest),
               "accounts": [{"login": a["login"], "name": a.get("strategy") or a["name"],
                             "shared": str(a.get("shared_by", "")) == uid and a.get("shared_origin") != "inferred"}
                            for a in accounts.load(guest) if not a.get("demo")]}
              for guest, name in logic.guests_of(db, uid)]
    username = os.getenv("TELEGRAM_BOT_USERNAME", "tagmarketgold_bot")
    partner_url = logic.partner_link(db, uid)
    link = logic.invite_link(username, logic.invite_personal(db, uid)) if partner_url else None
    return web.json_response({"guests": guests, "link": link, "partner_url": partner_url,
                              "shareable": [{"login": a["login"], "name": a.get("strategy") or a["name"],
                                             "cabinet": a.get("cabinet")}
                                            for a in accounts.load(uid)
                                            if not a.get("demo") and not a.get("shared_by")]})


async def cabinet_report(request):
    uid, _ = authorize(request)
    cabinet = request.match_info["cabinet"]
    if cabinet not in accounts.cabinets(uid):
        raise web.HTTPNotFound(text="Кабинет не найден")
    period = request.query.get("period", "month")
    if period not in ("today", "yesterday", "week", "lastweek", "month", "lastmonth", "all"):
        raise ValueError("period")
    return web.json_response({"report": plain_report(logic.build_all(period, uid, cabinet))})


async def invite(request):
    uid, _ = authorize(request)
    db = request.app["db"]
    username = os.getenv("TELEGRAM_BOT_USERNAME", "tagmarketgold_bot")
    if request.method != "DELETE" and not logic.partner_link(db, uid):
        raise web.HTTPPreconditionRequired(text="Сначала сохраните свою ссылку из раздела Partner в IB Portal")
    if request.method == "DELETE":
        # «обновить ссылку»: прежняя перестаёт работать, входившие остаются гостями
        token = request.match_info["token"]
        inv = logic.invite_get(db, token)
        if not inv or str(inv["owner"]) != uid:
            raise web.HTTPNotFound(text="Приглашение не найдено")
        if inv.get("personal"):
            token = logic.invite_personal(db, uid, renew=True)
        else:
            inv["revoked"] = True
            logic.invite_save(db, token, inv)
            token = logic.invite_personal(db, uid)
    else:
        token = logic.invite_personal(db, uid)
    return web.json_response({"url": logic.invite_link(username, token),
                              "partner_url": logic.partner_link(db, uid)})


async def partner_profile(request):
    uid, _ = authorize(request)
    db = request.app["db"]
    if request.method == "GET":
        return web.json_response({"url": logic.partner_link(db, uid),
                                  "portal": "https://exfusion.ibportal.io"})
    data = await json_object(request)
    value = str(data.get("url", "")).strip()
    if not logic.valid_partner_link(value):
        raise ValueError("partner url")
    partner.kv_set(db, f"partner_link:{uid}", value)
    return web.json_response({"ok": True, "url": value})


async def guest_action(request):
    uid, _ = authorize(request)
    db = request.app["db"]
    guest = request.match_info["guest"]
    if str(partner.kv_get(db, f"guest_by:{guest}")) != uid or logic.is_founder(guest) or guest == uid:
        raise web.HTTPForbidden(text="Нет доступа к этому гостю")
    data = await json_object(request)
    if data.get("action") == "revoke":
        try:
            logic.revoke_guest(db, uid, guest)
        except ValueError as error:
            raise web.HTTPConflict(text=str(error)) from error
    elif data.get("action") == "share":
        raw = data.get("logins", [])
        # строка "123" раньше итерировалась посимвольно (счета 1, 2, 3), а
        # [true] превращался в счёт 1 — только список номеров
        if not isinstance(raw, list) or len(raw) > 50:
            raise ValueError("logins")
        logins = list(dict.fromkeys(mt5_login(x) for x in raw))
        for login in logins:
            acc = owned(uid, login)
            if acc.get("demo") or acc.get("shared_by"):
                raise web.HTTPForbidden(text="Делиться можно только собственными счетами")
        try:
            added = accounts.share(logins, uid, guest) if logins else []
        except ValueError as error:
            raise web.HTTPConflict(text=str(error)) from error
        return web.json_response({"ok": True, "added": len(added)})
    elif data.get("action") == "take":
        acc = owned(uid, mt5_login(data.get("login")))
        shared = next((a for a in accounts.load(guest)
                       if int(a["login"]) == int(acc["login"])
                       and str(a.get("shared_by", "")) == uid
                       and a.get("shared_origin") != "inferred"), None)
        if not shared:
            raise web.HTTPForbidden(text="Личный счёт гостя доступен только для просмотра")
        accounts.remove_login(acc["login"], guest, shared_by=uid)
    else:
        raise ValueError("action")
    return web.json_response({"ok": True})


async def guest_detail(request):
    uid, _ = authorize(request)
    db = request.app["db"]
    guest = request.match_info["guest"]
    if str(partner.kv_get(db, f"guest_by:{guest}")) != uid:
        raise web.HTTPForbidden(text="Нет доступа к этому гостю")
    text, _ = logic.guest_view(db, uid, guest)
    return web.json_response({"report": plain_report(text)})


async def action(request):
    uid, _ = authorize(request)
    db = request.app["db"]
    data = await json_object(request)
    kind = data.get("action")
    if kind == "restart":
        acc = owned(uid, mt5_login(data.get("login")))
        if acc.get("demo") or acc.get("shared_by"):
            raise web.HTTPForbidden(text="Общий терминал недоступен для управления гостю")
        store.set_command(request.app["trades"], acc["login"], "restart_terminal")
        partner.kv_set(db, f"restart_asked:{uid}", "1")
    elif kind == "update_alerts" and logic.is_founder(uid):
        if type(data.get("value")) is not bool:
            raise ValueError("value")
        partner.kv_set(db, "update_alerts", "1" if data["value"] else "0")
    elif kind == "leave" and not logic.is_founder(uid):
        logic.wipe_user(db, uid)
    else:
        raise web.HTTPForbidden(text="Действие недоступно")
    return web.json_response({"ok": True})


ALIVE_WITHIN = 120      # секунд: любой отклик машины за это время — процесс жив
UPDATE_EVERY = 900      # как часто агент сам проверяет обновления (UPDATE_CHECK_EVERY)


def _seconds_since(stamp, now):
    try:
        return max(0, now - datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).timestamp())
    except (TypeError, ValueError):
        return None


def machine_states(db, now):
    """Агентские машины и понятное состояние каждой.

    Состояние считает сервер, а не интерфейс: «опрашивает» — держит аренду;
    «ждёт» — жива и готова подхватить; «старый код» — жива, но не умеет
    просить аренду (агент до её появления), поэтому заменить основную не
    сможет; «офлайн» — давно не отвечала.
    """
    lease = coordination.read(db)
    holder = lease["host"] if lease and lease["expires"] > now else None
    hosts = set()
    for pattern in ("machine_seen:%", "machine_role:%", "machine_claim:%",
                    "canary_latest_seen:%", "machine_sync:%"):
        hosts.update(k.split(":", 1)[1] for k in partner.kv_keys(db, pattern))
    out = []
    for host in sorted(hosts):
        stamps = {n: _seconds_since(partner.kv_get(db, f"{n}:{host}"), now)
                  for n in ("machine_seen", "machine_claim", "canary_latest_seen", "machine_sync")}
        contacts = [v for v in stamps.values() if v is not None]
        idle = min(contacts) if contacts else None
        alive = idle is not None and idle < ALIVE_WITHIN
        claiming = stamps["machine_claim"] is not None and stamps["machine_claim"] < ALIVE_WITHIN
        if host == holder:
            state = "polling"
        elif not alive:
            state = "offline"
        elif claiming:
            state = "waiting"
        else:
            state = "legacy"
        blocked_at, _, blocked_why = (partner.kv_get(db, f"machine_blocked:{host}") or "").partition("|")
        age = _seconds_since(blocked_at, now)
        out.append({"host": host, "role": partner.kv_get(db, f"machine_role:{host}"),
                    "state": state, "idle": None if idle is None else round(idle),
                    # причина показывается, пока свежа: проверка обновлений идёт
                    # раз в 15 минут, а после успешного обновления запись стареет сама
                    "blocked": blocked_why if age is not None and age < 1800 else "",
                    # агент повторяет проверку сам; если папка проекта исправлена,
                    # обновится на ближайшей — показываем, когда она будет. По
                    # модулю цикла: отметка живёт 30 минут, и во второй их
                    # половине max(0, …) давал 0 — «меньше минуты» 15 минут подряд
                    "next_check": (round(UPDATE_EVERY - age % UPDATE_EVERY)
                                   if blocked_why and age is not None and age < 1800 else None),
                    "synced": stamps["machine_sync"] if stamps["machine_sync"] is None
                              else round(stamps["machine_sync"]),
                    "commit": (partner.kv_get(db, f"machine_commit:{host}") or "")[:7]})
    return out


async def admin(request):
    uid, _ = authorize(request)
    if not logic.is_founder(uid):
        raise web.HTTPForbidden(text="Только для основателя")
    db = request.app["db"]
    return web.json_response({"machines": machine_states(db, time.time()),
        "active": partner.kv_get(db, "active_machine"),
        "users": [{"id": u, "name": n} for u, n in logic.all_guests(db)],
        "network": [{"day": k.split(":", 1)[1], "income": float(partner.kv_get(db, k) or 0),
                     "trades": int(partner.kv_get(db, k.replace("net_income:", "net_trades:")) or 0)}
                    for k in sorted(partner.kv_keys(db, "net_income:%"), reverse=True)[:30]]})


async def broadcast(request):
    uid, _ = authorize(request)
    if not logic.is_founder(uid):
        raise web.HTTPForbidden(text="Только для основателя")
    media_path = None
    media_kind = None
    media_digest = ""
    try:
        if request.content_type.startswith("multipart/"):
            data = {}
            reader = await request.multipart()
            async for part in reader:
                if part.name != "media":
                    data[part.name] = (await part.text()).strip()
                    continue
                if media_path:
                    raise web.HTTPBadRequest(text="Можно приложить только один файл")
                media_path = Path(tempfile.gettempdir()) / f"tagmarkets-broadcast-{uuid.uuid4().hex}.upload"
                size = 0
                digest = hashlib.sha256()
                header = b""
                with os.fdopen(os.open(media_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as dst:
                    while chunk := await part.read_chunk(64 * 1024):
                        size += len(chunk)
                        if size > 20 * 1024 * 1024:
                            raise web.HTTPBadRequest(text="Фото до 10 МБ, видео до 20 МБ")
                        if len(header) < 16:
                            header = (header + chunk)[:16]
                        digest.update(chunk)
                        dst.write(chunk)
                if header.startswith(b"\xff\xd8\xff"):
                    suffix, media_kind = ".jpg", "photo"
                elif header.startswith(b"\x89PNG\r\n\x1a\n"):
                    suffix, media_kind = ".png", "photo"
                elif header[4:8] == b"ftyp":
                    suffix, media_kind = ".mp4", "video"
                else:
                    raise web.HTTPBadRequest(text="Разрешены JPG, PNG и MP4")
                if media_kind == "photo" and size > 10 * 1024 * 1024:
                    raise web.HTTPBadRequest(text="Фото до 10 МБ, видео до 20 МБ")
                named_path = media_path.with_suffix(suffix)
                media_path.rename(named_path)
                media_path = named_path
                media_digest = digest.hexdigest()
        else:
            if request.content_type == "application/json":
                data = await json_object(request)
            else:
                # aiohttp FormData without a file is urlencoded, so accept it
                # just like multipart submissions from the web form.
                data = {k: v for k, v in (await request.post()).items()}
        try:
            body = sanitize_broadcast_html(data.get("text", ""))
        except ValueError:
            raise web.HTTPBadRequest(text="Текст слишком длинный")
        if telegram_length(plain_report(body)) > 4096:
            raise web.HTTPBadRequest(text="Текст превышает лимит Telegram")
        if not body and not media_path:
            raise web.HTTPBadRequest(text="Добавьте текст или медиафайл")
        target = str(data.get("target", "all"))
        db = request.app["db"]
        known = {u for u, _ in logic.all_guests(db)}
        if target != "all" and target not in known:
            raise web.HTTPNotFound(text="Получатель не найден")
        if not known:
            raise web.HTTPBadRequest(text="Пока нет получателей")
        key = bounded_text(data, "request_id", 64, True)
        fingerprint = hashlib.sha256(json.dumps(
            [target, body, media_kind, media_digest], ensure_ascii=False).encode()).hexdigest()
        token = os.environ["TELEGRAM_BOT_TOKEN"]
        proxies = [p.strip() for p in os.getenv("TELEGRAM_PROXY", "").split(",") if p.strip()] or [""]
        proxy = None
        for candidate in proxies:
            if await logic.works(token, candidate):
                proxy = candidate
                break
        if proxy is None:
            raise web.HTTPServiceUnavailable(text="Telegram сейчас недоступен. Сообщение не отправлено — попробуйте позже")
        if key in _broadcast_active:
            raise web.HTTPConflict(text="Эта рассылка уже выполняется")
        campaign_key = f"mini_broadcast:{key}"
        raw = partner.kv_get(db, campaign_key)
        if raw:
            try:
                campaign = json.loads(raw)
            except (ValueError, TypeError):
                raise web.HTTPConflict(text="Старая попытка требует нового сообщения")
            if not isinstance(campaign, dict) or campaign.get("fingerprint") != fingerprint:
                raise web.HTTPConflict(text="Содержимое повторной отправки отличается от исходного")
        else:
            campaign = {"fingerprint": fingerprint,
                        "recipients": {recipient: "pending" for recipient in
                                       sorted(known if target == "all" else {target})}}
            partner.kv_set(db, campaign_key, json.dumps(campaign))
        session = logic.AiohttpSession(proxy=proxy or None)
        sender = logic.Bot(token, session=session)
        _broadcast_active.add(key)
        try:
            # Telegram limits media captions to 1024 characters. Longer messages
            # follow the attachment as a separate formatted message.
            caption = body if telegram_length(plain_report(body)) <= 1000 else None
            for recipient, status in campaign["recipients"].items():
                if status == "sent":
                    continue
                try:
                    if status != "media_sent":
                        if media_kind == "photo":
                            await sender.send_photo(recipient, FSInputFile(media_path), caption=caption,
                                                    parse_mode=ParseMode.HTML)
                        elif media_kind == "video":
                            await sender.send_video(recipient, FSInputFile(media_path), caption=caption,
                                                    parse_mode=ParseMode.HTML, supports_streaming=True)
                        if media_kind:
                            campaign["recipients"][recipient] = "media_sent"
                            partner.kv_set(db, campaign_key, json.dumps(campaign))
                    if body and (not media_kind or caption is None):
                        await sender.send_message(recipient, body, parse_mode=ParseMode.HTML)
                    campaign["recipients"][recipient] = "sent"
                    partner.kv_set(db, campaign_key, json.dumps(campaign))
                    try:
                        partner.record_notification(db, recipient, f"broadcast:{key}", "message",
                                                    "Сообщение Tag Markets",
                                                    plain_report(body) or ("Фото" if media_kind == "photo" else "Видео"))
                    except sqlite3.DatabaseError:
                        logging.exception("broadcast delivered but inbox save failed for %s", recipient)
                except Exception:
                    logging.exception("miniapp broadcast failed for recipient %s", recipient)
                    if campaign["recipients"][recipient] != "media_sent":
                        campaign["recipients"][recipient] = "failed"
                        partner.kv_set(db, campaign_key, json.dumps(campaign))
        finally:
            try:
                await session.close()
            finally:
                _broadcast_active.discard(key)
        result = {"sent": sum(s == "sent" for s in campaign["recipients"].values()),
                  "failed": sum(s != "sent" for s in campaign["recipients"].values())}
        return web.json_response(result)
    finally:
        if media_path:
            media_path.unlink(missing_ok=True)


async def static(request):
    name = request.match_info.get("file", "index.html") or "index.html"
    if name not in ("index.html", "app.js", "style.css", "brand.svg", "preview.json"):
        raise web.HTTPNotFound()
    response = web.FileResponse(STATIC / name)
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' https://telegram.org; "
        "style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "connect-src 'self'; base-uri 'none'; object-src 'none'")
    return response


async def app_redirect(request):
    raise web.HTTPFound("app/")


def setup(app):
    # Legacy copies lack provenance. Matching only a login is unsafe: an
    # independently added account may use that number with another password.
    with locked(accounts.PATH):
        accs = accounts._read()
        changed = False
        for acc in accs:
            parent = partner.kv_get(app["db"], f"guest_by:{acc['owner']}")
            if not acc.get("shared_by") and parent and any(
                    str(src["owner"]) == str(parent) and src["login"] == acc["login"]
                    and src["server"] == acc["server"]
                    and src.get("password") == acc.get("password")
                    and src.get("cabinet") == acc.get("cabinet") for src in accs):
                acc["shared_by"] = str(parent)
                acc["shared_origin"] = "inferred"
                changed = True
        if changed:
            accounts.save(accs)
    app.middlewares.append(api_errors)
    app.router.add_get("/app", app_redirect)
    app.router.add_get("/app/", static)
    app.router.add_get("/app/{file}", static)
    app.router.add_get("/api/bootstrap", bootstrap)
    app.router.add_get("/api/notifications", notifications)
    app.router.add_post("/api/notifications", notifications)
    app.router.add_post("/api/onboarding", onboarding_progress)
    app.router.add_get("/api/overview/report", overview_report)
    app.router.add_get("/api/accounts/{login}/report", report)
    app.router.add_get("/api/accounts/{login}/candles", price_chart)
    app.router.add_post("/api/accounts", add_account)
    app.router.add_patch("/api/accounts/{login}", change_account)
    app.router.add_delete("/api/accounts/{login}", change_account)
    app.router.add_get("/api/people", people)
    app.router.add_get("/api/cabinets/{cabinet}/report", cabinet_report)
    app.router.add_post("/api/invites", invite)
    app.router.add_get("/api/profile/partner-link", partner_profile)
    app.router.add_put("/api/profile/partner-link", partner_profile)
    app.router.add_delete("/api/invites/{token}", invite)
    app.router.add_post("/api/guests/{guest}", guest_action)
    app.router.add_get("/api/guests/{guest}", guest_detail)
    app.router.add_post("/api/actions", action)
    app.router.add_get("/api/admin", admin)
    app.router.add_post("/api/broadcast", broadcast)
