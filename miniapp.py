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
import tempfile
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl
from account_lock import locked

from aiohttp import web
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile

os.environ["TRADES_SOURCE"] = "store"
import accounts
import bot as logic
import partner
import store
import trades

STATIC = Path(__file__).parent / "web"
MAX_AUTH_AGE = 86400
_rates = OrderedDict()


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
    except (ValueError, TypeError, KeyError) as exc:
        if "/api/" not in request.path:
            raise
        response = web.json_response({"error": "Некорректные данные запроса"}, status=400)
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


def owned(uid, login):
    acc = next((a for a in accounts.load(uid) if int(a["login"]) == int(login)), None)
    if not acc:
        raise web.HTTPNotFound(text="Счёт не найден")
    return acc


def public_account(acc, db):
    result = {k: acc.get(k) for k in ("login", "name", "strategy", "cabinet", "holder",
              "server", "enabled", "notify", "demo", "base", "base_at")}
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
    logic.ensure_demo_account(uid)
    items = [public_account(a, request.app["trades"]) for a in accounts.dedup(accounts.load(uid))]
    # Never combine currencies or include demonstration capital in personal totals.
    totals = {}
    for a in items:
        t = a["totals"]
        if a["demo"] or not a["enabled"] or not t:
            continue
        bucket = totals.setdefault(t["cur"], {"capital": 0, "pnl": 0, "month": 0, "kept": 0})
        for key, source in (("capital", "now"), ("pnl", "pnl"), ("month", "month_net"), ("kept", "kept")):
            bucket[key] += t[source]
    wallets = [{"cabinet": cab, "name": accounts.label(cab, uid),
                "amount": partner.wallet_balance(db, cab)[0]} for cab in accounts.cabinets(uid)
               if cab != accounts.NO_CABINET]
    return web.json_response({"user": {"id": user["id"], "name": user.get("first_name", "Инвестор")},
        "accounts": items, "totals": totals, "wallets": wallets,
        "founder": logic.is_founder(uid), "update_alerts": logic.update_alerts_on(db),
        "server_time": logic.utcnow().isoformat() + "Z", "refresh_seconds": 15})


async def report(request):
    uid, _ = authorize(request)
    acc = owned(uid, request.match_info["login"])
    if not store.get_state(request.app["trades"], acc["login"]):
        return web.json_response({"pending": True, "deals": [], "months": [], "chart": []})
    trades.use(acc)
    period = request.query.get("period", "month")
    if period == "custom":
        since = datetime.fromisoformat(request.query["from"])
        until = datetime.fromisoformat(request.query["to"]) + timedelta(days=1) - timedelta(microseconds=1)
        if since.tzinfo or until.tzinfo or since > until:
            raise ValueError("invalid period")
        title = "Выбранный период"
    else:
        if period not in ("today", "yesterday", "week", "lastweek", "month", "lastmonth", "all"):
            raise ValueError("invalid period")
        title, since, until, _ = logic.period(period)
    rows = trades.fetch(since, until)
    summary = trades.summary(rows)
    archived = trades.archive(since, until)
    partial_archive = False
    for month in archived:
        start = datetime.fromisoformat(month["month"] + "-01")
        end = start.replace(day=calendar.monthrange(start.year, start.month)[1],
                            hour=23, minute=59, second=59, microsecond=999999)
        if start < since or end > until:
            partial_archive = True
    # A monthly rollup cannot answer an exact partial-month query.
    if partial_archive:
        raise web.HTTPUnprocessableEntity(text="Детали этого периода уже свёрнуты. Выберите весь месяц или историю по месяцам")
    total = summary["total"] + sum(m["gross"] + m["platform"] for m in archived)
    summary["net_income"] = trades.net_of_fee(trades.mine(total))
    summary["count"] += sum(m["trades"] for m in archived)
    summary["wins"] += sum(m["wins"] for m in archived)
    chart = {}
    for row in rows:
        if row["is_closing"]:
            day = row["time"].strftime("%Y-%m-%d")
            chart[day] = chart.get(day, 0) + trades.net_of_fee(trades.mine(row["net"]))
    for month in archived:
        last_day = calendar.monthrange(*map(int, month["month"].split("-")))[1]
        day = f'{month["month"]}-{last_day:02d}'
        chart[day] = chart.get(day, 0) + trades.net_of_fee(trades.mine(month["gross"] + month["platform"]))
    offset = max(0, int(request.query.get("offset", 0)))
    kind = request.query.get("kind", "trades")
    filtered = [r for r in rows if r["is_balance"]] if kind == "moves" else [r for r in rows if r["is_closing"]]
    filtered.sort(key=lambda x: (x["time"], x["ticket"]), reverse=True)
    page = filtered[offset:offset + 50]
    flows = (trades.fetch(min(r["time"] for r in page), logic.utcnow() + timedelta(days=1))
             if page and kind != "moves" else [])
    deals = []
    for row in page:
        net_income = trades.own_amount(row) if row["is_balance"] else trades.net_of_fee(trades.mine(row["net"]))
        capital_then = trades.capital_at(row["time"], flows) if not row["is_balance"] else 0
        deals.append({**row, "time": row["time"].isoformat() + "Z", "net_income": net_income,
                      "pct_capital": round(net_income / capital_then * 100, 4) if capital_then > 0 else None})
    months = [{"month": m["month"], "count": m["trades"],
               "net": trades.net_of_fee(trades.mine(m["gross"] + m["platform"]))} for m in trades.monthly(120)]
    return web.json_response({"title": title, "summary": summary, "currency": trades.currency(),
        "deals": deals, "has_more": offset + 50 < len(filtered), "offset": offset,
        "chart": [{"day": k, "value": v} for k, v in sorted(chart.items())],
        "months": months, "archived": bool(archived),
        "report": plain_report(trades.fmt_report(title, rows, trades.currency(), since=since, until=until))})


