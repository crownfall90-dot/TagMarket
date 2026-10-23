"""Telegram Mini App API. Shares accounts, reports and preferences with the bot.

Handlers do not yield while using the legacy trades calculation context.
Only signed Telegram initData is accepted; no browser authentication bypass.
"""
import asyncio
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
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

os.environ["TRADES_SOURCE"] = "store"
import accounts
import activity
import banks
import devices
import push
import bot as logic
import coordination
import friends
import fx
import goals
import income
import insights
import lists
import live
import spend
import partner
import projects
import store
import trades

STATIC = Path(__file__).parent / "web"
MAX_AUTH_AGE = 86400
_rates = OrderedDict()
_broadcast_active = set()


async def fx_snapshot(db=None):
    """Единый снимок курсов (MYFIN -> НБРБ -> последний сохранённый)."""
    return await fx.service.get(db)


def usd_factor(currency, byn_per_unit):
    currency = (currency or "USD").upper()
    if currency not in {"USD", "RUB", "BYN"}:
        return None
    return byn_per_unit[currency] / byn_per_unit["USD"]


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


def device_token(request):
    """Токен приложения для Android из «Authorization: Bearer pld_…», иначе None."""
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    return token if token.startswith(devices.TOKEN_PREFIX) else None


def authorize(request):
    db = request.app["db"]
    token = device_token(request)
    if token:
        # приложение для Android: устройство привязано кодом из бота (/app)
        owner = devices.owner_for(db, token)
        if owner is None:
            raise web.HTTPUnauthorized(text="Устройство отвязано — войдите заново кодом из бота")
        user = {"id": int(owner) if owner.isdigit() else owner,
                "first_name": partner.kv_get(db, f"user_name:{owner}") or ""}
    else:
        try:
            user = validate_init_data(request.headers.get("X-Telegram-Init-Data", ""),
                                      os.getenv("TELEGRAM_BOT_TOKEN", ""))
        except (ValueError, TypeError, KeyError, AttributeError):
            raise web.HTTPUnauthorized(text="Откройте приложение заново через Telegram")
    uid = str(user["id"])
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
    request["uid"] = uid
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
        raise web.HTTPNotFound(text="Счёт не найден")
    return acc


def current_account_settings(acc):
    """Use the inviter's current capital settings for a read-only shared account."""
    inviter = acc.get("shared_by")
    if not inviter:
        return acc
    source = next((item for item in accounts.load(inviter)
                   if int(item["login"]) == int(acc["login"])
                   and item.get("server") == acc.get("server")), None)
    if not source:
        return acc
    return {**acc, **{key: source.get(key) for key in ("multiplier", "base", "base_at")}}


_state_db = None     # партнёрская KV, где лежат имена пользователей; задаётся в setup()


def person_name(uid):
    """Имя пользователя Telegram: запомненное при входе в Mini App или имя гостя."""
    if _state_db is None:
        return ""
    return partner.kv_get(_state_db, f"user_name:{uid}") or partner.kv_get(_state_db, f"guest_name:{uid}") or ""


def public_account(acc, db):
    result = {k: acc.get(k) for k in ("login", "name", "strategy", "cabinet", "holder",
              "server", "enabled", "notify", "base", "base_at")}
    # У копий общего демо-счёта номер в accounts.json лежит строкой, у остальных —
    # числом. Интерфейс сравнивает его строго, и «Настроить» на такой записи
    # молча ничего не делало
    result["login"] = int(acc["login"])
    result["shared"] = bool(acc.get("shared_by"))
    if result["shared"]:
        # выданный счёт выглядит как свой; кем и когда выдан — мелкой подписью
        result["shared_at"] = acc.get("shared_at")
        result["shared_by_name"] = person_name(acc["shared_by"]) or acc.get("holder") or ""
    state = store.get_state(db, acc["login"])
    result["synced"] = (state or {}).get("synced")
    result["status"] = "pending"
    result["totals"] = None
    if state:
        age = (logic.utcnow() - datetime.fromisoformat(state["synced"])).total_seconds()
        result["status"] = "fresh" if age < logic.TERMINAL_STALE else "stale"
        result["totals"] = logic.account_totals(current_account_settings(acc))
    return result


