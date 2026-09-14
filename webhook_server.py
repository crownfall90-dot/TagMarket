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
import logging
import os
import secrets
from datetime import datetime, timezone

from aiohttp import web
from dotenv import load_dotenv

import accounts
import partner  # формат событий и дедуп общие с ботом, но без зависимости от MT5
import store

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

    if row.get("token") != TOKEN:
        log.warning("вебхук %s: неверный токен от %s", kind, request.remote)
        raise web.HTTPForbidden(text="bad token")
    row.pop("token", None)
    db = request.app["db"]
    fresh, first_run = partner.unseen(db, kind, [row])
    if fresh and not first_run and not _just_sent(db, kind, row):
        # Telegram с этого сервера отвечает медленно, а портал ждёт ответа
        # считанные секунды и по таймауту шлёт событие заново — поэтому
        # подтверждаем сразу, а сообщение отправляем следом
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
    # money() отдаёт "1234.56 USD" — та же форма, что уже разбирает pretty_money()
    # по всему боту; берём число тем же способом (rpartition по последнему
    # пробелу — устойчивее, чем брать первое слово, если в сумме вдруг
    # окажется внутренний пробел)
    number, _, _ = partner.money(row).rpartition(" ")
    try:
        partner.wallet_add(db, cabinet, float(number.replace(" ", "").replace(" ", "")))
    except (TypeError, ValueError):
        log.warning("не разобрал сумму депозита для кошелька: %r", number)


def _just_sent(db, kind: str, row: dict) -> bool:
    """Не то же ли самое мы отправляли минуту назад.

    Портал шлёт одно событие дважды: сначала зачисление на баланс, следом
    перевод в стратегию — суммы и кабинет совпадают, и в чат падали два
    одинаковых сообщения. Дедупликация по id не спасает: id у них разные.
    """
    key = ("hook:" + kind + ":" + str(partner.pick(row, "customer_no", "customer") or "")
           + ":" + str(partner.pick(row, "amount", "sum") or ""))
    seen_at = partner.kv_get(db, key)
    now = datetime.utcnow()
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
    return await handle(request, "deposit", partner.fmt_deposit)


async def health(request):
    return web.Response(text="ok")


async def status(request):
    """Состояние бота и синхронизации — читается по HTTPS, поэтому работает
    даже когда SSH до сервера не отвечает."""
    db = request.app["db"]
    beat = partner.kv_get(db, "bot_heartbeat")
    alive, ago = False, None
    if beat:
        ago = (utcnow() - datetime.fromisoformat(beat)).total_seconds()
        alive = ago < 120        # отметку бот ставит раз в 30 секунд

    trades_db = request.app["trades"]
    row = trades_db.execute("SELECT COUNT(*), MAX(synced) FROM state").fetchone()
    # секунды считаем здесь же, часами сервера с обеих сторон разности —
    # агент сравнивал last_sync (время сервера) со своими часами напрямую,
    # и рассинхрон часов агент/сервер ложно показывал то устаревший, то
    # свежий синк. sync_seconds_ago нейтрален к любому перекосу часов агента.
    last_sync = row[1] if row else None
    sync_ago = (utcnow() - datetime.fromisoformat(last_sync)).total_seconds() \
        if last_sync else None
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
    # constant-time сравнение: обычное != отдаёт результат тем быстрее, чем
    # раньше расходятся строки — теоретическая утечка токена по времени ответа
    q = request.query.get("token") or ""
    h = request.headers.get("X-Token") or ""
    if not (secrets.compare_digest(q, TOKEN) or secrets.compare_digest(h, TOKEN)):
        log.warning("агент: неверный токен от %s", request.remote)
        raise web.HTTPForbidden(text="bad token")


# Настройки, общие для всех агентских машин — раздаём тем же токеном, что и
# /agent/accounts. Не всё из .env: приватные ключи портала и токен Telegram
# агенту не нужны и не должны покидать сервер лишний раз. MT5_TERMINAL,
# AGENT_ROLE, STANDBY_TIMEOUT, AGENT_LOCK_PORT — машинно-специфичные,
# каждая машина держит их сама.
AGENT_ENV_KEYS = ("AGENT_SERVER", "WEBHOOK_TOKEN", "AGENT_INTERVAL",
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
        for a in accounts.dedup(accounts.load(), by_owner=False) if a.get("enabled", True)
    ])


async def agent_role_change(request):
    """Агентская машина сообщила о смене роли (резерв включился/выключился).

    Сама рассылка через notify() живёт здесь, а не на агенте: у него нет и
    не должно быть токена Telegram-бота на клиентской машине, а сервер его
    уже держит для всех остальных уведомлений.
    """
    check_token(request)
    data = await request.json()
    host = str(data.get("host") or "неизвестная машина")
    became = data.get("became")     # "active" | "standby"
    db = request.app["db"]
    if became == "active":
        partner.kv_set(db, "active_machine", host)
        text = (f"🔀 <b>Резерв подключился</b>\n{partner.THIN}\n"
               f"<b>{host}</b> взял на себя опрос терминала — "
               f"основная машина не отвечала.")
    elif became == "standby":
        text = (f"🔀 <b>Резерв отключился</b>\n{partner.THIN}\n"
               f"<b>{host}</b> увидел, что основная машина снова на связи, "
               f"и вернулся в ожидание.")
    else:
        return web.json_response({"ok": False, "error": "bad became"}, status=400)
    fire(notify(request.app, text))
    log.info("смена роли: %s -> %s", host, became)
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
    data = await request.json()
    host = str(data.get("host") or "")
    commit = str(data.get("commit") or "")
    if not host or not commit:
        return web.json_response({"ok": False}, status=400)
    db = request.app["db"]
    # первая метка по этому (host, commit) остаётся первой — она и есть
    # «с какого момента standby живёт на этом коде», а не последний репорт
    key = f"canary:{host}:{commit}"
    if not partner.kv_get(db, key):
        partner.kv_set(db, key, utcnow().isoformat())
    partner.kv_set(db, "canary_latest_commit", commit)
    partner.kv_set(db, f"canary_latest_seen:{host}", utcnow().isoformat())
    return web.json_response({"ok": True})


