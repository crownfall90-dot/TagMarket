"""Приём вебхуков Syntellicore: On Registration и On Deposit.

Мгновеннее, чем поллинг, и снимает нагрузку с лимита API (3 запроса/4 сек).
Дедуп общий с поллингом через ту же таблицу seen — что бы ни пришло первым,
второе не продублируется (см. row_id() в bot.py: tx_id/customer_no).

Запуск:  python webhook_server.py
Слушает 0.0.0.0:$WEBHOOK_PORT (по умолчанию 8443) на путях:
  GET /hook/registration?token=...&customer_no={{customer_no}}&fname={{fname}}...
  GET /hook/deposit?token=...&customer_no={{customer_no}}&amount={{amount}}...

В портале: Partner Area → My API → Webhooks → Add Webhook, событие и URL
берутся из webhook_urls() ниже (bot.py при старте печатает их в лог).
"""

import asyncio
import html
import logging
import math
import os
import re
import sqlite3
import secrets
from datetime import datetime, timezone

from aiohttp import web
from dotenv import load_dotenv

import accounts
import partner  # формат событий и дедуп общие с ботом, но без зависимости от MT5
import store
import coordination
from account_lock import locked

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def utcnow() -> datetime:
    """UTC без зоны. datetime.utcnow() объявлен устаревшим, а в базе лежат
    наивные значения — с ними и сравниваем, поэтому зону сразу отбрасываем.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

log = logging.getLogger("webhook")

PORT = int(os.getenv("WEBHOOK_PORT", 8443))
HOST = os.getenv("WEBHOOK_HOST", "127.0.0.1")
TOKEN = os.getenv("WEBHOOK_TOKEN", "")
# столько секунд считаем повтор тем же событием: портал шлёт зачисление и
# перевод в стратегию порознь, а выглядят они одинаково
HOOK_REPEAT = int(os.getenv("HOOK_REPEAT", 300))
# хэш git-коммита от агента (или «unknown»): только буквы и цифры
COMMIT_RE = re.compile(r"[0-9A-Za-z]{1,64}")


def ensure_token() -> str:
    """Токен в URL — самодельная защита; в доках Syntellicore подписи нет."""
    global TOKEN
    if TOKEN:
        return TOKEN
    TOKEN = secrets.token_urlsafe(24)
    path = os.getenv("ENV_FILE", ".env")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\nWEBHOOK_TOKEN={TOKEN}\n")
    log.warning("WEBHOOK_TOKEN не был задан, сгенерировал и дописал в %s", path)
    return TOKEN


def webhook_urls(host: str) -> dict[str, str]:
    t = ensure_token()
    base = f"http://{host}:{PORT}/hook"
    return {
        "On Registration": (f"{base}/registration?token={t}&customer_no={{{{customer_no}}}}"
                            f"&fname={{{{fname}}}}&lname={{{{lname}}}}&email={{{{email}}}}"),
        "On Deposit": (f"{base}/deposit?token={t}&customer_no={{{{customer_no}}}}"
                      f"&amount={{{{amount}}}}&currency={{{{currency}}}}"
                      f"&is_ftd={{{{is_ftd}}}}&tx_id={{{{tx_id}}}}"),
    }


def token_matches(value) -> bool:
    """Совпадает ли присланный токен с WEBHOOK_TOKEN.

    Сравнение за постоянное время: обычное == отвечает тем быстрее, чем раньше
    расходятся строки, — теоретическая утечка токена по времени ответа.
    Сравниваем байты, а не str: compare_digest не умеет не-ASCII строки и
    бросал TypeError (500 вместо 403). Пустая настройка не совпадает ни с
    чем — иначе отсутствующий токен «совпал» бы с незаданным.
    """
    if not TOKEN or not isinstance(value, str) or not value:
        return False
    try:
        supplied = value.encode("utf-8")
    except UnicodeError:        # одиночные суррогаты из JSON или заголовка
        return False
    return secrets.compare_digest(supplied, TOKEN.encode("utf-8"))


async def handle(request: web.Request, kind: str, fmt) -> web.Response:
    # портал шлёт POST (симулятор это показал), но URL с параметрами в доках
    # выглядит как GET — принимаем оба и собираем параметры отовсюду
    row = dict(request.query)
    if request.method == "POST":
        try:
            row.update(await request.post())
        except Exception:
            try:
                row.update(await request.json())
            except Exception:
                pass

    if not token_matches(row.get("token")):
        log.warning("вебхук %s: неверный токен от %s", kind, request.remote)
        raise web.HTTPForbidden(text="bad token")
    row.pop("token", None)
    db = request.app["db"]
    if kind == "registration":
        # запоминаем ФИО клиента по кабинету здесь, а не только в fmt_lead —
        # депозит того же клиента приходит без имени вовсе (вебхук On Deposit
        # шлёт только customer_no), и это единственный источник, откуда его
        # потом взять; безусловно и до дедупа: регистрация может прийти
        # раньше первого запуска бота и потеряться как first_run
        partner.remember_client_name(db, row)
    fresh, first_run = partner.unseen(db, kind, [row])
    if fresh and not first_run and not _just_sent(db, kind, row):
        # Telegram с этого сервера отвечает медленно, а портал ждёт ответа
        # считанные секунды и по таймауту шлёт событие заново — поэтому
        # подтверждаем сразу, а сообщение отправляем следом
        recipient = os.getenv("FOUNDER_ID") or os.getenv("TELEGRAM_CHAT_ID", "")
        if recipient:
            title = "Новая регистрация" if kind == "registration" else "Пополнение"
            detail = partner.who(row) if kind == "registration" else \
                f"{partner.whose(row, db)[0]} · {partner.money(row)}"
            partner.record_notification(db, recipient, f"hook:{kind}:{partner.row_id(row)}",
                                        kind, title, detail)
        fire(notify(request.app, fmt(row)))
        _remember_wallet_income(db, kind, row)
    log.info("вебхук %s: %s", kind, row.get("customer_no", row.get("tx_id", "?")))
    return web.Response(text="ok")


def _remember_wallet_income(db, kind: str, row: dict) -> None:
    """Депозит на свой кабинет — это приход на баланс Tag Markets.

    Копим только приход: портал шлёт вебхук на пополнение кошелька, а на
    вывод с него — нет. Расход (возврат денег в стратегию) partner считает
    сам по истории MT5, см. wallet_balance().
    """
    if kind != "deposit":
        return
    _, mine = partner.whose(row)
    if not mine:        # депозит клиента, а не движение своих денег
        return
    cabinet = str(partner.pick(row, "customer_no", "customer", "client_no") or "").strip()
    parsed = partner.parsed_amount(row)
    if not parsed:
        log.warning("не разобрал сумму депозита для кошелька: %r", partner.money(row))
        return
    amount, currency = parsed
    partner.wallet_add(db, cabinet, amount)
    partner.site_move_add(db, cabinet, "deposit", amount, currency)


def _just_sent(db, kind: str, row: dict) -> bool:
    """Не то же ли самое мы отправляли минуту назад.

    Портал шлёт одно событие дважды: сначала зачисление на баланс, следом
    перевод в стратегию — суммы и кабинет совпадают, и в чат падали два
    одинаковых сообщения. Дедупликация по id не спасает: id у них разные.
    """
    key = ("hook:" + kind + ":" + str(partner.pick(row, "customer_no", "customer") or "")
           + ":" + str(partner.pick(row, "amount", "sum") or ""))
    seen_at = partner.kv_get(db, key)
    now = utcnow()
    partner.kv_set(db, key, now.isoformat())
    if not seen_at:
        return False
    try:
        return (now - datetime.fromisoformat(seen_at)).total_seconds() < HOOK_REPEAT
    except ValueError:
        return False


NOTIFY_RETRIES = 3       # событие уже помечено виденным (partner.unseen) — повтора
NOTIFY_BACKOFF = 5       # со стороны портала не будет, единственный шанс доставить


async def notify(app, text: str) -> None:
    """Шлёт уведомление в Telegram с повторами.

    Событие уже отмечено как увиденное в partner.unseen() до вызова notify()
    (иначе портал, ретраящий по таймауту, продублировал бы сообщение) — то
    есть это единственная попытка доставить его. Без ретраев минутный сбой
    прокси/Telegram терял депозит или вывод клиента насовсем, без следа даже
    в логах уровня ошибки.
    """
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not chat_id:
        return
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"
    for attempt in range(1, NOTIFY_RETRIES + 1):
        try:
            async with app["tg"].post(
                    url, data={"chat_id": chat_id, "parse_mode": "HTML", "text": text},
                    proxy=app.get("proxy")) as resp:
                if resp.status < 300:
                    return
                body = await resp.text()
                raise RuntimeError(f"Telegram ответил {resp.status}: {body[:200]}")
        except Exception as e:
            if attempt == NOTIFY_RETRIES:
                log.error("не доставил уведомление в Telegram за %d попыток, "
                         "теряю: %s — %r", NOTIFY_RETRIES, e, text[:200])
                return
            log.warning("не отправил в Telegram (попытка %d/%d): %s",
                       attempt, NOTIFY_RETRIES, e)
            await asyncio.sleep(NOTIFY_BACKOFF * attempt)


_background: set[asyncio.Task] = set()   # держит задачи, пока notify() ретраит


def fire(coro) -> None:
    """asyncio.create_task, но без риска, что GC соберёт задачу на середине.

    Event loop хранит на задачу только слабую ссылку — она документированный
    источник потерянных fire-and-forget корутин. Пока notify() был мгновенным,
    окно было незаметным; с ретраями (до ~45 секунд на попытки и сон между
    ними) оно расширилось на два порядка, и уведомление могло пропасть без
    единой строки в логе — ровно то, что ретраи должны были вылечить.
    """
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def on_registration(request):
    return await handle(request, "lead", partner.fmt_lead)


async def on_deposit(request):
    db = request.app["db"]
    return await handle(request, "deposit", lambda row: partner.fmt_deposit(db, row))


async def health(request):
    return web.Response(text="ok")


async def status(request):
    """Состояние бота и синхронизации — читается по HTTPS, поэтому работает
    даже когда SSH до сервера не отвечает."""
    check_token(request)
    db = request.app["db"]
    ago = _stamp_age(partner.kv_get(db, "bot_heartbeat"))
    alive = ago is not None and ago < 120       # отметку бот ставит раз в 30 секунд

    trades_db = request.app["trades"]
    row = trades_db.execute("SELECT COUNT(*), MAX(synced) FROM state").fetchone()
    # секунды считаем здесь же, часами сервера с обеих сторон разности —
    # агент сравнивал last_sync (время сервера) со своими часами напрямую,
    # и рассинхрон часов агент/сервер ложно показывал то устаревший, то
    # свежий синк. sync_seconds_ago нейтрален к любому перекосу часов агента.
    last_sync = row[1] if row else None
    sync_ago = _stamp_age(last_sync)
    return web.json_response({
        "bot": "работает" if alive else "остановлен",
        "bot_seconds_ago": round(ago) if ago is not None else None,
        "accounts": row[0] if row else 0,
        "last_sync": last_sync,
        "sync_seconds_ago": round(sync_ago) if sync_ago is not None else None,
    })


# ── синхронизация с агентом на Windows ────────────────────────────────────
# Терминал MT5 работает только под Windows, поэтому историю читает агент на
# домашней машине и присылает сюда. Бот на сервере берёт данные уже из базы.

def check_token(request) -> None:
    # любой из двух источников, раз совпал — этого достаточно (агент может
    # прислать оба или только один); ошибочный query не должен перекрывать
    # верный header — иначе неверная строка в одном месте отказывала бы
    # запросу, у которого верный токен лежит в другом.
    if not (token_matches(request.query.get("token"))
            or token_matches(request.headers.get("X-Token"))):
        log.warning("агент: неверный токен от %s", request.remote)
        raise web.HTTPForbidden(text="bad token")


async def _agent_json(request) -> dict:
    """Тело агентского запроса: JSON-объект — или 400.

    Эти маршруты не под /api/, и middleware Mini App их ошибки не ловит:
    битый JSON или массив вместо объекта раньше давали 500 с трассировкой
    в логе на каждый такой запрос.
    """
    try:
        data = await request.json()
    except ValueError as exc:       # JSONDecodeError и битая кодировка тела
        raise web.HTTPBadRequest(text=f"bad payload: {exc}") from exc
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="bad payload: object required")
    return data


def _agent_host(value, required: bool = True) -> str:
    """Имя машины из запроса агента. Оно становится частью ключей в KV
    (machine_seen:<host> и т.п.), поэтому только строка разумной длины."""
    if value is not None and (not isinstance(value, str) or len(value) > 128
                              or "\x00" in value):
        raise web.HTTPBadRequest(text="invalid agent identity")
    host = (value or "").strip()
    if required and not host:
        raise web.HTTPBadRequest(text="invalid agent identity")
    return host


def _stamp_age(stamp) -> float | None:
    """Сколько секунд прошло с отметки из KV (UTC без зоны); None — если
    отметки нет или она битая: одна испорченная запись не должна ронять
    весь эндпоинт 500-й."""
    try:
        return (utcnow() - datetime.fromisoformat(stamp)).total_seconds()
    except (TypeError, ValueError):
        return None


# Настройки, общие для всех агентских машин — раздаём тем же токеном, что и
# /agent/accounts. Не всё из .env: приватные ключи портала и токен Telegram
# агенту не нужны и не должны покидать сервер лишний раз. MT5_TERMINAL,
# AGENT_ROLE, STANDBY_TIMEOUT, AGENT_LOCK_PORT — машинно-специфичные,
# каждая машина держит их сама.
AGENT_ENV_KEYS = ("AGENT_SERVER", "AGENT_INTERVAL",
                  "HISTORY_FROM", "INVESTOR_SHARE", "BROKER_FEE",
                  "REPORT_FROM", "TZ_HOURS")


async def agent_env(request):
    """Общие настройки для агента — чтобы .env не приходилось править вручную
    на каждой машине при смене токена или доли инвестора."""
    check_token(request)
    return web.json_response({k: os.environ[k] for k in AGENT_ENV_KEYS if k in os.environ})


async def agent_accounts(request):
    """Список счетов, которые агенту надо опрашивать (с паролями)."""
    check_token(request)
    session = request.headers.get("X-Agent-Session")
    allowed = (coordination.permits(request.app["db"], request.headers.get("X-Agent-Host"), session)
               if session else coordination.may_poll_anonymously(request.app["db"]))
    if not allowed:
        return web.json_response([])
    db = request.app["trades"]
    return web.json_response([
        {"name": a["name"], "login": a["login"], "password": a["password"],
         "server": a["server"], "multiplier": a.get("multiplier", 1),
         "since": store.last_ticket(db, a["login"]),
         "command": store.get_command(db, a["login"])}   # напр. «restart_terminal»
        # дедуп по логину+серверу БЕЗ владельца: агенту он не важен — это
        # один физический MT5-логин, даже если на него есть записи у разных
        # владельцев (свой счёт + расшаренная гостевая копия через share()).
        # by_owner=True тут не спас бы главный сценарий: гостевая копия
        # именно у ДРУГОГО owner'а всё равно осталась бы отдельной строкой
        # владелец решает, опрашивать ли счёт — его запись должна победить
        # дедуп раньше расшаренной гостевой копии того же логина, иначе
        # гость держит копию enabled и опрос продолжается вопреки паузе владельца
        for a in accounts.dedup(sorted((a for a in accounts.load()), key=lambda a: bool(a.get("shared_by"))), by_owner=False)
        if a.get("enabled", True)
    ])


async def agent_role_change(request):
    """Агентская машина сообщила о смене роли (резерв включился/выключился).

    Уведомление в Telegram сюда не входит — machines_watchdog в bot.py уже
    следит за active_machine и шлёт более точный текст (с учётом роли обеих
    машин, а не только «резерв»/«не резерв»); дублировать его тут значило бы
    слать два сообщения об одном и том же событии. Этот эндпоинт только
    держит active_machine актуальным на случай, если standby включился без
    очередного agent_sync (тот тоже пишет active_machine, но не сразу).
    """
    check_token(request)
    data = await _agent_json(request)
    host = _agent_host(data.get("host"), required=False) or "неизвестная машина"
    became = data.get("became")     # "active" | "standby"
    db = request.app["db"]
    if became == "active":
        if not coordination.authorize(db, host, data.get("session")):
            return web.json_response({"ok": False, "error": "not polling owner"}, status=409)
        partner.kv_set(db, "active_machine", host)
    elif became != "standby":
        return web.json_response({"ok": False, "error": "bad became"}, status=400)
    log.info("смена роли: %s -> %s", host, became)
    return web.json_response({"ok": True})


async def agent_update_notify(request):
    """Агентская машина только что подтянула новый код и перезапустилась.

    Уведомление идёт только основателю (notify() шлёт на TELEGRAM_CHAT_ID —
    личный чат оператора, не общий канал) и только если он не отключил его
    в настройках бота (update_alerts, по умолчанию включено). Настройка
    хранится в KV без привязки к владельцу счёта — она про машины, а не
    про чьи-то счета, и видна в боте только основателю.
    """
    check_token(request)
    data = await _agent_json(request)
    host = _agent_host(data.get("host"), required=False) or "неизвестная машина"
    commit = str(data.get("commit") or "")[:8]
    # агент шлёт сюда же и автоматический откат плохого обновления
    # (_report_rollback): commit — рабочий, на который вернулся, rollback_from —
    # тот, что не подтвердил себя. Раньше откат читался как «подтянул новый код»
    rolled_back = str(data.get("rollback_from") or "")[:8]
    db = request.app["db"]
    if partner.kv_get(db, "update_alerts") != "0":
        who = html.escape(host)
        if rolled_back:
            text = (f"⏪ <b>Агент откатил обновление</b>\n{partner.THIN}\n"
                    f"<b>{who}</b>: код {html.escape(rolled_back)} не подтвердил себя "
                    f"после перезапуска — вернулся на рабочий"
                    + (f" {html.escape(commit)}" if commit else "") + ".")
        else:
            text = (f"🔄 <b>Агент обновился</b>\n{partner.THIN}\n"
                    f"<b>{who}</b> подтянул новый код"
                    + (f" ({html.escape(commit)})" if commit else "") + " и перезапустился.")
        fire(notify(request.app, text))
    if rolled_back:
        log.warning("агент откатился: %s %s -> %s", host, rolled_back, commit or "?")
    else:
        log.info("агент обновился: %s -> %s", host, commit or "?")
    return web.json_response({"ok": True})


async def agent_update_report(request):
    """Резервная машина отчиталась: работает на таком-то коммите столько-то.

    Канареечный деплой: standby не трогает терминал, поэтому обновляется на
    новый код сразу и без риска. primary мог бы обновиться следом за ним, но
    ждёт, пока станет видно, что standby на новом коде уже какое-то время не
    падал (через тот же /agent/sync — если синк не прервался, значит код
    рабочий) — прежде чем самому рисковать активной сессией в терминале.
    """
    check_token(request)
    data = await _agent_json(request)
    host = _agent_host(data.get("host"), required=False)
    commit = data.get("commit")
    # коммит становится частью ключа canary:<host>:<commit> и шаблона LIKE в
    # agent_update_status — «%» или «_» в нём совпали бы с чужими записями
    if not host or not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        return web.json_response({"ok": False}, status=400)
    db = request.app["db"]
    blocked = str(data.get("blocked") or "").strip()[:120]
    if blocked:
        # причина, по которой машина не может обновиться (грязная рабочая копия,
        # незапушенный коммит) — панель сервиса показывает её вместо молчания
        partner.kv_set(db, f"machine_blocked:{host}", f"{utcnow().isoformat()}|{blocked}")
    # первая метка по этому (host, commit) остаётся первой — она и есть
    # «с какого момента standby живёт на этом коде», а не последний репорт
    key = f"canary:{host}:{commit}"
    if not partner.kv_get(db, key):
        partner.kv_set(db, key, utcnow().isoformat())
    partner.kv_set(db, "canary_latest_commit", commit)
    partner.kv_set(db, f"machine_commit:{host}", commit)
    partner.kv_set(db, f"canary_latest_seen:{host}", utcnow().isoformat())
    return web.json_response({"ok": True})


def canary_age(db, commit: str) -> float | None:
    """Сколько секунд какая-то машина подтверждённо прожила на этом коммите.

    Раньше это было «сколько прошло с первого отчёта», и канарейка, упавшая
    через минуту после обновления (или откатившаяся), через CANARY_DELAY всё
    равно разрешала основной машине обновиться на тот же код — «обкатку»
    засчитывало само время, а не работа. Теперь в зачёт идёт только отрезок
    от первого до последнего отчёта машины, и только пока она всё ещё на
    этом коммите. У живой канарейки последний отчёт — секунды назад, так что
    для неё число то же, что и раньше.
    """
    if not commit or not COMMIT_RE.fullmatch(commit):
        return None
    best = None
    for key in partner.kv_keys(db, f"canary:%:{commit}"):
        host, sep, tail = key[len("canary:"):].rpartition(":")
        if not sep or tail != commit or not host:
            continue
        if partner.kv_get(db, f"machine_commit:{host}") != commit:
            continue        # машина ушла с этого кода: откатилась или обновилась дальше
        try:
            first = datetime.fromisoformat(partner.kv_get(db, key) or "")
        except ValueError:
            continue
        try:
            last = datetime.fromisoformat(partner.kv_get(db, f"canary_latest_seen:{host}") or "")
        except ValueError:
            last = first
        lived = max(0.0, (max(last, first) - first).total_seconds())
        best = lived if best is None else max(best, lived)
    return best


async def agent_update_status(request):
    """Можно ли обновляться на этот коммит — и сколько кто-то на нём проработал."""
    check_token(request)
    age = canary_age(request.app["db"], request.query.get("commit", ""))
    return web.json_response({"canary_age_seconds": round(age) if age is not None else None})


async def agent_heartbeat(request):
    """Машина в резерве отмечается: жива, ждёт молча — она не шлёт agent_sync
    (терминал не опрашивает), и без этого сервер не знал бы её hostname."""
    check_token(request)
    data = await _agent_json(request)
    host = _agent_host(data.get("host"), required=False)
    if not host:
        return web.json_response({"ok": False}, status=400)
    db = request.app["db"]
    partner.kv_set(db, f"machine_seen:{host}", utcnow().isoformat())
    role = str(data.get("role") or "").strip().lower()
    if role in ("primary", "standby"):
        partner.kv_set(db, f"machine_role:{host}", role)
    return web.json_response({"ok": True})


async def agent_machines_status(request):
    """Кто из известных машин недавно был на связи — для /status и уведомлений."""
    check_token(request)
    db = request.app["db"]
    try:
        stale_after = int(request.query.get("stale_after", 60))
    except ValueError:
        raise web.HTTPBadRequest(text="stale_after: integer required") from None
    out = {}
    for key in partner.kv_keys(db, "machine_seen:%"):
        host = key.split(":", 1)[1]
        seen = partner.kv_get(db, key)
        age = _stamp_age(seen)
        if seen and age is None:
            # битая метка не должна валить весь эндпоинт для всех машин —
            # просто не знаем возраст этой конкретной записи
            log.warning("machines_status: не разобрал метку времени %s=%r", key, seen)
        out[host] = {"seconds_ago": round(age) if age is not None else None,
                    "alive": age is not None and age < stale_after}
    return web.json_response({"machines": out,
                             "active_machine": partner.kv_get(db, "active_machine")})


def _sync_number(value, name: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name}: number required")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: number required") from exc
    if not math.isfinite(number) or abs(number) > 1e15 or (nonnegative and number < 0):
        raise ValueError(f"{name}: out of range")
    return number


def _sync_text(value, name: str, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name}: invalid text")
    return value


def _sync_flag(value, name: str) -> bool:
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    raise ValueError(f"{name}: boolean required")


def _sync_payload(data: dict) -> tuple[int, dict, list[dict], bool]:
    """Validate the whole packet before touching state, deals or commands."""
    if not isinstance(data, dict):
        raise ValueError("object required")
    login = data.get("login")
    if type(login) not in (int, str) or not str(login).isdigit() or not 0 < int(login) < 2**63:
        raise ValueError("login: positive integer required")
    login = int(login)
    state = {
        "balance": _sync_number(data.get("balance"), "balance"),
        "equity": _sync_number(data.get("equity"), "equity"),
        "currency": _sync_text(data.get("currency"), "currency", 16),
        "server": _sync_text(data.get("server"), "server", 128),
        "capital_hist": None if data.get("capital_hist") is None else
            _sync_number(data["capital_hist"], "capital_hist"),
    }
    if not state["currency"].strip() or not state["server"].strip():
        raise ValueError("currency/server: required")
    command_done = _sync_flag(data.get("command_done", False), "command_done")
    incoming = data.get("deals")
    if not isinstance(incoming, list) or len(incoming) > 50000:
        raise ValueError("deals: invalid list")
    deals = []
    tickets = set()
    for index, row in enumerate(incoming):
        label = f"deals[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"{label}: object required")
        ticket = row.get("ticket")
        if type(ticket) not in (int, str) or not str(ticket).isdigit() or not 0 < int(ticket) < 2**63:
            raise ValueError(f"{label}.ticket: positive integer required")
        ticket = int(ticket)
        if ticket in tickets:
            raise ValueError(f"{label}.ticket: duplicate in packet")
        tickets.add(ticket)
        raw_time = row.get("time")
        if not isinstance(raw_time, str):
            raise ValueError(f"{label}.time: ISO timestamp required")
        try:
            when = datetime.fromisoformat(raw_time)
        except ValueError as exc:
            raise ValueError(f"{label}.time: invalid timestamp") from exc
        if when.tzinfo is not None or not 2000 <= when.year <= 2100:
            raise ValueError(f"{label}.time: UTC naive timestamp required")
        deal = {"ticket": ticket, "time": when.isoformat()}
        for field, limit in (("symbol", 64), ("side", 8), ("comment", 1024)):
            deal[field] = _sync_text(row.get(field), f"{label}.{field}", limit)
        if deal["side"] not in ("", "BUY", "SELL"):
            raise ValueError(f"{label}.side: invalid value")
        for field in ("volume", "price", "profit", "swap", "commission", "net"):
            deal[field] = _sync_number(row.get(field), f"{label}.{field}",
                                       nonnegative=field in ("volume", "price"))
        for field in ("is_balance", "is_closing", "is_opening"):
            deal[field] = _sync_flag(row.get(field), f"{label}.{field}")
        if sum(deal[field] for field in ("is_balance", "is_closing", "is_opening")) > 1:
            raise ValueError(f"{label}: contradictory flags")
        deals.append(deal)
    return login, state, deals, command_done


async def agent_sync(request):
    """Агент прислал состояние счёта и новые сделки."""
    check_token(request)
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("object required")
    except (ValueError, TypeError, KeyError, OverflowError) as e:
        raise web.HTTPBadRequest(text=f"bad payload: {e}")
    db = request.app["trades"]
    host, session = data.get("host"), data.get("session")
    if (not isinstance(host, str) or not 1 <= len(host) <= 128
            or (session is not None and (not isinstance(session, str) or not 16 <= len(session) <= 128))):
        raise web.HTTPBadRequest(text="invalid agent identity")
    if not coordination.authorize(request.app["db"], host, session):
        raise web.HTTPConflict(text="polling lease lost")
    try:
        login, state, deals, command_done = _sync_payload(data)
    except (ValueError, TypeError, KeyError, OverflowError) as e:
        raise web.HTTPBadRequest(text=f"bad payload: {e}")

    try:
        new = store.save_sync(db, login, state, deals, command_done)
    except sqlite3.DatabaseError as exc:
        log.warning("temporary database failure during sync for %s: %s", login, exc)
        raise web.HTTPServiceUnavailable(text="database temporarily busy")
    reported_server = state["server"].strip()
    # имя владельца из MT5 необязательно: непригодное (не строка, слишком
    # длинное) просто не трогает accounts.json, а не отвергает весь пакет —
    # из-за одной подписи не должен останавливаться поток сделок
    holder = data.get("holder")
    reported_holder = (holder.strip() if isinstance(holder, str) and len(holder) <= 128
                       and "\x00" not in holder else "")
    if reported_server or reported_holder:
        # MT5 is authoritative for broker server and account owner label.
        # Update every legitimate owner copy atomically; a shared copy must
        # never drift from the physical account it represents.
        with locked(accounts.PATH):
            all_accounts = accounts._read()
            changed = False
            for acc in all_accounts:
                if int(acc.get("login", -1)) != login:
                    continue
                if reported_server and acc.get("server") != reported_server:
                    acc["server"] = reported_server; changed = True
                if reported_holder and acc.get("holder") != reported_holder:
                    acc["holder"] = reported_holder; changed = True
            if changed:
                accounts.save(all_accounts)
    if new:
        log.info("счёт %s: %d новых сделок", login, new)

    host = data.get("host")
    if host:
        # какая машина реально опрашивает терминал прямо сейчас — для
        # /agent/machines_status и machines_watchdog в bot.py. ВАЖНО: kv-таблица
        # живёт в app["db"] (partner.open_db), а не в app["trades"] (store.open_db,
        # только сделки/состояние счетов, без таблицы kv вообще) — локальная
        # `db` выше в этой функции указывает на trades, использовать её здесь
        # означало бы падать с "no such table: kv" на каждый вызов с host
        kvdb = request.app["db"]
        partner.kv_set(kvdb, "active_machine", host)
        partner.kv_set(kvdb, f"machine_seen:{host}", utcnow().isoformat())
        partner.kv_set(kvdb, f"machine_sync:{host}", utcnow().isoformat())
        role = str(data.get("role") or "").strip().lower()
        if role in ("primary", "standby"):
            partner.kv_set(kvdb, f"machine_role:{host}", role)
    coordination.renew(request.app["db"], data.get("host"), data.get("session"))
    return web.json_response({"ok": True, "new": new})


def _candle_row(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("candle: object required")
    time_text = _sync_text(raw.get("time"), "candle.time", 40)
    try:
        datetime.fromisoformat(time_text)
    except ValueError as exc:
        raise ValueError("candle.time: invalid ISO datetime") from exc
    return {"time": time_text,
            "open": _sync_number(raw.get("open"), "candle.open", nonnegative=True),
            "high": _sync_number(raw.get("high"), "candle.high", nonnegative=True),
            "low": _sync_number(raw.get("low"), "candle.low", nonnegative=True),
            "close": _sync_number(raw.get("close"), "candle.close", nonnegative=True)}


async def agent_candles(request):
    """Агент прислал свечи XAUUSD для графика цены — не привязано к счёту/лизу:
    котировки одного символа общие для всех, кто сейчас держит терминал.
    """
    check_token(request)
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("object required")
        rows = data.get("candles")
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError("candles: list required")
        candles = [_candle_row(r) for r in rows]
    except (ValueError, TypeError, KeyError, OverflowError) as e:
        raise web.HTTPBadRequest(text=f"bad payload: {e}")
    db = request.app["trades"]
    try:
        new = store.save_candles(db, candles)
        store.trim_candles(db, commit=False)
        db.commit()
    except sqlite3.DatabaseError as exc:
        log.warning("temporary database failure during candle sync: %s", exc)
        raise web.HTTPServiceUnavailable(text="database temporarily busy")
    return web.json_response({"ok": True, "new": new})


async def agent_claim(request):
    check_token(request)
    try:
        data = await request.json()
        host, session, role = data["host"], data["session"], data["role"]
        if (not isinstance(host, str) or not 1 <= len(host) <= 128
                or not isinstance(session, str) or not 16 <= len(session) <= 128
                or role not in ("primary", "standby")):
            raise ValueError("invalid agent identity")
    except (ValueError, TypeError, KeyError):
        raise web.HTTPBadRequest(text="invalid agent identity")
    result = coordination.claim(request.app["db"], host, session, role)
    # машина, которая умеет просить аренду, — на актуальном коде; по отсутствию
    # этой отметки панель сервиса отличает резерв на старом коде, который
    # заменить основную не сможет
    partner.kv_set(request.app["db"], f"machine_claim:{host}", utcnow().isoformat())
    return web.json_response(result)


async def main():
    ensure_token()
    import aiohttp
    # Telegram initData, webhook payloads and broadcasts are small; reject
    # unexpectedly large bodies before they reach JSON/form parsers.
    # Telegram media broadcasts are capped at 20 MiB by the API handler;
    # leave a small multipart overhead margin here.
    app = web.Application(client_max_size=22 * 1024 * 1024)
    app["db"] = partner.open_db()
    # Telegram недоступен с сервера напрямую (Москва) — тот же прокси, что у бота.
    # Без него вебхуки исправно приходили, а сообщения молча не доставлялись
    app["proxy"] = os.getenv("TELEGRAM_PROXY", "").split(",")[0].strip() or None
    app["tg"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    app["trades"] = store.open_db()
    import miniapp
    miniapp.setup(app)
    app.router.add_route("*", "/hook/registration", on_registration)
    app.router.add_route("*", "/hook/deposit", on_deposit)
    app.router.add_get("/health", health)
    app.router.add_get("/status", status)
    app.router.add_get("/agent/accounts", agent_accounts)
    app.router.add_get("/agent/env", agent_env)
    app.router.add_post("/agent/sync", agent_sync)
    app.router.add_post("/agent/candles", agent_candles)
    app.router.add_post("/agent/claim", agent_claim)
    app.router.add_post("/agent/role_change", agent_role_change)
    app.router.add_post("/agent/update_notify", agent_update_notify)
    app.router.add_post("/agent/update_report", agent_update_report)
    app.router.add_get("/agent/update_status", agent_update_status)
    app.router.add_post("/agent/heartbeat", agent_heartbeat)
    app.router.add_get("/agent/machines_status", agent_machines_status)

    runner = web.AppRunner(app)
    await runner.setup()
    # наружу нас отдаёт nginx, поэтому слушаем локально: так порт не торчит в интернет
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    log.info("слушаю 0.0.0.0:%s — токен в URL, см. .env WEBHOOK_TOKEN", PORT)
    try:
        await asyncio.Event().wait()
    finally:
        await app["tg"].close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