async def bootstrap(request):
    uid, user = authorize(request)
    db = request.app["db"]
    name = " ".join(str(user.get(k) or "").strip() for k in ("first_name", "last_name")).strip()[:64]
    if name and partner.kv_get(db, f"user_name:{uid}") != name:
        partner.kv_set(db, f"user_name:{uid}", name)
    items = [public_account(a, request.app["trades"]) for a in accounts.dedup(accounts.load(uid))]
    currencies = {a["totals"]["cur"].upper() for a in items
                  if a["totals"]}
    project_currencies = {p[0] for p in db.execute("SELECT currency FROM projects WHERE owner_id=?", (str(uid),))}
    # валюты банковских счетов тоже нужны курсу: баланс в BYN или RUB показывается в валюте отображения
    project_currencies |= {a["currency"] for a in banks.accounts(db, uid)}
    # и валюты трат: подписки часто в EUR
    project_currencies |= {r[0] for r in db.execute("SELECT DISTINCT currency FROM spend_items WHERE owner_id=?", (str(uid),))}
    project_currencies |= {r[0] for r in db.execute("SELECT DISTINCT currency FROM income_items WHERE owner_id=?", (str(uid),))}
    project_currencies |= {r[0] for r in db.execute("SELECT DISTINCT currency FROM goals WHERE owner_id=?", (str(uid),))}
    display_currency = partner.kv_get(db, f"display_currency:{uid}", "USD")
    unsupported = currencies - {"USD", "RUB", "BYN"}
    byn_per_unit = fx_info = None
    fx_error = ""
    if currencies - {"USD"} or project_currencies - {"USD"} or display_currency != "USD":
        try:
            fx_info = await fx_snapshot(db)
            byn_per_unit = fx_info["rates"]
        except fx.FxUnavailable:
            fx_error = "Не удалось обновить курс НБРБ на MYFIN"
    if unsupported:
        fx_error = "Для полной сводки поддерживаются только USD, RUB и BYN"
    # Personal totals are shown in USD when a current official quote is available.
    totals = {}
    trading_days = [a["totals"]["last_trade_day"] for a in items
                    if a.get("totals")
                    and a["totals"].get("last_trade_day")]
    latest_trading_day = max(trading_days, default=None)
    trading_day_usd = 0.0
    trading_day_partial = False
    for a in items:
        t = a["totals"]
        if not t:
            continue
        currency = t["cur"].upper()
        factor = usd_factor(currency, byn_per_unit) if byn_per_unit else (1 if currency == "USD" else None)
        if t.get("last_trade_day") == latest_trading_day:
            if factor is None:
                trading_day_partial = True
            else:
                trading_day_usd += (t.get("last_trade_net") or 0) * factor
        if factor is None:
            continue
        bucket = totals.setdefault("USD", {"capital": 0, "balance": 0, "pnl": 0, "month": 0, "today": 0, "kept": 0})
        # balance — что показываем (капитал вместе с невыведенным результатом сделок),
        # capital — база процентов
        for key, source in (("capital", "capital"), ("balance", "now"), ("pnl", "pnl"), ("month", "month_net"),
                            ("today", "today_net"), ("kept", "kept")):
            bucket[key] += t.get(source, t["now"]) * factor if factor is not None else t[source]
    if latest_trading_day:
        bucket = totals.setdefault("USD", {"capital": 0, "balance": 0, "pnl": 0, "month": 0, "today": 0, "kept": 0})
        bucket.update({"trading_day": latest_trading_day,
                       "trading_day_net": round(trading_day_usd, 2),
                       "trading_day_partial": trading_day_partial})
    # выданный счёт считается своим: онбординг не нужен, если счета уже есть
    own_accounts = items
    inviter = partner.kv_get(db, f"guest_by:{uid}")
    registration_url = (logic.partner_link(db, inviter) if inviter else logic.partner_registration_url())
    return web.json_response({"user": {"id": user["id"], "name": user.get("first_name", "Инвестор")},
        "accounts": items, "totals": totals,
        "fx": ({"source": fx.LABELS[fx_info["provider"]], "provider": fx_info["provider"],
                "stale": fx_info["stale"], "currency": "USD", "byn_per_unit": byn_per_unit,
                "byn_per_usd": byn_per_unit["USD"], "byn_per_100_rub": byn_per_unit["RUB"] * 100,
                "updated_at": fx_info["updated_at"]}
               if byn_per_unit else None), "fx_error": fx_error,
        "display_currency": display_currency,
        "station": station_prefs(db, uid),
        "insights": insights_for(db, uid, display_currency, byn_per_unit,
                                 (totals["USD"]["month"], totals["USD"]["today"], "USD") if totals.get("USD") else None),
        "onboarding": {"needed": not own_accounts,
                        "later": partner.kv_get(db, f"onboard:{uid}:later") == "1",
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
    if step not in (*steps, "later") or type(data.get("done")) is not bool:
        raise web.HTTPBadRequest(text="Некорректный шаг")
    db = request.app["db"]
    # «Зарегистрируюсь позже»: новичок открывает всё приложение без своих
    # счетов — общий счёт и то, чем поделился пригласивший. Хранится на
    # сервере, чтобы выбор не сбрасывался на другом устройстве
    if step == "later":
        partner.kv_set(db, f"onboard:{uid}:later", "1" if data["done"] else "0")
        return web.json_response({"later": data["done"]})
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



def report_timeline(chart, since, until, state=None, rows=(), retained_from=None):
    """Display points only: preserve empty days without adding deals or estimated balances."""
    end = min(until.date(), trades.clock().date())
    start = since.date()
    if since.year == 2000:  # all time: start at the first available observation
        start = min((date.fromisoformat(day) for day in chart), default=end)
    if start > end:
        return [{"day": start.isoformat(), "value": 0, "balance": None}]
    # ponytail: daily UI series is capped at 10,000 days; longer ranges need aggregation.
    if (end - start).days > 10000:
        return [{"day": d.isoformat(), "value": chart.get(d.isoformat(), 0), "balance": None}
                for d in sorted({start, end, *(date.fromisoformat(k) for k in chart)})]
    synced = None
    if state and state.get("synced"):
        synced = datetime.fromisoformat(state["synced"]).replace(tzinfo=None) + timedelta(hours=trades.TZ_HOURS)
    history_from = datetime.fromisoformat(os.getenv("HISTORY_FROM", "2026-06-01")).date()
    if retained_from:
        history_from = max(history_from, retained_from)
    after = {}
    for row in rows:
        if synced and row["time"] <= synced:
            day = row["time"].date()
            after[day] = after.get(day, 0) + row["net"]
    balance = state.get("balance") if synced else None
    result = []
    cursor = synced.date() if synced else end
    # Walk back through retained raw operations, not net-income/fee estimates.
    while cursor > end:
        balance -= after.get(cursor, 0)
        cursor -= timedelta(days=1)
    day = end
    while day >= start:
        known = synced and history_from <= day <= synced.date() and balance is not None and balance >= 0
        key = day.isoformat()
        result.append({"day": key, "value": chart.get(key, 0), "balance": round(balance, 2) if known else None})
        if balance is not None:
            balance -= after.get(day, 0)
        day -= timedelta(days=1)
    return list(reversed(result))


def retained_history_start(db, login):
    month = db.execute("SELECT MAX(month) FROM months WHERE login=?", (login,)).fetchone()[0]
    if not month:
        return None
    year, index = map(int, month.split("-"))
    return date(year + (index == 12), index % 12 + 1, 1)


async def overview_report(request):
    uid, _ = authorize(request)
    title, since, until = report_period(request.query)
    db = request.app["trades"]
    personal = accounts.dedup(accounts.load(uid))
    currencies = {((store.get_state(db, a["login"]) or {}).get("currency") or "USD").upper()
                  for a in personal}
    unsupported = currencies - {"USD", "RUB", "BYN"}
    if unsupported:
        raise web.HTTPServiceUnavailable(text="В сводке поддерживаются только USD, RUB и BYN")
    byn_per_unit = None
    if currencies - {"USD"}:
        try:
            byn_per_unit = (await fx_snapshot(request.app["db"]))["rates"]
        except fx.FxUnavailable as exc:
            raise web.HTTPServiceUnavailable(text="Курс валют временно недоступен") from exc
    chart = {}
    total = count = account_count = archived_count = pending_count = 0
    current_capital = weighted = 0
    timelines = []
    for acc in personal:
        state = store.get_state(db, acc["login"])
        if not state:
            pending_count += 1
            continue
        factor = usd_factor(state["currency"], byn_per_unit) if byn_per_unit else (
            1 if state["currency"].upper() == "USD" else None)
        if factor is None:
            continue
        trades.use(current_account_settings(acc))
        cap = trades.capital()
        current_capital += max(0, cap) * factor
        rows = trades.fetch(since, until)
        archived = report_archive(since, until)
        summary = trades.summary(rows)
        # процент «Обзора» — средний по счетам, взвешенный капиталом, той же
        # мерой, что карточки (как в сводке бота), а не сумма ÷ общий капитал
        all_rows = trades.fetch(datetime(2000, 1, 1), logic.utcnow() + timedelta(days=1))
        timelines.append((report_timeline({r["time"].date().isoformat(): 0 for r in all_rows}, since, until, state, all_rows, retained_history_start(db, acc["login"])), factor))
        weighted += max(0, cap) * factor * trades.period_growth(rows, all_rows, archived, cap)
        total += trades.net_of_fee(trades.mine(
            summary["total"] + sum((m["gross"] or 0) + (m["platform"] or 0) for m in archived))) * factor
        count += summary["count"] + sum(m["trades"] or 0 for m in archived)
        account_count += 1
        archived_count += len(archived)
        for row in rows:
            if row["is_closing"] or (row["is_balance"] and not trades.is_transfer(row)
                                      and not trades.is_perf_fee(row)):
                day = row["time"].strftime("%Y-%m-%d")
                chart[day] = chart.get(day, 0) + trades.net_of_fee(trades.mine(row["net"])) * factor
        for month in archived:
            last_day = calendar.monthrange(*map(int, month["month"].split("-")))[1]
            day = f'{month["month"]}-{last_day:02d}'
            chart[day] = chart.get(day, 0) + trades.net_of_fee(trades.mine(
                (month["gross"] or 0) + (month["platform"] or 0))) * factor
    timeline = report_timeline(chart, since, until)
    per_account = [(dict((p["day"], p["balance"]) for p in points), factor) for points, factor in timelines]
    for point in timeline:
        balances = [days.get(point["day"]) for days, _ in per_account]
        if balances and not pending_count and all(b is not None for b in balances):
            point["balance"] = round(sum(b * factor for b, (_, factor) in zip(balances, per_account)), 2)
    return web.json_response({"timeline": timeline, "title": title, "summary": {"count": count, "net_income": total,
        "pct_capital": round(weighted / current_capital, 3) if current_capital > 0 else None},
        "currency": "USD", "chart": [{"day": k, "value": v} for k, v in sorted(chart.items())],
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
    acc = current_account_settings(owned(uid, request.match_info["login"]))
    account_state = store.get_state(request.app["trades"], acc["login"])
    if not account_state:
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
    timeline = report_timeline(chart, since, until, account_state, all_rows,
                               retained_history_start(request.app["trades"], acc["login"]))
    return web.json_response({**extra, "timeline": timeline, "title": title, "summary": summary, "currency": trades.currency(),
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
    acc = current_account_settings(owned(uid, request.match_info["login"]))
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
    открытую позицию той же стороны: и у входа, и у выхода side — направление
    позиции (см. trades._position_side). Вход до начала периода — пара без
    входа, только выход.
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
        waiting = queue.get(r["side"], [])
        if entry is not None and entry in waiting:
            waiting.remove(entry)
        elif entry is None and waiting:
            entry = waiting.pop(0)
        pairs.append({"side": entry["side"] if entry else r["side"],
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
    if method == "DELETE":
        accounts.remove(acc["name"], uid)
    else:
        if set(data) - {"name", "enabled", "notify", "base"}:
            raise ValueError("unknown field")
        if "name" in data:
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
            if acc.get("shared_by"):
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
                            for a in accounts.load(guest)]}
              for guest, name in logic.guests_of(db, uid)]
    username = os.getenv("TELEGRAM_BOT_USERNAME", "tagmarketgold_bot")
    partner_url = logic.partner_link(db, uid)
    link = logic.invite_link(username, logic.invite_personal(db, uid)) if partner_url else None
    return web.json_response({"guests": guests, "link": link, "partner_url": partner_url,
                              "shareable": [{"login": a["login"], "name": a.get("strategy") or a["name"],
                                             "cabinet": a.get("cabinet")}
                                            for a in accounts.load(uid)
                                            if not a.get("shared_by")]})


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
            if acc.get("shared_by"):
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
        if acc.get("shared_by"):
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
            body = sanitize_broadcast_html(data.get("text", ""), limit=16384)
        except ValueError:
            raise web.HTTPBadRequest(text="Текст слишком длинный")
        if telegram_length(plain_report(body)) > 4096:
            raise web.HTTPBadRequest(text="Текст превышает лимит Telegram")
        if not body and not media_path:
            raise web.HTTPBadRequest(text="Добавьте текст или медиафайл")
        # кнопка под сообщением: название любое, ссылка всегда на мини-приложение
        button_text = str(data.get("button_text", "") or "").strip()
        if len(button_text) > 40:
            raise web.HTTPBadRequest(text="Название кнопки — до 40 символов")
        app_url = os.getenv("MINI_APP_URL", "").strip()
        if button_text and not app_url:
            raise web.HTTPBadRequest(text="Ссылка на мини-приложение не настроена (MINI_APP_URL)")
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=button_text, web_app=WebAppInfo(url=app_url))]]) if button_text else None
        target = str(data.get("target", "all"))
        db = request.app["db"]
        known = {u for u, _ in logic.all_guests(db)}
        if target != "all" and target not in known:
            raise web.HTTPNotFound(text="Получатель не найден")
        if not known:
            raise web.HTTPBadRequest(text="Пока нет получателей")
        key = bounded_text(data, "request_id", 64, True)
        fingerprint = hashlib.sha256(json.dumps(
            [target, body, media_kind, media_digest, button_text], ensure_ascii=False).encode()).hexdigest()
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
                if status in ("sent", "unreachable"):
                    continue
                try:
                    if status != "media_sent":
                        # кнопка — под последним сообщением: под файлом, если текст в его подписи
                        media_markup = markup if (caption is not None or not body) else None
                        if media_kind == "photo":
                            await sender.send_photo(recipient, FSInputFile(media_path), caption=caption,
                                                    parse_mode=ParseMode.HTML, reply_markup=media_markup)
                        elif media_kind == "video":
                            await sender.send_video(recipient, FSInputFile(media_path), caption=caption,
                                                    parse_mode=ParseMode.HTML, supports_streaming=True,
                                                    reply_markup=media_markup)
                        if media_kind:
                            campaign["recipients"][recipient] = "media_sent"
                            partner.kv_set(db, campaign_key, json.dumps(campaign))
                    if body and (not media_kind or caption is None):
                        await sender.send_message(recipient, body, parse_mode=ParseMode.HTML, reply_markup=markup)
                    campaign["recipients"][recipient] = "sent"
                    partner.kv_set(db, campaign_key, json.dumps(campaign))
                    try:
                        partner.record_notification(db, recipient, f"broadcast:{key}", "message",
                                                    "Сообщение Tag Markets",
                                                    plain_report(body) or ("Фото" if media_kind == "photo" else "Видео"))
                    except Exception:
                        # доставлено, а запись во «входящих» не удалась — получателю это не повод считаться недоставленным
                        logging.exception("broadcast delivered but inbox save failed for %s", recipient)
                except TelegramForbiddenError:
                    # человек заблокировал бота или удалил аккаунт: сколько ни повторяй, сообщение не дойдёт.
                    # Такого получателя не держим в «ожидает повторной отправки»
                    logging.warning("broadcast: %s недоступен (бот заблокирован или аккаунт удалён)", recipient)
                    campaign["recipients"][recipient] = "unreachable"
                    partner.kv_set(db, campaign_key, json.dumps(campaign))
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
        statuses = campaign["recipients"]
        result = {"sent": sum(v == "sent" for v in statuses.values()),
                  "failed": sum(v not in ("sent", "unreachable") for v in statuses.values()),
                  "unreachable": [{"id": r, "name": partner.kv_get(db, f"guest_name:{r}") or r}
                                  for r, v in statuses.items() if v == "unreachable"]}
        return web.json_response(result)
    finally:
        if media_path:
            media_path.unlink(missing_ok=True)


# картинки раздела «Частые вопросы» — скриншоты стратегий, лицензии и MT5
FAQ_IMAGES = ("faq-neo-card.jpg", "faq-neo-stats.jpg", "faq-sonic-card.jpg", "faq-sonic-stats.jpg", "faq-license.jpg", "faq-mt5.jpg", "faq-neo-myfxbook.jpg")


async def static(request):
    name = request.match_info.get("file", "index.html") or "index.html"
    if name not in ("index.html", "app.js", "style.css", "preview.json", "privacy.html", *FAQ_IMAGES):
        raise web.HTTPNotFound()
    response = web.FileResponse(STATIC / name)
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' https://telegram.org; "
        "style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "connect-src 'self'; base-uri 'none'; object-src 'none'")
    return response


async def app_redirect(request):
    raise web.HTTPFound("app/")


async def project_api(request):
    uid, _ = authorize(request)
    db = request.app["db"]
    project_id = request.match_info.get("project_id")
    account_id = request.match_info.get("account_id")
    data = await json_object(request) if request.method in {"POST", "PATCH"} else {}
    try:
        if request.path.endswith("/pause") and request.method == "POST":
            result = projects.set_paused(db, uid, project_id, data.get("paused"), account_id)
        elif request.path.endswith("/accounts/reorder") and request.method == "POST":
            result = projects.reorder_account(db, uid, project_id, data.get("account_id"), data.get("position"))
        elif "/accounts" in request.path:
            result = projects.account_change(db, uid, project_id, data, account_id,
                                             remove=request.method == "DELETE")
        elif request.method == "GET":
            result = projects.get(db, uid, project_id) if project_id else {"projects": projects.list_for(db, uid)}
        elif request.method == "DELETE":
            projects.delete(db, uid, project_id)
            result = {"ok": True}
        else:
            result = projects.save(db, uid, data, project_id)
    except LookupError as exc:
        raise web.HTTPNotFound(text=str(exc))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    return web.json_response(result, status=201 if request.method == "POST" and not request.path.endswith(("/accounts/reorder", "/pause")) else 200)


async def project_forecast(request):
    uid, _ = authorize(request)
    db = request.app["db"]
    ids = request.query.getall("id", [])
    if not ids and request.query.get("all", "1") != "0":
        ids = [p["id"] for p in projects.list_for(db, uid)]
    if len(ids) > 100:
        raise web.HTTPBadRequest(text="Можно выбрать до 100 проектов")
    try:
        results = [projects.forecast(db, uid, pid, request.query.get("until"), request.query.get("bonus", "1") != "0") for pid in ids]
    except LookupError as exc:
        raise web.HTTPNotFound(text=str(exc))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    return web.json_response({"projects": results})


async def tagmarket_forecast(request):
    """Статистический прогноз TagMarket по средней доходности собственных счетов."""
    uid, _ = authorize(request)
    try:
        target = date.fromisoformat(request.query.get("until", ""))
    except ValueError:
        raise web.HTTPBadRequest(text="Укажите корректную дату прогноза")
    start = projects.today()
    if target < start or target > start + timedelta(days=3660):
        raise web.HTTPBadRequest(text="Дата прогноза должна быть в пределах 10 лет")
    db = request.app["trades"]
    personal = [current_account_settings(a) for a in accounts.dedup(accounts.load(uid))]
    states = {a["login"]: store.get_state(db, a["login"]) for a in personal}
    currencies = {(s["currency"] or "USD").upper() for s in states.values() if s}
    byn_per_unit = None
    if currencies - {"USD"}:
        try:
            byn_per_unit = (await fx_snapshot(request.app["db"]))["rates"]
        except fx.FxUnavailable as exc:
            raise web.HTTPServiceUnavailable(text="Курс валют временно недоступен") from exc
    today = trades.clock().date()
    per_account = []
    for acc in personal:
        state = states[acc["login"]]
        if not state:
            continue
        factor = usd_factor(state["currency"], byn_per_unit) if byn_per_unit else (
            1 if state["currency"].upper() == "USD" else None)
        if factor is None:
            continue
        trades.use(acc)
        rows = trades.fetch(datetime(2000, 1, 1), logic.utcnow() + timedelta(days=1))
        results = {}
        for row in rows:
            if row["is_closing"] and row["time"].date() < today:
                day = row["time"].date()
                results[day] = results.get(day, 0) + trades.net_of_fee(trades.mine(row["net"]))
        per_account.append((acc, rows, results, factor,
                            min((r["time"] for r in rows), default=None)))
    # торговый день — день, когда хотя бы на одном счёте закрывались сделки
    candidates = sorted({day for _, _, results, _, _ in per_account for day in results})[-90:]
    series = {day: {"day": day.isoformat(), "net": 0.0, "base": 0.0} for day in candidates}
    for acc, rows, results, factor, first in per_account:
        trades.use(acc)     # плечо и доля счёта — глобальное состояние trades
        current = trades.capital()
        for day in candidates:
            if first is None or first > datetime.combine(day, datetime.max.time()):
                continue    # счёта ещё не было — его капитал в базу дня не входит
            capital_then = trades.capital_at(datetime.combine(day, datetime.min.time()), rows, current)
            if capital_then > 0:
                series[day]["net"] += results.get(day, 0) * factor
                series[day]["base"] += capital_then * factor
    return web.json_response(projects.tag_forecast(list(series.values()), start, target))


def _section_call(fn):
    """Ошибки разделов → HTTP: чужая или удалённая запись — 404, неверные данные — 400."""
    try:
        return fn()
    except LookupError as exc:
        raise web.HTTPNotFound(text=str(exc))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))


