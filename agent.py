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

Автообновление (канареечный деплой между машинами):
    AUTO_UPDATE=1              — включено по умолчанию, 0/false выключает
    UPDATE_CHECK_EVERY=900     — как часто проверять GitHub, секунды
    CANARY_DELAY=1800          — сколько reserv должен проработать на новом
                                 коде без сбоев, прежде чем обновится primary
standby подтягивает новый коммит из GIT_REMOTE/GIT_BRANCH сразу (git fetch +
reset --hard) и перезапускает себя — он не в терминале, риск минимален.
primary ждёт, пока тот же коммит не проходит CANARY_DELAY на standby (сервер
хранит это в /agent/update_status, машины друг про друга напрямую не знают).
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

# Вспомогательные консольные утилиты (git, taskkill) при запуске из-под pythonw
# окна не создают сами по себе, но если агент когда-нибудь запущен из-под
# обычного python.exe (или из планировщика с видимой консолью) — каждый такой
# вызов на миг мигает своим чёрным окном. CREATE_NO_WINDOW глушит это всегда,
# независимо от того, как запущен сам агент — не мешает другим процессам
# компьютера и не отвлекает пользователя.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0     # CREATE_NO_WINDOW


def _quiet_run(args, **kw):
    import subprocess
    kw.setdefault("creationflags", 0)
    kw["creationflags"] |= _NO_WINDOW
    return subprocess.run(args, **kw)


def _quiet_popen(args, **kw):
    import subprocess
    kw.setdefault("creationflags", 0)
    kw["creationflags"] |= _NO_WINDOW
    return subprocess.Popen(args, **kw)

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
        r = requests.get(f"{SERVER}/agent/env", headers={"X-Token": TOKEN}, timeout=15)
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
        _reload_config()


def _reload_config() -> None:
    """Перечитывает уже связанные модульные константы после load_dotenv.

    os.environ обновляется сам, но SERVER/TOKEN/INTERVAL/HISTORY_FROM здесь
    и SHARE/BROKER_FEE/REPORT_FROM/TZ_HOURS в trades.py были прочитаны один
    раз при импорте — без этого смена токена или доли брокера долетала бы
    только до .env на диске, а реально агент продолжал бы работать по
    старым числам до ручного перезапуска процесса.
    """
    global SERVER, TOKEN, INTERVAL, HISTORY_FROM
    SERVER = os.getenv("AGENT_SERVER", "https://crownfail.shop/tagmarkets").rstrip("/")
    TOKEN = os.getenv("WEBHOOK_TOKEN", "")
    INTERVAL = int(os.getenv("AGENT_INTERVAL", 15))
    HISTORY_FROM = datetime.fromisoformat(os.getenv("HISTORY_FROM", "2026-06-01"))
    trades._load_config()


# Автообновление кода: канареечный деплой между двумя агентскими машинами.
# standby не занимает терминал, поэтому обновляется сразу же и безопасно;
# primary ждёт, пока standby не проработает на новом коде CANARY_DELAY
# секунд без сбоев (подтверждается через сервер, не напрямую между машинами —
# агенты друг про друга ничего не знают, кроме общего /status).
AUTO_UPDATE = os.getenv("AUTO_UPDATE", "1") not in ("0", "false", "no")
UPDATE_CHECK_EVERY = int(os.getenv("UPDATE_CHECK_EVERY", 900))     # раз в 15 минут
CANARY_DELAY = int(os.getenv("CANARY_DELAY", 1800))                # 30 минут пробега на standby
GIT_REMOTE = os.getenv("GIT_REMOTE", "origin")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")