async def agent_update_status(request):
    """Можно ли обновляться на этот коммит — и как давно кто-то на нём живёт."""
    check_token(request)
    commit = request.query.get("commit", "")
    db = request.app["db"]
    since = None
    if commit:
        # берём самую раннюю метку среди всех машин, репортовавших этот коммит
        stamps = [partner.kv_get(db, k) for k in partner.kv_keys(db, f"canary:%:{commit}")]
        stamps = [s for s in stamps if s]
        since = min(stamps) if stamps else None
    age = (utcnow() - datetime.fromisoformat(since)).total_seconds() if since else None
    return web.json_response({"canary_age_seconds": round(age) if age is not None else None})


async def agent_heartbeat(request):
    """Машина в резерве отмечается: жива, ждёт молча — она не шлёт agent_sync
    (терминал не опрашивает), и без этого сервер не знал бы её hostname."""
    check_token(request)
    data = await request.json()
    host = str(data.get("host") or "")
    if not host:
        return web.json_response({"ok": False}, status=400)
    db = request.app["db"]
    partner.kv_set(db, f"machine_seen:{host}", utcnow().isoformat())
    return web.json_response({"ok": True})


async def agent_machines_status(request):
    """Кто из известных машин недавно был на связи — для /status и уведомлений."""
    check_token(request)
    db = request.app["db"]
    stale_after = int(request.query.get("stale_after", 60))
    out = {}
    for key in partner.kv_keys(db, "machine_seen:%"):
        host = key.split(":", 1)[1]
        seen = partner.kv_get(db, key)
        age = None
        if seen:
            try:
                age = (utcnow() - datetime.fromisoformat(seen)).total_seconds()
            except ValueError:
                # битая метка не должна валить весь эндпоинт для всех машин —
                # просто не знаем возраст этой конкретной записи
                log.warning("machines_status: не разобрал метку времени %s=%r", key, seen)
        out[host] = {"seconds_ago": round(age) if age is not None else None,
                    "alive": age is not None and age < stale_after}
    return web.json_response({"machines": out,
                             "active_machine": partner.kv_get(db, "active_machine")})


def _valid_deal(d: dict) -> bool:
    """Сделка годна к записи: время реально парсится.

    Без этой проверки битая строка (обрыв связи на середине, старая версия
    агента) тихо ложится в deals, а датой давится не запись, а КАЖДОЕ чтение
    истории потом — store.fetch() падает ValueError на datetime.fromisoformat,
    а capital()/_profit_on_account() эту ошибку глотают и молча возвращают
    0 вместо честного сбоя. Итог — капитал завышен, и никто не узнает.
    """
    t = d.get("time")
    if isinstance(t, datetime):
        return True
    try:
        datetime.fromisoformat(str(t))
        return True
    except (TypeError, ValueError):
        return False


async def agent_sync(request):
    """Агент прислал состояние счёта и новые сделки."""
    check_token(request)
    try:
        data = await request.json()
        login = int(data["login"])
    except (ValueError, TypeError, KeyError) as e:
        raise web.HTTPBadRequest(text=f"bad payload: {e}")
    db = request.app["trades"]

    store.save_state(db, login, data.get("balance", 0.0), data.get("equity", 0.0),
                     data.get("currency", ""), data.get("server", ""),
                     data.get("capital_hist"))
    if data.get("command_done"):        # агент выполнил команду — снимаем её
        store.clear_command(db, login)

    deals = data.get("deals", [])
    good = [d for d in deals if _valid_deal(d)]
    if len(good) != len(deals):
        log.error("счёт %s: %d сделок с нечитаемым временем отброшено", login,
                  len(deals) - len(good))
    new = store.save_deals(db, login, good)
    if new:
        log.info("счёт %s: %d новых сделок", login, new)

    host = data.get("host")
    if host:
        # какая машина реально опрашивает терминал прямо сейчас — для
        # /agent/machines_status и для текста в agent_role_change
        partner.kv_set(db, "active_machine", host)
        partner.kv_set(db, f"machine_seen:{host}", utcnow().isoformat())
    return web.json_response({"ok": True, "new": new})


async def main():
    ensure_token()
    import aiohttp
    app = web.Application()
    app["db"] = partner.open_db()
    # Telegram недоступен с сервера напрямую (Москва) — тот же прокси, что у бота.
    # Без него вебхуки исправно приходили, а сообщения молча не доставлялись
    app["proxy"] = os.getenv("TELEGRAM_PROXY", "").split(",")[0].strip() or None
    app["tg"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    app["trades"] = store.open_db()
    app.router.add_route("*", "/hook/registration", on_registration)
    app.router.add_route("*", "/hook/deposit", on_deposit)
    app.router.add_get("/health", health)
    app.router.add_get("/status", status)
    app.router.add_get("/agent/accounts", agent_accounts)
    app.router.add_get("/agent/env", agent_env)
    app.router.add_post("/agent/sync", agent_sync)
    app.router.add_post("/agent/role_change", agent_role_change)
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


if __name__ == "__main__":
    asyncio.run(main())