def bounded_text(data, key, maximum=64, required=False):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(key)
    return value.strip()


async def add_account(request):
    uid, _ = authorize(request)
    data = await request.json()
    login = int(data["login"])
    if login <= 0 or login > 2**63 - 1:
        raise ValueError("login")
    # The terminal is the source of truth for broker server and account name.
    # Keep an optional deployment default only for the first login handshake;
    # agent_sync replaces it with the values reported by MT5.
    server = os.getenv("MT5_SERVER", "").strip()
    if not server:
        known = next((a.get("server") for a in accounts.load() if a.get("server")), "")
        server = known or "TMFinancials-Server"
    # Existing history must not become visible merely by guessing a login.
    with locked(accounts.PATH):
        if any(int(a["login"]) == login for a in accounts.load()):
            raise web.HTTPConflict(text="Счёт уже подключён. Попросите владельца прислать приглашение")
        # Also deny abandoned history until independent credentials verification exists.
        if store.get_state(request.app["trades"], login):
            raise web.HTTPConflict(text="Для повторного подключения этого счёта обратитесь к владельцу бота")
        accounts.add({"owner": uid, "login": login, "server": server,
            "name": bounded_text(data, "name", 48, True),
            "strategy": bounded_text(data, "name", 48, True),
            "holder": bounded_text(data, "holder", 96),
            "cabinet": bounded_text(data, "cabinet", 32),
            "password": bounded_text(data, "password", 128, True),
            "multiplier": logic.DEFAULT_MULTIPLIER})
    return web.json_response({"ok": True, "pending": True}, status=201)


async def change_account(request):
    uid, _ = authorize(request)
    data = await request.json() if request.method != "DELETE" else {}
    with locked(accounts.PATH):
        return _change_account(uid, request.match_info["login"], request.method, data)