def _run_git(*args, timeout=30) -> str:
    r = _quiet_run(["git", *args], cwd=ROOT, capture_output=True,
                   text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def _remote_commit() -> str | None:
    """Хэш HEAD в GitHub — git fetch (не reset), чтобы дальше можно было
    прочитать сообщение этого коммита локально (_remote_commit_host)."""
    try:
        _run_git("fetch", GIT_REMOTE, GIT_BRANCH, timeout=60)
        return _run_git("rev-parse", f"{GIT_REMOTE}/{GIT_BRANCH}") or None
    except Exception as e:
        log.warning("не проверил обновления в git: %s", e)
        return None


def _remote_commit_host(commit: str) -> str | None:
    """Значение Origin-Host: из трейлера коммита, если он его содержит.

    Коммит с этой машины (и с той, что сейчас его сделала) несёт свой
    hostname в trailer'е — так агент отличает «это мой пуш, обновляюсь
    сразу» от «пуш пришёл откуда-то ещё, жду обычную канареечную задержку».
    Коммит без такой строки (например, сделанный не через это соглашение)
    просто не даёт немедленного пути — обычная задержка применится и тут.

    Ищем только в последнем абзаце (трейлеры всегда там, без пустых строк
    внутри) — иначе revert/cherry-pick/цитата чужого коммита в теле подставили
    бы чужой hostname, и не та машина обновилась бы без всякой обкатки.
    """
    try:
        msg = _run_git("log", "-1", "--format=%B", commit)
    except Exception:
        return None
    trailer = msg.strip().split("\n\n")[-1]
    for line in trailer.splitlines():
        if line.startswith("Origin-Host:"):
            return line.split(":", 1)[1].strip()
    return None


def _local_commit() -> str | None:
    try:
        return _run_git("rev-parse", "HEAD")
    except Exception as e:
        log.warning("не прочитал текущий коммит: %s", e)
        return None


def _canary_age(commit: str) -> float | None:
    """Сколько секунд назад standby впервые отчитался об этом коммите (по данным сервера)."""
    try:
        r = requests.get(f"{SERVER}/agent/update_status", params={"commit": commit},
                         headers={"X-Token": TOKEN}, timeout=15)
        r.raise_for_status()
        return r.json().get("canary_age_seconds")
    except Exception as e:
        log.warning("не проверил статус канарейки: %s", e)
        return None


def report_canary(commit: str) -> None:
    """standby отчитывается серверу: жив и работает на таком-то коммите."""
    try:
        requests.post(f"{SERVER}/agent/update_report",
                      json={"host": socket.gethostname(), "commit": commit},
                      headers={"X-Token": TOKEN}, timeout=15)
    except Exception as e:
        log.warning("не отчитался о коммите: %s", e)


def send_heartbeat() -> None:
    """Отмечаемся живыми, пока ждём в резерве и не шлём agent/sync.

    Без этого сервер не знал бы hostname машины, которая просто молча
    стоит наготове — machines_watchdog в bot.py не увидел бы её вовсе.
    """
    try:
        requests.post(f"{SERVER}/agent/heartbeat",
                      json={"host": socket.gethostname()},
                      headers={"X-Token": TOKEN}, timeout=15)
    except Exception as e:
        log.warning("не отправил heartbeat: %s", e)


def check_for_update(lock: socket.socket) -> None:
    """Раз в UPDATE_CHECK_EVERY проверяет GitHub и обновляется, если можно.

    Три пути, по возрастанию осторожности:
    1. Машина, с которой коммит запушили (Origin-Host в трейлере коммита
       совпадает с её hostname), обновляется сразу — её только что явно
       попросили это сделать.
    2. standby не держит терминал (просто ждёт молча или шлёт heartbeat) —
       обновляется сразу же следом, без задержки: рисковать нечем, а кто-то
       ведь должен реально погонять новый код, прежде чем на него перейдёт
       primary.
    3. primary (не источник) ждёт CANARY_DELAY секунд, за которые standby
       должен отчитаться о работе именно на этом коммите без сбоев — только
       так у canary_age вообще появляется ненулевое значение. Раньше все
       не-standby и не-источники ждали одинаково, и коммит с третьей машины
       (не primary и не standby) не мог обновить никого: некому было стать
       канарейкой первым — дедлок.

    Не поднимаем tools/keeper.ps1 самостоятельно: перезапуск через новый
    процесс + выход из этого — сторож (если настроен) просто увидит живой
    agent.beat и не вмешается; если сторожа нет, задача планировщика,
    которая изначально запустила агент, никак не пострадает — сам процесс
    просто сменился.
    """
    remote = _remote_commit()
    if not remote:
        return
    local = _local_commit()
    if not local or local == remote:
        return      # уже на актуальном коде — или git недоступен, не рискуем

    if _remote_commit_host(remote) == socket.gethostname():
        log.info("это моя машина запушила %s -> %s — обновляюсь сразу, без задержки",
                 local[:8], remote[:8])
        _self_update_and_restart(lock, remote)
        return

    if ROLE == "standby":
        log.info("резерв: коммит %s -> %s — обновляюсь сразу, терминал не держу",
                 local[:8], remote[:8])
        _self_update_and_restart(lock, remote)
        return

    age = _canary_age(remote)
    if age is None or age < CANARY_DELAY:
        log.info("коммит %s ещё не обкатан (%s из %d с) — жду",
                 remote[:8], f"{age:.0f}" if age is not None else "не запускался",
                 CANARY_DELAY)
        return
    log.info("коммит %s %d с без сбоев — обновляюсь", remote[:8], age)
    _self_update_and_restart(lock, remote)


# Сколько новый процесс готов ждать освобождения порта от старого (передаём
# через AGENT_RESPAWN_WAIT), и сколько старый процесс минимум ждёт перед тем,
# как отпустить лок сам — раньше было фиксированных 2 секунды без всякой
# проверки, что новый процесс вообще поднялся; под IDLE-приоритетом и
# нагруженной машиной интерпретатор с импортом MetaTrader5 может стартовать
# дольше, и порт мог достаться кому-то ещё в этом окне
RESPAWN_WAIT = float(os.getenv("AGENT_RESPAWN_WAIT_SECONDS", 15))


def _self_update_and_restart(lock: socket.socket, target_commit: str) -> None:
    """git pull, запуск нового процесса, выход из текущего.

    lock (only_one_copy) закрываем только после проверки, что новый процесс
    не умер сразу — иначе машина рискует остаться совсем без агента, если
    порт в промежутке займёт что-то ещё (см. RESPAWN_WAIT).
    """
    try:
        dirty = _run_git("status", "--porcelain")
        if dirty:
            # кто-то вручную правил файлы на этой машине без коммита —
            # reset --hard стёр бы это молча и без возможности вернуть.
            # Автообновление тут не должно решать за человека
            log.warning("в рабочей копии есть незакоммиченные изменения — "
                       "автообновление пропущено, разберитесь вручную:\n%s", dirty)
            return
        _run_git("fetch", GIT_REMOTE, GIT_BRANCH, timeout=60)
        _run_git("reset", "--hard", f"{GIT_REMOTE}/{GIT_BRANCH}", timeout=30)
    except Exception as e:
        log.error("обновление не удалось, остаюсь на текущем коде: %s", e)
        return

    _offer_console_free_setup()

    log.info("код обновлён до %s, перезапускаюсь", target_commit[:8])
    try:
        import subprocess
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        child_env = dict(os.environ, AGENT_RESPAWN_WAIT=str(RESPAWN_WAIT))
        proc = _quiet_popen([pythonw, os.path.join(ROOT, "agent.py")], cwd=ROOT, env=child_env,
                            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    except Exception as e:
        log.error("не запустил новый процесс, остаюсь на старом коде до ручного рестарта: %s", e)
        return

    # держим порт занятым, пока сами не убедимся, что новый процесс жив —
    # закрывать раньше и слепо ждать бессмысленно: если он уже упал, лучше
    # остаться на старом коде, чем оставить машину вообще без агента
    time.sleep(3)
    if proc.poll() is not None:
        log.error("новый процесс сразу завершился (код %s) — остаюсь на старом коде "
                  "до ручного разбора", proc.poll())
        return
    lock.close()
    log.info("новый процесс запущен и жив, этот завершается")
    sys.exit(0)


# Отметка, чтобы предлагать переключение задачи на бесконсольный запуск не
# при каждом автообновлении, а один раз за всё время жизни этой машины —
# после первого переключения (или отказа пользователя) файл остаётся как
# памятка, что вопрос уже решён
_CONSOLE_FREE_MARKER = os.path.join(ROOT, "data", ".console_free_offered")


def _offer_console_free_setup() -> None:
    """Разово, при первом автообновлении на новом коде, проверяет — не
    запускает ли эта машина ещё старый run_agent.bat (тот на миг показывает
    окно cmd.exe) — и если да, предлагает пользователю UAC-запрос на
    переключение задачи планировщика на run_agent.vbs (без окна вообще).

    Сам агент работает не от администратора, поэтому тихо и незаметно
    поменять задачу планировщика нельзя — Set-ScheduledTask откажет.
    Единственный способ не мешать пользователю молчаливым сбоем — честно
    попросить один раз через системный UAC-диалог, который пользователь
    либо примет, либо отклонит; в обоих случаях повторно не спрашиваем.

    Осознанный компромисс: механизм автообновления и так означает, что
    любой, кто может запушить в GIT_REMOTE/GIT_BRANCH, получает выполнение
    произвольного кода от имени пользователя агента — это не новая дыра.
    Но именно этот UAC-запрос приучает пользователя воспринимать неожиданное
    окно с запросом прав администратора как нормальное поведение агента —
    при компрометации репозитория tools/setup_console_free.ps1 можно
    подменить, и пользователь, уже привыкший жать «да», молча даст код
    выполниться от администратора. Защиты от этого сценария на уровне кода
    нет — только у того, кто имеет доступ на запись в git-репозиторий,
    и так уже есть выполнение кода от пользователя; повышение до
    администратора требует его же осознанного клика на реальном экране.
    """
    if os.name != "nt" or os.path.exists(_CONSOLE_FREE_MARKER):
        return
    setup_script = os.path.join(ROOT, "tools", "setup_console_free.ps1")
    if not os.path.exists(setup_script):
        return

    # отметку ставим только когда реально дошли до решения (задачи нет, уже
    # переключена, или предложение реально показано) — если проверка ниже
    # оборвётся временной ошибкой (PowerShell не успел стартовать, WMI
    # запнулся и т.п.), пользователя ничего не спросили, и лучше повторить
    # попытку при следующем автообновлении, чем молча похоронить её навсегда
    def _mark_done() -> None:
        try:
            os.makedirs(os.path.dirname(_CONSOLE_FREE_MARKER), exist_ok=True)
            with open(_CONSOLE_FREE_MARKER, "w", encoding="utf-8") as f:
                f.write(utcnow().isoformat())
        except Exception as e:
            log.warning("не создал отметку про предложение бесконсольной настройки: %s", e)

    try:
        out = _quiet_run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-ScheduledTask -TaskName TagMarketsAgent -ErrorAction "
             "SilentlyContinue).Actions.Execute"],
            capture_output=True, text=True, timeout=15).stdout.strip().lower()
        if not out or "wscript" in out:
            _mark_done()     # задачи нет или уже переключена — предлагать нечего
            return
    except Exception as e:
        log.warning("не проверил конфигурацию задачи планировщика, попробую при "
                   "следующем обновлении: %s", e)
        return    # без _mark_done(): это не решение, а сбой проверки

    log.info("задача планировщика ещё использует .bat (мелькает окно консоли) — "
             "предлагаю пользователю переключить на бесконсольный запуск (UAC)")
    try:
        import subprocess
        # тут окно консоли — не баг, а необходимость: сам setup-скрипт
        # спрашивает пользователя (y/n) перед запросом UAC, и это единственный
        # осмысленный случай во всём агенте, где окно должно быть видимым
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", setup_script],
            cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE)
        _mark_done()    # предложение показано — больше не спрашиваем, независимо от ответа
    except Exception as e:
        log.warning("не запустил предложение бесконсольной настройки, попробую при "
                   "следующем обновлении: %s", e)


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
    r = requests.get(f"{SERVER}/agent/accounts", headers={"X-Token": TOKEN}, timeout=30)
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
            _quiet_run(["taskkill", "/F", "/IM", "terminal64.exe"],
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
        # "host" пока не шлём: на сервере ещё старый webhook_server.py, который
        # не ждёт это поле и падает 500-й на каждый /agent/sync (проверено
        # напрямую: тот же payload без host отвечает 200). У сервера нет
        # автодеплоя (в отличие от агентов), поэтому рассинхрон код/сервер тут
        # не самообновится сам — вернуть после ручного деплоя на VPS.
    }