async def activity_api(request):
    """Активности: GET — сводка за ?days=, POST — запись, DELETE /{id}, PUT /goals."""
    uid, _ = authorize(request)
    db = request.app["db"]
    entry_id = request.match_info.get("entry_id")
    if request.method == "GET":
        raw = request.query.get("days", "30")
        days = int(raw) if raw.isdigit() else -1
        result = _section_call(lambda: activity.overview(db, uid, days))
        return web.json_response({**result, "sync": activity.sync_status(db, uid)})
    if request.method == "DELETE":
        _section_call(lambda: activity.delete(db, uid, entry_id))
        return web.json_response({"ok": True})
    data = await json_object(request)
    if request.method == "PATCH":
        return web.json_response(_section_call(lambda: activity.replace(db, uid, entry_id, data)))
    if request.path.endswith("/goals"):
        return web.json_response({"goals": _section_call(lambda: activity.set_goals(db, uid, data))})
    return web.json_response(_section_call(lambda: activity.add(db, uid, data)), status=201)


def sync_url(request):
    """Адрес для автоматизации на телефоне — тот же, по которому открыт Mini App."""
    base = os.getenv("MINI_APP_URL", "").strip()
    if base.startswith("https://"):
        return base.rstrip("/").rsplit("/app", 1)[0] + "/api/activity/sync"
    return str(request.url.with_path("/api/activity/sync").with_query(None))