def _change_account(uid, login, method, data):
    acc = owned(uid, login)
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
               "accounts": [{"login": a["login"], "name": a["name"]} for a in accounts.load(guest)
                            if a.get("shared_by") == uid or any(int(s["login"]) == int(a["login"]) for s in accounts.load(uid))]}
              for guest, name in logic.guests_of(db, uid)]
    username = os.getenv("TELEGRAM_BOT_USERNAME", "tagmarketgold_bot")
    invites = [{"token": token, "url": logic.invite_link(username, token),
                "created": inv.get("created"), "uses": inv.get("uses", 0),
                "logins": inv.get("logins", [])} for token, inv in logic.invite_list(db, uid)]
    return web.json_response({"guests": guests, "invites": invites})


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
    if request.method == "DELETE":
        token = request.match_info["token"]
        inv = logic.invite_get(db, token)
        if not inv or str(inv["owner"]) != uid:
            raise web.HTTPNotFound(text="Приглашение не найдено")
        inv["revoked"] = True
        logic.invite_save(db, token, inv)
        return web.json_response({"ok": True})
    data = await request.json()
    logins = list(dict.fromkeys(int(x) for x in data.get("logins", [])))
    for login in logins:
        acc = owned(uid, login)
        if acc.get("demo") or acc.get("shared_by"):
            raise web.HTTPForbidden(text="Делиться можно только собственными счетами")
    token = logic.invite_new(db, uid, logins)
    return web.json_response({"url": logic.invite_link(os.getenv("TELEGRAM_BOT_USERNAME", "tagmarketgold_bot"), token)})


async def guest_action(request):
    uid, _ = authorize(request)
    db = request.app["db"]
    guest = request.match_info["guest"]
    if str(partner.kv_get(db, f"guest_by:{guest}")) != uid or logic.is_founder(guest) or guest == uid:
        raise web.HTTPForbidden(text="Нет доступа к этому гостю")
    data = await request.json()
    if data.get("action") == "revoke":
        logic.wipe_user(db, guest)
    elif data.get("action") == "take":
        acc = owned(uid, data["login"])
        accounts.remove_login(acc["login"], guest)
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
    data = await request.json()
    kind = data.get("action")
    if kind == "restart":
        acc = owned(uid, data["login"])
        if acc.get("demo") or acc.get("shared_by"):
            raise web.HTTPForbidden(text="Общий терминал недоступен для управления гостю")
        store.set_command(request.app["trades"], acc["login"], "restart_terminal")
        partner.kv_set(db, f"restart_asked:{uid}", "1")
    elif kind == "wallet_reset":
        cabinet = str(data["cabinet"])
        if not any(a.get("cabinet") == cabinet and not a.get("shared_by") and not a.get("demo") for a in accounts.load(uid)):
            raise web.HTTPForbidden(text="Нет доступа к кошельку")
        partner.wallet_reset(db, cabinet)
    elif kind == "update_alerts" and logic.is_founder(uid):
        if type(data.get("value")) is not bool:
            raise ValueError("value")
        partner.kv_set(db, "update_alerts", "1" if data["value"] else "0")
    elif kind == "leave" and not logic.is_founder(uid):
        logic.wipe_user(db, uid)
    else:
        raise web.HTTPForbidden(text="Действие недоступно")
    return web.json_response({"ok": True})