def only_one_copy(retry_seconds: float = 0) -> socket.socket:
    """Терминал MT5 один на всех: два агента будут переключать его друг у друга
    и читать чужие счета. Держим занятым локальный порт как признак запуска.

    retry_seconds > 0 — для процесса, запущенного самообновлением: старый
    процесс мог ещё не успеть освободить порт (сложный интерпретатор,
    занятая машина под IDLE-приоритетом стартует не мгновенно), и вместо
    немедленной смерти новый процесс недолго подождёт освобождения сам.
    """
    deadline = time.monotonic() + retry_seconds
    while True:
        guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            guard.bind(("127.0.0.1", LOCK_PORT))
            return guard
        except OSError:
            guard.close()
            if time.monotonic() >= deadline:
                raise SystemExit("агент уже запущен — второй не нужен, он будет мешать первому")
            time.sleep(0.5)


def _run_quietly() -> None:
    """Самый низкий приоритет для самого агента — он лишь дёргает терминал
    и шлёт HTTP-запросы раз в несколько секунд, процессору пользователя
    это не должно быть заметно вообще, даже под большой нагрузкой."""
    if os.name != "nt":
        return
    try:
        import ctypes
        IDLE_PRIORITY_CLASS = 0x00000040
        PROCESS_MODE_BACKGROUND_BEGIN = 0x00100000
        h = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(h, IDLE_PRIORITY_CLASS)
        ctypes.windll.kernel32.SetPriorityClass(h, PROCESS_MODE_BACKGROUND_BEGIN)
    except Exception as e:
        log.warning("не понизил приоритет агента: %s", e)