async def activity_sync(request):
    """Приём показателей с телефона: без Telegram, по личному ключу.

    Ключ — заголовок «Authorization: Bearer …», «X-Sync-Key» или параметр
    ?key=… (не во всех автоматизаторах удобно задавать заголовки). Тело — JSON
    или обычная форма: «Команды» iOS умеют и то и другое.
    """
    auth = request.headers.get("Authorization", "")
    key = (auth[7:].strip() if auth.lower().startswith("bearer ") else
           request.headers.get("X-Sync-Key") or request.query.get("key"))
    db = request.app["db"]
    # приложение для Android шлёт шаги из Health Connect со своим токеном устройства
    owner = devices.owner_for(db, key) or activity.owner_for(db, key)
    if owner is None or partner.kv_get(db, f"left:{owner}") == "1":
        raise web.HTTPUnauthorized(text="Ключ синхронизации не подходит — создайте новый в приложении")
    now = time.monotonic()
    start, count = _rates.pop(f"sync:{owner}", (now, 0))
    if now - start >= 60:
        start, count = now, 0
    _rates[f"sync:{owner}"] = (start, count + 1)
    if count >= 30:
        raise web.HTTPTooManyRequests(text="Слишком часто — достаточно раза в несколько минут")
    if request.content_type in ("application/x-www-form-urlencoded", "multipart/form-data"):
        payload = {k: v for k, v in (await request.post()).items() if isinstance(v, str)}
    else:
        payload = await request.json()
    result = _section_call(lambda: activity.ingest(db, owner, payload))
    live.bump(db, owner, "activity")        # шаги с телефона — сразу на открытом экране
    return web.json_response(result)