async def admin(request):
    uid, _ = authorize(request)
    if not logic.is_founder(uid):
        raise web.HTTPForbidden(text="Только для основателя")
    db = request.app["db"]
    machines = [{"host": k.split(":", 1)[1], "seen": partner.kv_get(db, k),
                 "role": partner.kv_get(db, "machine_role:" + k.split(":", 1)[1])}
                for k in partner.kv_keys(db, "machine_seen:%")]
    return web.json_response({"machines": machines, "active": partner.kv_get(db, "active_machine"),
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
                formats = {"image/jpeg": (".jpg", "photo"),
                           "image/png": (".png", "photo"), "video/mp4": (".mp4", "video")}
                media_type = part.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if media_type not in formats:
                    raise web.HTTPBadRequest(text="Разрешены JPG, PNG и MP4")
                suffix, media_kind = formats[media_type]
                media_path = Path(tempfile.gettempdir()) / f"tagmarkets-broadcast-{uuid.uuid4().hex}{suffix}"
                size = 0
                header = b""
                with media_path.open("wb") as dst:
                    while chunk := await part.read_chunk(64 * 1024):
                        size += len(chunk)
                        if size > 20 * 1024 * 1024:
                            raise web.HTTPRequestEntityTooLarge(max_size=20 * 1024 * 1024,
                                                               actual_size=size)
                        if len(header) < 16:
                            header = (header + chunk)[:16]
                        dst.write(chunk)
                valid = (suffix == ".jpg" and header.startswith(b"\xff\xd8\xff") or
                         suffix == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n") or
                         suffix == ".mp4" and header[4:8] == b"ftyp")
                if not valid:
                    raise web.HTTPBadRequest(text="Формат файла не совпадает с содержимым")
        else:
            data = await request.json()
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
        key = bounded_text(data, "request_id", 64, True)
        # Persist before sending: repeated browser submissions must not duplicate a broadcast.
        db.execute("BEGIN IMMEDIATE")
        try:
            if partner.kv_get(db, f"mini_broadcast:{key}"):
                raise web.HTTPConflict(text="Эта рассылка уже была запущена. Повторная отправка отклонена")
            db.execute("INSERT INTO kv VALUES (?,?)", (f"mini_broadcast:{key}", "started"))
            db.commit()
        except Exception:
            db.rollback()
            raise
        ok = failed = 0
        session = logic.AiohttpSession(proxy=os.getenv("TELEGRAM_PROXY", "").split(",")[0].strip() or None)
        sender = logic.Bot(os.environ["TELEGRAM_BOT_TOKEN"], session=session)
        try:
            # Telegram limits media captions to 1024 characters. Longer messages
            # follow the attachment as a separate formatted message.
            caption = body if telegram_length(plain_report(body)) <= 1000 else None
            for recipient in sorted(known if target == "all" else {target}):
                try:
                    if media_kind == "photo":
                        await sender.send_photo(recipient, FSInputFile(media_path), caption=caption,
                                                parse_mode=ParseMode.HTML)
                    elif media_kind == "video":
                        await sender.send_video(recipient, FSInputFile(media_path), caption=caption,
                                                parse_mode=ParseMode.HTML, supports_streaming=True)
                    if body and (not media_kind or caption is None):
                        await sender.send_message(recipient, body, parse_mode=ParseMode.HTML)
                    ok += 1
                except Exception:
                    failed += 1
                    logging.exception("miniapp broadcast failed for recipient %s", recipient)
        finally:
            await session.close()
        result = {"sent": ok, "failed": failed}
        partner.kv_set(db, f"mini_broadcast:{key}", json.dumps(result))
        return web.json_response(result)
    finally:
        if media_path:
            media_path.unlink(missing_ok=True)


async def static(request):
    name = request.match_info.get("file", "index.html") or "index.html"
    if name not in ("index.html", "app.js", "style.css", "preview.json"):
        raise web.HTTPNotFound()
    response = web.FileResponse(STATIC / name)
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' https://telegram.org; "
        "style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; object-src 'none'")
    return response


async def app_redirect(request):
    raise web.HTTPFound("app/")


def setup(app):
    # Recover provenance for older shared copies before exposing mutation APIs.
    with locked(accounts.PATH):
        accs = accounts._read()
        changed = False
        for acc in accs:
            parent = partner.kv_get(app["db"], f"guest_by:{acc['owner']}")
            if not acc.get("shared_by") and parent and any(
                    str(src["owner"]) == str(parent) and src["login"] == acc["login"]
                    and src["server"] == acc["server"] for src in accs):
                acc["shared_by"] = str(parent)
                changed = True
        if changed:
            accounts.save(accs)
    app.middlewares.append(api_errors)
    app.router.add_get("/app", app_redirect)
    app.router.add_get("/app/", static)
    app.router.add_get("/app/{file}", static)
    app.router.add_get("/api/bootstrap", bootstrap)
    app.router.add_get("/api/accounts/{login}/report", report)
    app.router.add_post("/api/accounts", add_account)
    app.router.add_patch("/api/accounts/{login}", change_account)
    app.router.add_delete("/api/accounts/{login}", change_account)
    app.router.add_get("/api/people", people)
    app.router.add_get("/api/cabinets/{cabinet}/report", cabinet_report)
    app.router.add_post("/api/invites", invite)
    app.router.add_delete("/api/invites/{token}", invite)
    app.router.add_post("/api/guests/{guest}", guest_action)
    app.router.add_get("/api/guests/{guest}", guest_detail)
    app.router.add_post("/api/actions", action)
    app.router.add_get("/api/admin", admin)
    app.router.add_post("/api/broadcast", broadcast)
