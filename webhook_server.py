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
    if fresh and not first_run:
        # Telegram с этого сервера отвечает медленно, а портал ждёт ответа
        # считанные секунды и по таймауту шлёт событие заново — поэтому
        # подтверждаем сразу, а сообщение отправляем следом
        asyncio.create_task(notify(request.app, fmt(row)))
    log.info("вебхук %s: %s", kind, row.get("customer_no", row.get("tx_id", "?")))
    return web.Response(text="ok")


async def notify(app, text: str) -> None:
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not chat_id:
        return
    try:
        await app["tg"].post(
            f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
            data={"chat_id": chat_id, "parse_mode": "HTML", "text": text})
    except Exception as e:
        log.warning("не отправил в Telegram: %s", e)


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
    return web.json_response({
        "bot": "работает" if alive else "остановлен",
        "bot_seconds_ago": round(ago) if ago is not None else None,
        "accounts": row[0] if row else 0,
        "last_sync": row[1] if row else None,
    })


# ── синхронизация с агентом на Windows ────────────────────────────────────
# Терминал MT5 работает только под Windows, поэтому историю читает агент на
# домашней машине и присылает сюда. Бот на сервере берёт данные уже из базы.

def check_token(request) -> None:
    if request.query.get("token") != TOKEN and request.headers.get("X-Token") != TOKEN:
        log.warning("агент: неверный токен от %s", request.remote)
        raise web.HTTPForbidden(text="bad token")


async def agent_accounts(request):
    """Список счетов, которые агенту надо опрашивать (с паролями)."""
    check_token(request)
    db = request.app["trades"]
    return web.json_response([
        {"name": a["name"], "login": a["login"], "password": a["password"],
         "server": a["server"], "multiplier": a.get("multiplier", 1),
         "since": store.last_ticket(db, a["login"]),
         "command": store.get_command(db, a["login"])}   # напр. «restart_terminal»
        for a in accounts.load() if a.get("enabled", True)
    ])


async def agent_sync(request):
    """Агент прислал состояние счёта и новые сделки."""
    check_token(request)
    data = await request.json()
    db = request.app["trades"]
    login = int(data["login"])

    store.save_state(db, login, data.get("balance", 0.0), data.get("equity", 0.0),
                     data.get("currency", ""), data.get("server", ""))
    if data.get("command_done"):        # агент выполнил команду — снимаем её
        store.clear_command(db, login)
    new = store.save_deals(db, login, data.get("deals", []))
    if new:
        log.info("счёт %s: %d новых сделок", login, new)
    return web.json_response({"ok": True, "new": new})


async def main():
    ensure_token()
    import aiohttp
    app = web.Application()
    app["db"] = partner.open_db()
    app["tg"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    app["trades"] = store.open_db()
    app.router.add_route("*", "/hook/registration", on_registration)
    app.router.add_route("*", "/hook/deposit", on_deposit)
    app.router.add_get("/health", health)
    app.router.add_get("/status", status)
    app.router.add_get("/agent/accounts", agent_accounts)
    app.router.add_post("/agent/sync", agent_sync)

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