# Игра не должна замечать агента вообще: ни лишней нагрузки, ни тем более
# мелькающего окна консоли при alt-tab или сворачивании. Но правило именно
# такое, как попросили: мешает только игра В ФОКУСЕ и на весь экран —
# свёрнутая или в оконном режиме игра агенту не мешает, можно опрашивать.
#
# SHQueryUserNotificationState (QUNS_RUNNING_D3D_FULL_SCREEN) казался бы
# готовым решением, но на практике ложно срабатывает от любого фонового D3D-
# рендера — например, Wallpaper Engine (живые обои) держит этот флаг
# постоянно включённым, даже когда активна обычная программа на рабочем
# столе. Проверено на реальной машине: пока в фокусе был редактор кода,
# а не игра, флаг всё равно стоял «полноэкранная игра». Полагаться на него
# нельзя — агент бы никогда не запускался.
#
# Вместо системного флага — окно переднего плана реально ли занимает весь
# экран без рамки (так рисуют игры в exclusive/borderless fullscreen) И
# принадлежит известному игровому процессу или просто безрамочное на весь
# экран. Отдельно, независимо — общая загрузка CPU уже высокая сама по себе:
# если что-то и так забирает почти весь процессор, неважно, игра это или нет.
_GAME_CHECK_EVERY = int(os.getenv("GAME_CHECK_EVERY", 20))     # секунд между проверками
_last_game_check = 0.0
_last_game_state = False

