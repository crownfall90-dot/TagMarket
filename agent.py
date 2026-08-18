"""Агент: читает терминал MT5 на Windows и отправляет историю на сервер.

Нужен потому, что библиотека MetaTrader5 — мост к запущенному Windows-терминалу,
и на Linux-сервере её нет. Агент ходит на сервер сам (исходящие запросы), так что
пробрасывать порты домой не нужно.

Запуск:  python agent.py
Настройки в .env:
    AGENT_SERVER=https://crownfail.shop/tagmarkets
    WEBHOOK_TOKEN=...          — тот же токен, что у сервера
    AGENT_INTERVAL=15          — пауза между кругами, секунды
"""

import logging
import logging.handlers
import os
import socket
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

import trades

load_dotenv()
ROOT = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(ROOT, "logs")
os.makedirs(LOGS, exist_ok=True)
os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)

# в фоне консоли нет, поэтому пишем ещё и в файл — его показывает пульт управления.
# Файл крутится по кругу: агент пишет каждые 15 секунд и без ограничения
# за год оставил бы десятки мегабайт.
_handlers = [logging.handlers.RotatingFileHandler(
    os.path.join(LOGS, "agent.log"),
    maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
if sys.stdout is not None:
    _handlers.append(logging.StreamHandler())
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=_handlers)

def utcnow() -> datetime:
    """UTC без зоны. datetime.utcnow() объявлен устаревшим, а в базе лежат
    наивные значения — с ними и сравниваем, поэтому зону сразу отбрасываем.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

log = logging.getLogger("agent")

SERVER = os.getenv("AGENT_SERVER", "https://crownfail.shop/tagmarkets").rstrip("/")
TOKEN = os.getenv("WEBHOOK_TOKEN", "")
INTERVAL = int(os.getenv("AGENT_INTERVAL", 15))
# храним историю с этой даты — старое на сервере не нужно и только занимает место
HISTORY_FROM = datetime.fromisoformat(os.getenv("HISTORY_FROM", "2026-06-01"))
LOCK_PORT = int(os.getenv("AGENT_LOCK_PORT", 47653))    # признак «агент уже работает»
# отметка «последняя успешная связь с терминалом» — её читает сторож keeper.ps1
# на ПК: если отметке ≥3 минут или процесса нет, сторож перезапускает агента
# (раньше, чем на 5-й минуте сработает уведомление сервера)
BEAT = os.path.join(ROOT, "data", "agent.beat")


def fetch_accounts() -> list[dict]:
    r = requests.get(f"{SERVER}/agent/accounts", params={"token": TOKEN}, timeout=30)
    r.raise_for_status()
    return r.json()


def push(payload: dict) -> int:
    r = requests.post(f"{SERVER}/agent/sync", json=payload,
                      headers={"X-Token": TOKEN}, timeout=60)
    r.raise_for_status()
    return r.json().get("new", 0)


def collect(acc: dict) -> dict:
    """Состояние счёта и его сделки. Первый раз — вся история, потом только новые."""
    done = False
    if acc.get("command") == "restart_terminal":
        # кнопка «запустить» из бота: убиваем терминал и поднимаем заново
        log.info("%s: команда перезапуска терминала", acc["name"])
        try:
            import subprocess
            subprocess.run(["taskkill", "/F", "/IM", "terminal64.exe"],
                           capture_output=True, timeout=15)
            time.sleep(3)
            trades._current = ""            # заставить переоткрыть терминал
        except Exception as e:
            log.warning("не убил терминал: %s", e)
        done = True

    trades.use(acc)
    info = trades.account()
    if not info or int(info.login) != int(acc["login"]):
        raise RuntimeError("терминал открыл не тот счёт")

    since = acc.get("since") or 0
    if since:
        deals = trades.since_ticket(since)
    else:   # сервер про этот счёт ещё не знает — отдаём историю с нужной даты
        deals = trades.fetch(HISTORY_FROM, trades.clock() + timedelta(days=1))
    deals = [d for d in deals if d["time"] >= HISTORY_FROM]

    return {
        "login": int(acc["login"]),
        "balance": info.balance,
        "equity": info.equity,
        "currency": info.currency,
        "server": info.server,
        "deals": [{**d, "time": d["time"].isoformat()} for d in deals],
        "command_done": done,       # сервер снимет команду после выполнения
    }


def only_one_copy() -> socket.socket:
    """Терминал MT5 один на всех: два агента будут переключать его друг у друга
    и читать чужие счета. Держим занятым локальный порт как признак запуска."""
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        guard.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        raise SystemExit("агент уже запущен — второй не нужен, он будет мешать первому")
    return guard


def main():
    if not TOKEN:
        raise SystemExit("не задан WEBHOOK_TOKEN — агент не сможет авторизоваться")
    lock = only_one_copy()      # держим до конца работы
    log.info("агент запущен, сервер %s, круг раз в %d с", SERVER, INTERVAL)

    while True:
        try:
            accs = fetch_accounts()
        except Exception as e:
            log.warning("не получил список счетов: %s", e)
            time.sleep(INTERVAL)
            continue

        # терминал может показать окно сам: при обновлении, всплывающих
        # сообщениях брокера или после переподключения — прячем каждый круг
        trades.hide_terminal()

        ok = False
        for acc in accs:
            try:
                payload = collect(acc)
                new = push(payload)
                ok = True
                log.info("%s: отправлено %d сделок, новых %d, баланс %.2f",
                         acc["name"], len(payload["deals"]), new, payload["balance"])
            except Exception as e:
                log.warning("%s: %s", acc.get("name", "?"), e)

        if ok:      # хоть один счёт прочитан — терминал жив, отмечаемся для сторожа
            try:
                with open(BEAT, "w", encoding="utf-8") as f:
                    f.write(utcnow().isoformat())
            except Exception as e:
                log.warning("не записал отметку: %s", e)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