async def activity_sync_key(request):
    """Ключ синхронизации владельца: GET — состояние, POST — новый ключ, DELETE — отключить."""
    uid, _ = authorize(request)
    db = request.app["db"]
    if request.method == "POST":
        key = activity.create_token(db, uid)
        return web.json_response({**activity.sync_status(db, uid), "key": key, "url": sync_url(request)})
    if request.method == "DELETE":
        activity.revoke_token(db, uid)
    return web.json_response({**activity.sync_status(db, uid), "url": sync_url(request)})


async def spend_api(request):
    """Траты: GET — список и сводка, POST — новая, PATCH/DELETE /{id}."""
    uid, _ = authorize(request)
    db = request.app["db"]
    item_id, method = request.match_info.get("item_id"), request.method
    if method == "GET":
        return web.json_response(_section_call(lambda: spend.overview(db, uid, span=request.query.get("span", "month"))))
    if method == "DELETE":
        _section_call(lambda: spend.delete(db, uid, item_id))
        return web.json_response({"ok": True})
    data = await json_object(request)
    return web.json_response(_section_call(lambda: spend.save(db, uid, data, item_id)),
                             status=201 if method == "POST" else 200)


LIVE_WAIT = 25          # секунд держим запрос /api/live, если ничего не меняется


async def live_api(request):
    """Живая синхронизация: ?rev= — последний известный номер. Ответ — как только
    данные изменились (или через LIVE_WAIT секунд с тем же номером)."""
    uid, _ = authorize(request)
    db = request.app["db"]
    try:
        since = int(request.query.get("rev", "-1"))
    except ValueError:
        raise web.HTTPBadRequest(text="rev")
    latest, changed = live.state(db, uid, max(since, 0))
    deadline = time.monotonic() + LIVE_WAIT
    while since >= 0 and latest <= since and time.monotonic() < deadline:
        await asyncio.sleep(1)
        latest, changed = live.state(db, uid, since)
    return web.json_response({"rev": max(latest, since, 0), "changed": changed if since >= 0 and latest > since else []})


@web.middleware
async def live_marks(request, handler):
    """Успешное изменение через API — отметка для живой синхронизации других копий приложения."""
    response = await handler(request)
    if (request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/api/")
            and request.get("uid") and getattr(response, "status", 500) < 400):
        live.bump(request.app["db"], request["uid"], live.section_for(request.path))
    return response


async def device_pair(request):
    """Приложение для Android: код из бота (/app) → токен устройства. Без Telegram, с ограничением частоты."""
    ip = request.remote or "?"
    now = time.monotonic()
    start, count = _rates.pop(f"pair:{ip}", (now, 0))
    if now - start >= 60:
        start, count = now, 0
    _rates[f"pair:{ip}"] = (start, count + 1)
    if count >= 10:
        raise web.HTTPTooManyRequests(text="Слишком много попыток. Подождите минуту")
    data = await json_object(request)
    db = request.app["db"]
    result = _section_call(lambda: devices.pair(db, data.get("code"), data.get("name")))
    if partner.kv_get(db, f"left:{result['owner']}") == "1":
        devices.revoke(db, result["owner"])
        raise web.HTTPForbidden(text="Доступ закрыт. Запросите приглашение в боте")
    return web.json_response({"token": result["token"], "device_id": result["device_id"]}, status=201)