# По имени процесса — известные игры/лаунчеры, которые пользователь сам
# назвал (CS:GO/CS2 и похожие). Учитываются только если такой процесс СЕЙЧАС
# в фокусе — свёрнутый Steam или CS2 в фоне агенту не мешает.
_HEAVY_FOREGROUND_PROCESSES = {
    "cs2.exe", "csgo.exe", "hl2.exe", "steam.exe",
    "faceitclient.exe", "faceitservice.exe",
    "dota2.exe", "valorant.exe", "valorant-win64-shipping.exe",
    "riotclientservices.exe", "fortniteclient-win64-shipping.exe",
    "gta5.exe", "eafc24.exe", "r5apex.exe",
}


def heavy_process_running() -> bool:
    """Игра в полноэкранном фокусе (или другая тяжёлая нагрузка на CPU)
    сейчас идёт — агенту сюда не лезть. Свёрнутая игра не в счёт. Кэшируем
    на _GAME_CHECK_EVERY секунд: измерение CPU занимает время, незачем
    делать его каждый круг."""
    global _last_game_check, _last_game_state
    if os.name != "nt":
        return False
    now = time.monotonic()
    if now - _last_game_check < _GAME_CHECK_EVERY:
        return _last_game_state
    _last_game_check = now
    _last_game_state = _foreground_is_heavy() or _cpu_saturated()
    return _last_game_state


