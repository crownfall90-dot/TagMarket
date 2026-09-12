"""Агент: читает терминал MT5 на Windows и отправляет историю на сервер.

Нужен потому, что библиотека MetaTrader5 — мост к запущенному Windows-терминалу,
и на Linux-сервере её нет. Агент ходит на сервер сам (исходящие запросы), так что
пробрасывать порты домой не нужно.

Запуск:  python agent.py
Настройки в .env:
    AGENT_SERVER=https://crownfail.shop/tagmarkets
    WEBHOOK_TOKEN=...          — тот же токен, что у сервера
    AGENT_INTERVAL=15          — пауза между кругами, секунды

Резерв (две машины на одни и те же счета):
    AGENT_ROLE=primary|standby — по умолчанию primary (работает всегда)
    STANDBY_TIMEOUT=90         — секунд без синка отовсюду, прежде чем
                                 standby сам включится (по умолчанию)
Двух primary одновременно быть не должно: они будут выбивать друг друга
из терминала при каждом логине в один счёт. standby молчит, пока видит
через публичный /status сервера, что кто-то (primary) недавно слал данные;
включается сам, только если синк отовсюду пропал дольше STANDBY_TIMEOUT.
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

ROLE = os.getenv("AGENT_ROLE", "primary").strip().lower()
# ощутимо больше цикла синка (по умолчанию 15с) — короткая сетевая заминка
# на primary не должна включать вторую машину поверх первой
STANDBY_TIMEOUT = int(os.getenv("STANDBY_TIMEOUT", 90))


def server_alive() -> bool:
    """Кто-то (обычно primary) недавно слал данные на сервер.

    Смотрим /status — тот же публичный эндпоинт, что использует пульт
    управления. Он не привязан к конкретной машине: агенту не нужно знать
    про другую машину напрямую, достаточно видеть общий признак «синк идёт».

    Берём готовый sync_seconds_ago, посчитанный на сервере его же часами —
    не вычисляем разность сами из last_sync и своего utcnow(). Часы агентской
    машины и сервера ничем не синхронизированы: если агент спешит хотя бы на
    STANDBY_TIMEOUT, он решил бы, что синк устарел, и включился поверх живого
    primary — оба агента одновременно ломятся в один MT5-логин.

    Сетевая ошибка тут — не повод включаться: считаем, что кто-то жив, и
    подождём следующего круга, а не бросаемся занимать терминал вслепую.
    """
    try:
        r = requests.get(f"{SERVER}/status", timeout=15)
        r.raise_for_status()
        data = r.json()
        ago = data.get("sync_seconds_ago")
        if ago is not None:
            return ago < STANDBY_TIMEOUT
        # старый сервер без sync_seconds_ago (до обновления) — считаем сами,
        # хуже часов агента опоры всё равно нет
        last = data.get("last_sync")
        if not last:
            return False
        age = (utcnow() - datetime.fromisoformat(last)).total_seconds()
        return age < STANDBY_TIMEOUT
    except Exception as e:
        log.warning("не проверил /status: %s — считаю, что кто-то жив", e)
        return True


# Ключи, которые машина решает сама — сервер их не присылает и не должен
# перезаписывать, иначе AGENT_ROLE=standby одной машины стёрло бы роль другой
_LOCAL_ENV_KEYS = ("MT5_TERMINAL", "AGENT_ROLE", "STANDBY_TIMEOUT", "AGENT_LOCK_PORT")
ENV_FILE = os.getenv("ENV_FILE", os.path.join(ROOT, ".env"))
ENV_SYNC_EVERY = int(os.getenv("ENV_SYNC_EVERY", 600))     # раз в 10 минут — токены меняются редко


def sync_env() -> None:
    """Подтягивает общие настройки (токены, доли) с сервера в локальный .env.

    Так смену WEBHOOK_TOKEN или INVESTOR_SHARE не нужно вручную повторять на
    каждой агентской машине. Машинно-специфичные строки (путь к терминалу,
    роль primary/standby) не трогаем — сервер их и не присылает.
    """
    try:
        r = requests.get(f"{SERVER}/agent/env", params={"token": TOKEN}, timeout=15)
        r.raise_for_status()
        remote = r.json()
    except Exception as e:
        log.warning("не подтянул общие настройки: %s", e)
        return
    if not remote:
        return

    try:
        with open(ENV_FILE, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        lines = []

    kept = [l for l in lines if not any(
        l.startswith(k + "=") for k in remote if k not in _LOCAL_ENV_KEYS)]
    changed = [f"{k}={v}" for k, v in remote.items() if k not in _LOCAL_ENV_KEYS]
    new_lines = kept + changed
    if new_lines != lines:
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
        log.info("общие настройки обновлены с сервера (%d ключей)", len(changed))
        load_dotenv(ENV_FILE, override=True)


def notify_role_change(became: str) -> None:
    """Сообщить серверу о смене роли — сам Telegram-токен агенту не нужен,
    сервер уже держит его для всех остальных уведомлений и разошлёт сам."""
    try:
        requests.post(f"{SERVER}/agent/role_change",
                      json={"host": socket.gethostname(), "became": became},
                      headers={"X-Token": TOKEN}, timeout=15)
    except Exception as e:
        log.warning("не сообщил серверу о смене роли: %s", e)


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

    # Капитал из истории: складываем все пополнения и выводы капитала с самого
    # открытия счёта. Терминал хранит их полностью, а на сервере история
    # обрезана — поэтому считаем здесь и присылаем готовое число. Так капитал
    # не приходится вводить руками, и он не путается с прибылью в балансе.
    try:
        capital_hist = trades._capital_moves(datetime(2000, 1, 1))
    except Exception as e:
        log.warning("не посчитал капитал по истории: %s", e)
        capital_hist = None

    return {
        "login": int(acc["login"]),
        "balance": info.balance,
        "capital_hist": capital_hist,
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
    log.info("агент запущен (роль: %s), сервер %s, круг раз в %d с", ROLE, SERVER, INTERVAL)

    # None = роль ещё не определялась (первый круг); дальше True — в резерве,
    # False — активен. Уведомляем сервер только на смене None->False->True
    # или None->True->False, а не на самом первом определении роли: обычный
    # старт standby — это не авария, тревожить незачем
    standing_by = None
    last_env_sync = 0.0
    while True:
        # раз в ENV_SYNC_EVERY, а не каждый круг — токены меняются редко,
        # незачем дёргать сервер лишним запросом каждые 15 секунд
        if time.monotonic() - last_env_sync > ENV_SYNC_EVERY:
            sync_env()
            last_env_sync = time.monotonic()

        if ROLE == "standby" and server_alive():
            if standing_by is not True:
                log.info("резерв: синк идёт с другой машины, жду молча")
                if standing_by is False:      # реальный переход, не первый запуск
                    notify_role_change("standby")
                standing_by = True
            time.sleep(INTERVAL)
            continue
        if standing_by is True:
            log.warning("резерв: синк отовсюду пропал (>%d с) — включаюсь", STANDBY_TIMEOUT)
            notify_role_change("active")
        standing_by = False

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