async def device_logout(request):
    """Выход из приложения для Android: отзываем токен, которым пришёл запрос."""
    token = device_token(request)
    if not token:
        raise web.HTTPBadRequest(text="Выход — только из приложения для Android")
    devices.revoke_token(request.app["db"], token)
    return web.json_response({"ok": True})


async def device_push(request):
    """Приложение для Android присылает FCM-токен — сюда сервер шлёт мгновенные уведомления."""
    token = device_token(request)
    if not token:
        raise web.HTTPBadRequest(text="Только из приложения для Android")
    authorize(request)                      # устройство должно быть привязано
    data = await json_object(request)
    if not _section_call(lambda: push.set_token(request.app["db"], token, data.get("token"))):
        raise web.HTTPUnauthorized(text="Устройство отвязано")
    return web.json_response({"ok": True, "enabled": push.account() is not None})


async def devices_api(request):
    """Привязанные устройства: GET — список, POST /code — код для входа, DELETE /{id} — отвязать."""
    uid, _ = authorize(request)
    db = request.app["db"]
    if request.method == "DELETE":
        _section_call(lambda: devices.revoke(db, uid, request.match_info["device_id"]))
        return web.json_response({"ok": True})
    if request.path.endswith("/code"):
        return web.json_response({"code": devices.new_code(db, uid), "minutes": int(devices.CODE_TTL.total_seconds() // 60)},
                                 status=201)
    return web.json_response({"devices": devices.devices(db, uid)})


async def goals_api(request):
    """Цели накоплений: GET — список, POST — новая, PATCH/DELETE /{id}, POST /{id}/add — отложить или забрать."""
    uid, _ = authorize(request)
    db = request.app["db"]
    goal_id, method = request.match_info.get("goal_id"), request.method
    if method == "GET":
        return web.json_response(goals.overview(db, uid))
    if method == "DELETE":
        _section_call(lambda: goals.delete(db, uid, goal_id))
        return web.json_response({"ok": True})
    data = await json_object(request)
    if request.path.endswith("/add"):
        return web.json_response(_section_call(lambda: goals.contribute(db, uid, goal_id, data.get("amount"))))
    return web.json_response(_section_call(lambda: goals.save(db, uid, data, goal_id)),
                             status=201 if method == "POST" else 200)


async def friends_api(request):
    """Друзья: GET — круг и общие траты с долгами; POST /split — запись, DELETE /split/{id}."""
    uid, _ = authorize(request)
    db = request.app["db"]
    info, method, path = request.match_info, request.method, request.path
    if path == "/api/friends":
        return web.json_response(friends.overview(db, uid))
    if method == "DELETE":
        people = friends.participants(db, info["split_id"])
        _section_call(lambda: friends.delete_split(db, uid, info["split_id"]))
    else:
        data = await json_object(request)
        people = friends.participants(db, _section_call(lambda: friends.add_split(db, uid, data)))
    live.bump(db, people, "friends")        # долг меняется и у друзей — у них экран обновится сам
    return web.json_response(friends.overview(db, uid), status=201 if method == "POST" else 200)


async def income_api(request):
    """Зарплата: GET — зачисления и сводка, POST — новое, PATCH/DELETE /{id}."""
    uid, _ = authorize(request)
    db = request.app["db"]
    item_id, method = request.match_info.get("item_id"), request.method
    if method == "GET":
        income.credit_due(db, uid)
        return web.json_response(income.overview(db, uid))
    if method == "DELETE":
        _section_call(lambda: income.delete(db, uid, item_id))
        return web.json_response({"ok": True})
    data = await json_object(request)
    return web.json_response(_section_call(lambda: income.save(db, uid, data, item_id)),
                             status=201 if method == "POST" else 200)


async def banks_api(request):
    """Банки и счета: список, создание, правка, удаление, история и входящие сообщения."""
    uid, _ = authorize(request)
    db = request.app["db"]
    info, method, path = request.match_info, request.method, request.path
    data = await json_object(request) if method in {"POST", "PATCH"} else {}
    if path == "/api/banks":
        if method == "GET":
            income.credit_due(db, uid)
            return web.json_response({**banks.overview(db, uid), "sync": activity.sync_status(db, uid),
                                      "sync_url": sync_url(request).replace("/activity/sync", "/banks/sync")})
        return web.json_response(_section_call(lambda: banks.save_account(db, uid, data)), status=201)
    if "/inbox/" in path:
        item_id = info["item_id"]
        if method == "DELETE":
            _section_call(lambda: banks.dismiss_inbox(db, uid, item_id))
            return web.json_response({"ok": True})
        return web.json_response(_section_call(lambda: banks.resolve_inbox(db, uid, item_id, data)))
    account_id = info["account_id"]
    if path.endswith("/ops"):
        return web.json_response({"operations": _section_call(lambda: banks.operations(db, uid, account_id))})
    if method == "DELETE":
        _section_call(lambda: banks.delete_account(db, uid, account_id))
        return web.json_response({"ok": True})
    if method == "GET":
        return web.json_response(_section_call(lambda: banks.account(db, uid, account_id)))
    return web.json_response(_section_call(lambda: banks.save_account(db, uid, data, account_id)))


async def banks_sync(request):
    """Пересылка SMS/пуша банка с телефона: тот же личный ключ, что у шагов."""
    key = request.query.get("key") or request.headers.get("X-Sync-Key") or ""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        key = auth[7:].strip()
    db = request.app["db"]
    owner = activity.owner_for(db, key)
    if owner is None or partner.kv_get(db, f"left:{owner}") == "1":
        raise web.HTTPUnauthorized(text="Ключ синхронизации не подходит — создайте новый в приложении")
    now = time.monotonic()
    start, count = _rates.pop(f"bank:{owner}", (now, 0))
    if now - start >= 60:
        start, count = now, 0
    _rates[f"bank:{owner}"] = (start, count + 1)
    if count >= 60:
        raise web.HTTPTooManyRequests(text="Слишком часто")
    if request.content_type in ("application/x-www-form-urlencoded", "multipart/form-data"):
        body = {k: v for k, v in (await request.post()).items() if isinstance(v, str)}
    else:
        body = await request.json()
    if isinstance(body, str):
        body = {"text": body}
    if not isinstance(body, dict):
        raise ValueError("Ожидается JSON-объект")
    message = next((body[k] for k in ("text", "message", "sms", "body", "content") if isinstance(body.get(k), str)), None)
    result = _section_call(lambda: banks.ingest(db, owner, message))
    live.bump(db, owner, "banks")           # SMS банка — баланс обновляется на открытом экране
    return web.json_response(result)


async def lists_api(request):
    """Задачи, заметки и календарь — один обработчик на все пути раздела."""
    uid, _ = authorize(request)
    db = request.app["db"]
    info, method, path = request.match_info, request.method, request.path
    data = await json_object(request) if method in {"POST", "PATCH"} else {}
    if path == "/api/lists":
        return web.json_response({"notes": lists.notes(db, uid),
                                  "tasks": lists.tasks(db, uid), "areas": lists.AREAS,
                                  "upcoming": lists.upcoming(db, uid)})
    if path.startswith("/api/tasks"):
        task_id = info.get("task_id")
        if method == "DELETE":
            _section_call(lambda: lists.delete_task(db, uid, task_id))
            return web.json_response({"ok": True})
        result = _section_call(lambda: lists.save_task(db, uid, data, task_id))
    elif path == "/api/notes/import":
        return web.json_response(_section_call(lambda: lists.import_notes(db, uid, data.get("notes"))))
    elif path.startswith("/api/notes"):
        note_id = info.get("note_id")
        if method == "DELETE":
            _section_call(lambda: lists.delete_note(db, uid, note_id))
            return web.json_response({"ok": True})
        result = _section_call(lambda: lists.save_note(db, uid, data, note_id))
    else:
        event_id = info.get("event_id")
        if method == "GET":
            return web.json_response(_section_call(lambda: lists.events_between(
                db, uid, request.query.get("from"), request.query.get("to"))))
        if method == "DELETE":
            _section_call(lambda: lists.delete_event(db, uid, event_id))
            return web.json_response({"ok": True})
        result = _section_call(lambda: lists.save_event(db, uid, data, event_id))
    return web.json_response(result, status=201 if method == "POST" else 200)


# Что показывать в Platformer — у каждого своё и одинаково на всех устройствах:
# карточки главной и их порядок, быстрые кнопки, показатели «Активностей»
STATION_CHOICES = {
    "home": ("circle", "finance", "activity", "tasks", "events", "notes"),
    "quick": ("task", "event", "note"),
    "metrics": ("steps",),      # шаги — только присланные телефоном
}
STATION_DEFAULTS = {"home": list(STATION_CHOICES["home"]),
                    "quick": list(STATION_CHOICES["quick"]),
                    "metrics": list(STATION_CHOICES["metrics"])}


_tag_cache = OrderedDict()      # uid -> (month, today, currency): TagMarket для круга жизни между обновлениями


def insights_for(db, uid, display="USD", rates=None, tag=None):
    """Круг жизни пользователя по его данным; любой сбой не должен ломать приложение."""
    def conv(value, cur):
        if value is None:
            return None
        if cur == display:
            return float(value)
        if rates and rates.get(cur) and rates.get(display):
            return float(value) * rates[cur] / rates[display]
        return None
    try:
        projects = []
        for p in projects_list(db, uid):
            daily = p["daily_income"] if not p["calculation_limited"] else None
            projects.append({"name": p["name"], "paused": p["paused"], "income_starts": p["income_starts"],
                             "daily_income": conv(daily, p["currency"]) if daily is not None else None})
        if tag is not None:
            _tag_cache[str(uid)] = tag
            while len(_tag_cache) > 4096:
                _tag_cache.popitem(last=False)
        month, today_net, cur = _tag_cache.get(str(uid), (None, None, "USD"))
        tag_part = None if month is None else {"month": conv(month, cur) or 0, "today": conv(today_net, cur)}
        summary = activity.overview(db, uid, 30)
        sync = activity.sync_status(db, uid)
        sync["stale"] = bool(sync["connected"] and sync["last_sync"] and
                             datetime.now(timezone.utc) - datetime.fromisoformat(sync["last_sync"]) > timedelta(hours=36))
        now = lists.today()
        events = lists.events_between(db, uid, now.isoformat(), (now + timedelta(days=7)).isoformat())["events"]
        income.credit_due(db, uid, now)
        pay = income.overview(db, uid, now)
        salary = sum(conv(v, c) or 0 for c, v in pay["monthly"].items())
        paydays = [{**u, "converted": conv(u["amount"], u["currency"])} for u in pay["upcoming"] if u["in_days"] <= 3]
        bank_total = 0.0
        bank_known = False
        for a in banks.accounts(db, uid):
            if a["counted"]:
                value = conv(a["balance"], a["currency"])
                if value is not None:
                    bank_total += value
                    bank_known = True
        soon = [{**u, "converted": conv(u["amount"], u["currency"])} for u in spend.overview(db, uid, now)["upcoming"]
                if u["in_days"] <= 3]
        return insights.analyze({
            "finance": {"currency": display, "projects": projects, "tag": tag_part,
                        "banks": bank_total if bank_known else None, "charges": soon,
                        "salary": salary, "paydays": paydays},
            "activity": {**summary, "sync": sync}, "tasks": lists.tasks(db, uid), "events": events,
            "goals": goals.overview(db, uid, now)["items"], "friends": len(logic.guests_of(db, uid))},
            now, hour=int(datetime.now(timezone(timedelta(hours=3))).strftime("%H")))
    except Exception:
        logging.getLogger("miniapp").exception("insights failed")
        return None


def projects_list(db, uid):
    return projects.list_for(db, uid)


def station_prefs(db, uid):
    try:
        saved = json.loads(partner.kv_get(db, f"station_prefs:{uid}") or "{}")
    except (TypeError, ValueError):
        saved = {}
    out = {}
    for key, allowed in STATION_CHOICES.items():
        value = saved.get(key) if isinstance(saved, dict) else None
        if key == "home" and isinstance(value, list):
            value = ["notes" if v == "wish" else v for v in value]     # вишлисты стали заметками
        out[key] = ([v for v in value if v in allowed] if isinstance(value, list)
                    else list(STATION_DEFAULTS[key]))
    return out


async def station_preferences(request):
    uid, _ = authorize(request)
    db = request.app["db"]
    if request.method == "GET":
        return web.json_response(station_prefs(db, uid))
    data = await json_object(request)
    if set(data) - set(STATION_CHOICES):
        raise ValueError("Неизвестная настройка")
    current = station_prefs(db, uid)
    for key, value in data.items():
        if (not isinstance(value, list) or len(value) != len(set(value))
                or any(v not in STATION_CHOICES[key] for v in value)):
            raise ValueError(f"Некорректный список: {key}")
        current[key] = value
    partner.kv_set(db, f"station_prefs:{uid}", json.dumps(current))
    return web.json_response(current)


async def insights_api(request):
    """Круг жизни без полной перезагрузки: после правки задач, активностей, проектов."""
    uid, _ = authorize(request)
    db = request.app["db"]
    display = partner.kv_get(db, f"display_currency:{uid}", "USD")
    rates = None
    if display != "USD":
        try:
            rates = (await fx_snapshot(db))["rates"]
        except fx.FxUnavailable:
            rates = None
    result = insights_for(db, uid, display, rates)
    if result is None:
        raise web.HTTPServiceUnavailable(text="Не удалось построить круг жизни")
    return web.json_response(result)


async def display_preference(request):
    uid, _ = authorize(request)
    key = f"display_currency:{uid}"
    if request.method == "GET":
        return web.json_response({"currency": partner.kv_get(request.app["db"], key, "USD")})
    data = await json_object(request)
    currency = data.get("currency")
    if currency not in {"USD", "BYN", "RUB"}:
        raise web.HTTPBadRequest(text="Выберите USD, BYN или RUB")
    partner.kv_set(request.app["db"], key, currency)
    return web.json_response({"currency": currency})


def setup(app):
    global _state_db
    _state_db = app["db"]
    projects.setup(app["db"])
    activity.setup(app["db"])
    banks.setup(app["db"])
    lists.setup(app["db"])
    spend.setup(app["db"])
    income.setup(app["db"])
    goals.setup(app["db"])
    devices.setup(app["db"])
    push.setup(app["db"])
    friends.setup(app["db"])
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
    app.middlewares.append(live_marks)
    app.on_startup.append(push.start)
    app.on_cleanup.append(push.stop)
    app.router.add_get("/app", app_redirect)
    app.router.add_get("/app/", static)
    app.router.add_get("/app/{file}", static)
    app.router.add_get("/api/bootstrap", bootstrap)
    app.router.add_get("/api/projects", project_api)
    app.router.add_get("/api/projects/forecast", project_forecast)
    app.router.add_get("/api/tagmarket/forecast", tagmarket_forecast)
    app.router.add_get("/api/preferences/display-currency", display_preference)
    app.router.add_put("/api/preferences/display-currency", display_preference)
    app.router.add_post("/api/projects", project_api)
    app.router.add_get("/api/projects/{project_id}", project_api)
    app.router.add_patch("/api/projects/{project_id}", project_api)
    app.router.add_delete("/api/projects/{project_id}", project_api)
    app.router.add_post("/api/projects/{project_id}/pause", project_api)
    app.router.add_post("/api/projects/{project_id}/accounts/{account_id}/pause", project_api)
    app.router.add_post("/api/projects/{project_id}/accounts/reorder", project_api)
    app.router.add_post("/api/projects/{project_id}/accounts", project_api)
    app.router.add_patch("/api/projects/{project_id}/accounts/{account_id}", project_api)
    app.router.add_delete("/api/projects/{project_id}/accounts/{account_id}", project_api)
    app.router.add_post("/api/activity/sync", activity_sync)
    app.router.add_get("/api/activity/sync/key", activity_sync_key)
    app.router.add_post("/api/activity/sync/key", activity_sync_key)
    app.router.add_delete("/api/activity/sync/key", activity_sync_key)
    app.router.add_get("/api/live", live_api)
    app.router.add_post("/api/device/pair", device_pair)
    app.router.add_post("/api/device/logout", device_logout)
    app.router.add_post("/api/device/push", device_push)
    app.router.add_get("/api/devices", devices_api)
    app.router.add_post("/api/devices/code", devices_api)
    app.router.add_delete("/api/devices/{device_id}", devices_api)
    app.router.add_get("/api/goals", goals_api)
    app.router.add_post("/api/goals", goals_api)
    app.router.add_patch("/api/goals/{goal_id}", goals_api)
    app.router.add_delete("/api/goals/{goal_id}", goals_api)
    app.router.add_post("/api/goals/{goal_id}/add", goals_api)
    app.router.add_get("/api/friends", friends_api)
    app.router.add_post("/api/friends/split", friends_api)
    app.router.add_delete("/api/friends/split/{split_id}", friends_api)
    app.router.add_get("/api/income", income_api)
    app.router.add_post("/api/income", income_api)
    app.router.add_patch("/api/income/{item_id}", income_api)
    app.router.add_delete("/api/income/{item_id}", income_api)
    app.router.add_get("/api/spend", spend_api)
    app.router.add_post("/api/spend", spend_api)
    app.router.add_patch("/api/spend/{item_id}", spend_api)
    app.router.add_delete("/api/spend/{item_id}", spend_api)
    app.router.add_post("/api/banks/sync", banks_sync)
    app.router.add_get("/api/banks", banks_api)
    app.router.add_post("/api/banks", banks_api)
    app.router.add_post("/api/banks/inbox/{item_id}", banks_api)
    app.router.add_delete("/api/banks/inbox/{item_id}", banks_api)
    app.router.add_get("/api/banks/{account_id}", banks_api)
    app.router.add_patch("/api/banks/{account_id}", banks_api)
    app.router.add_delete("/api/banks/{account_id}", banks_api)
    app.router.add_get("/api/banks/{account_id}/ops", banks_api)
    app.router.add_get("/api/insights", insights_api)
    app.router.add_get("/api/activity", activity_api)
    app.router.add_post("/api/activity", activity_api)
    app.router.add_put("/api/activity/goals", activity_api)
    app.router.add_delete("/api/activity/{entry_id}", activity_api)
    app.router.add_patch("/api/activity/{entry_id}", activity_api)
    app.router.add_get("/api/preferences/station", station_preferences)
    app.router.add_put("/api/preferences/station", station_preferences)
    app.router.add_get("/api/lists", lists_api)
    app.router.add_post("/api/tasks", lists_api)
    app.router.add_patch("/api/tasks/{task_id}", lists_api)
    app.router.add_delete("/api/tasks/{task_id}", lists_api)
    app.router.add_post("/api/notes", lists_api)
    app.router.add_post("/api/notes/import", lists_api)
    app.router.add_patch("/api/notes/{note_id}", lists_api)
    app.router.add_delete("/api/notes/{note_id}", lists_api)
    app.router.add_get("/api/events", lists_api)
    app.router.add_post("/api/events", lists_api)
    app.router.add_patch("/api/events/{event_id}", lists_api)
    app.router.add_delete("/api/events/{event_id}", lists_api)
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