def _foreground_is_heavy() -> bool:
    """Активное окно — игра/лаунчер по имени процесса, или реально
    безрамочное окно на весь экран (типичный fullscreen-рендер игры).
    Оба признака про окно ПЕРЕДНЕГО ПЛАНА — свёрнутая игра тут не всплывёт."""
    try:
        import ctypes
        from ctypes import wintypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False

        name = ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if h:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value).lower()
            kernel32.CloseHandle(h)

        if name in _HEAVY_FOREGROUND_PROCESSES:
            return True

        # безрамочное окно ровно по границам экрана — типичный fullscreen игры;
        # обычные окна (даже развёрнутые) оставляют системную рамку/панель задач
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        sw = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        sh = user32.GetSystemMetrics(1)   # SM_CYSCREEN
        covers_screen = (rect.left <= 0 and rect.top <= 0
                        and rect.right >= sw and rect.bottom >= sh)
        if not covers_screen:
            return False
        # explorer.exe (рабочий стол/панель задач) тоже иногда «во весь экран» —
        # не считаем игрой
        return name not in ("", "explorer.exe", "shellexperiencehost.exe",
                            "searchhost.exe", "textinputhost.exe")
    except Exception as e:
        log.warning("не проверил активное окно: %s", e)
        return False


def _cpu_saturated(threshold: float = 90.0) -> bool:
    """Игра иногда не эксклюзивно-полноэкранная (оконный режим, alt-tab
    выключен), но грузит процессор так же сильно — тогда ловим по нагрузке.
    Без psutil: считаем по системным счётчикам времени самой Windows.
    """
    try:
        import ctypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

        def _to_int(ft):
            return (ft.high << 32) | ft.low

        idle1, kernel1, user1 = FILETIME(), FILETIME(), FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle1), ctypes.byref(kernel1), ctypes.byref(user1))
        time.sleep(0.2)     # короткая выборка — не задерживаем цикл агента
        idle2, kernel2, user2 = FILETIME(), FILETIME(), FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle2), ctypes.byref(kernel2), ctypes.byref(user2))

        idle_delta = _to_int(idle2) - _to_int(idle1)
        total_delta = (_to_int(kernel2) + _to_int(user2)) - (_to_int(kernel1) + _to_int(user1))
        if total_delta <= 0:
            return False
        busy_pct = 100.0 * (1 - idle_delta / total_delta)
        return busy_pct >= threshold
    except Exception as e:
        log.warning("не измерил загрузку процессора: %s", e)
        return False


def main():
    if not TOKEN:
        raise SystemExit("не задан WEBHOOK_TOKEN — агент не сможет авторизоваться")
    _run_quietly()
    # после самообновления старый процесс мог ещё держать порт — недолго
    # подождём вместо мгновенной смерти (см. RESPAWN_WAIT в _self_update_and_restart)
    retry = float(os.environ.pop("AGENT_RESPAWN_WAIT", 0) or 0)
    lock = only_one_copy(retry_seconds=retry)      # держим до конца работы
    log.info("агент запущен (роль: %s), сервер %s, круг раз в %d с", ROLE, SERVER, INTERVAL)

    # None = роль ещё не определялась (первый круг); дальше True — в резерве,
    # False — активен. Уведомляем сервер только на смене None->False->True
    # или None->True->False, а не на самом первом определении роли: обычный
    # старт standby — это не авария, тревожить незачем
    standing_by = None
    took_over = False   # резерв реально включался — обратно в ожидание больше не переходит
    gaming_paused = False
    last_env_sync = 0.0
    last_update_check = 0.0
    last_canary_report = 0.0
    # закэшировано на весь процесс: код меняется только через рестарт после
    # обновления, так что local-commit и «свой ли это коммит» не меняются
    # между запусками git заново на каждый круг
    canary_commit = _local_commit() if AUTO_UPDATE else None
    is_own_commit = (canary_commit and AUTO_UPDATE
                     and _remote_commit_host(canary_commit) == socket.gethostname())
    while True:
        # раз в ENV_SYNC_EVERY, а не каждый круг — токены меняются редко,
        # незачем дёргать сервер лишним запросом каждые 15 секунд
        if time.monotonic() - last_env_sync > ENV_SYNC_EVERY:
            sync_env()
            last_env_sync = time.monotonic()

        if AUTO_UPDATE and time.monotonic() - last_update_check > UPDATE_CHECK_EVERY:
            check_for_update(lock)     # обновится и выйдет сама, если можно
            last_update_check = time.monotonic()

        # Канарейка: любая машина, которая НЕ источник текущего коммита,
        # подтверждает серверу, что она на нём работает и не падает — не
        # только standby в ожидании, а вообще любое живое состояние (в том
        # числе активная работа с терминалом). Источник сам себя не
        # репортует — обкатка нужна именно на другой машине
        if (AUTO_UPDATE and canary_commit and not is_own_commit
                and time.monotonic() - last_canary_report > INTERVAL):
            report_canary(canary_commit)
            last_canary_report = time.monotonic()

        # took_over: как только резерв реально взял управление, обратно не
        # оглядываемся. server_alive() смотрит на sync_seconds_ago по ВСЕМ
        # машинам без разбора, чей это синк — а раз мы сами теперь синкуем
        # каждый круг, он всегда видит «кто-то жив только что» и без этой
        # защёлки резерв включался и выключался бы каждые ~STANDBY_TIMEOUT
        # секунд, дублируя уведомления о смене роли и синкуя реже, чем надо.
        if ROLE == "standby" and not took_over and server_alive():
            if standing_by is not True:
                log.info("резерв: синк идёт с другой машины, жду молча")
                if standing_by is False:      # реальный переход, не первый запуск
                    notify_role_change("standby")
                standing_by = True
            send_heartbeat()
            time.sleep(INTERVAL)
            continue
        if standing_by is True:
            log.warning("резерв: синк отовсюду пропал (>%d с) — включаюсь насовсем "
                       "(до перезапуска)", STANDBY_TIMEOUT)
            notify_role_change("active")
            took_over = True
        standing_by = False

        # игра в полноэкранном фокусе (или другая тяжёлая нагрузка) — терминал
        # сейчас не трогаем вообще: ни лишней нагрузки на CPU/GPU, ни риска,
        # что MT5 всплывёт окном или мигнёт консоль при alt-tab/сворачивании.
        # Как только игра свернётся или закроется, следующий круг отработает
        # как обычно — задержка в несколько секунд для уведомлений не критична
        is_heavy = heavy_process_running()
        if is_heavy and not gaming_paused:
            log.info("на переднем плане игра/тяжёлый процесс — опрос терминала приостановлен")
            gaming_paused = True
        elif not is_heavy and gaming_paused:
            log.info("тяжёлый процесс закрыт/свёрнут — опрос терминала возобновлён")
            gaming_paused = False
        if is_heavy:
            time.sleep(INTERVAL)
            continue

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
