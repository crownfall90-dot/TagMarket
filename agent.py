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
    AGENT_ROLE=primary|standby — роль машины, по умолчанию primary
    STANDBY_TIMEOUT=90         — секунд без синка отовсюду, прежде чем
                                 standby сам включится (по умолчанию)
Сервер выдаёт одному процессу исключительное право опроса на 180 секунд.
Его продлевает успешная передача данных. Остальные машины ждут, даже если
роль primary. Вернувшаяся машина не вытесняет исправно работающую резервную.
STANDBY_TIMEOUT оставлен для совместимости старого диагностического метода.

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
import re
import socket
import sys
import time
import uuid
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
# отметка «главный цикл жив» — её читает сторож keeper.ps1 на ПК: если
# отметке ≥3 минут или процесса нет, сторож перезапускает агента (раньше,
# чем на 5-й минуте сработает уведомление сервера). Обновляется и когда
# терминал реально опрошен, и когда цикл осознанно его не трогает (резерв
# ждёт) — иначе сторож принимал бы штатную паузу за зависший процесс и
# убивал агента прямо посреди неё
BEAT = os.path.join(ROOT, "data", "agent.beat")


def _touch_beat() -> None:
    try:
        with open(BEAT, "w", encoding="utf-8") as f:
            f.write(utcnow().isoformat())
    except Exception as e:
        log.warning("не записал отметку: %s", e)

ROLE = os.getenv("AGENT_ROLE", "primary").strip().lower()
SESSION = uuid.uuid4().hex


def claim_terminal() -> bool:
    """Never touch MT5 without an exclusive server-issued polling lease.

    A recovered primary waits for the current owner; no automatic preemption.
    Network errors and an older server both fail closed.
    """
    try:
        response = requests.post(f"{SERVER}/agent/claim", headers={"X-Token": TOKEN},
                                 json={"host": socket.gethostname(), "session": SESSION,
                                       "role": ROLE}, timeout=15)
        response.raise_for_status()
        return response.json().get("granted") is True
    except Exception as exc:
        log.warning("не получил право опроса терминала: %s", exc)
        return False
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
    прочитать сообщение этого коммита локально (_remote_commit_host).

    Таймаут короче, чем раньше (20с вместо 60с): при сетевой перегрузке эта
    проверка и так повторится сама через UPDATE_CHECK_EVERY — незачем
    держать процесс минуту в ожидании одной попытки, которая уже видна как
    маловероятная (тот же принцип, что и в _retry_request для agent/sync)."""
    try:
        _run_git("fetch", GIT_REMOTE, GIT_BRANCH, timeout=20)
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

    Ищем только в трейлере — иначе revert/cherry-pick/цитата чужого коммита
    в теле подставили бы чужой hostname, и не та машина обновилась бы без
    всякой обкатки. Трейлер — это последние строки, которые выглядят как
    "Key: value"; идём с конца сообщения и останавливаемся на первой строке,
    что не похожа на трейлер. Пустая строка сама по себе не обрывает поиск —
    Co-Authored-By пишется отдельным абзацем от Origin-Host, и разбивка по
    "\n\n" на последний абзац теряла Origin-Host целиком.
    """
    try:
        msg = _run_git("log", "-1", "--format=%B", commit)
    except Exception:
        return None
    trailer_re = re.compile(r"^[A-Za-z][A-Za-z0-9-]*:\s")
    trailer_lines = []
    for line in reversed(msg.rstrip().splitlines()):
        if not line.strip():
            continue                # пустая строка внутри трейлера — не обрыв
        if not trailer_re.match(line):
            break                   # первая не-трейлерная строка — конец области
        trailer_lines.append(line)
    for line in trailer_lines:
        if line.startswith("Origin-Host:"):
            return line.split(":", 1)[1].strip()
    return None


def _local_commit() -> str | None:
    try:
        return _run_git("rev-parse", "HEAD")
    except Exception as e:
        log.warning("не прочитал текущий коммит: %s", e)
        return None


# --- Автоматический откат плохого обновления -------------------------------
#
# _self_update_and_restart() уже ловит мгновенный краш нового процесса (первые
# несколько секунд) и в этом случае просто не переключается на новый код —
# но так же новый код может пережить эти секунды и упасть позже, уже во время
# реальной работы с терминалом (например, ошибка в первом же цикле fetch_accounts
# или collect). Эту ситуацию ловит уже следующий запуск: если PENDING_COMMIT_FILE
# существует и указывает на коммит, совпадающий с текущим HEAD, значит прошлый
# запуск на этом коммите не успел подтвердить себя (см. _confirm_update_ok) —
# откатываемся на LAST_GOOD_COMMIT_FILE прежде чем начинать реальную работу.
#
# ВАЖНО: pending пишется ДО того, как _self_update_and_restart() запускает
# новый процесс — а значит именно ЭТОТ новый процесс при своём первом же
# старте видит pending == HEAD, что нормально и ожидаемо (это его собственное,
# только что начавшееся обновление, а не чей-то чужой сбой). Поэтому откат не
# может срабатывать по самому факту совпадения — только если с момента
# записи pending прошло МИНИМУМ MIN_CONFIRM_GRACE секунд: этого заведомо
# достаточно на нормальный старт + первый цикл, и заведомо мало для
# легитимного «просто ещё не успел» на живой машине.
LAST_GOOD_COMMIT_FILE = os.path.join(ROOT, "data", "last_good_commit")
PENDING_COMMIT_FILE = os.path.join(ROOT, "data", "pending_commit")
MIN_CONFIRM_GRACE = float(os.getenv("MIN_CONFIRM_GRACE_SECONDS", 30))


def _read_marker(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _write_marker(path: str, value: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(value)
    except OSError as e:
        log.warning("не записал %s: %s", os.path.basename(path), e)


def _write_pending(commit: str) -> None:
    _write_marker(PENDING_COMMIT_FILE, f"{commit}|{utcnow().isoformat()}")


def _read_pending() -> tuple[str, float] | None:
    """Возвращает (commit, seconds_since_written) или None, если маркера нет
    или он в устаревшем формате без временной метки (тогда считаем его сразу
    «старым» — 0 секунд грации не бывает, safer to treat as no-marker)."""
    raw = _read_marker(PENDING_COMMIT_FILE)
    if not raw:
        return None
    commit, sep, stamp = raw.partition("|")
    if not sep:
        return None     # старый формат без метки времени — не с чем сверяться
    try:
        age = (utcnow() - datetime.fromisoformat(stamp)).total_seconds()
    except ValueError:
        return None
    return commit, age


def _check_and_rollback_bad_update(lock: socket.socket) -> bool:
    """При старте: если предыдущий запуск не подтвердил обновление — откатиться.

    Возвращает True, если откат произошёл (и уже запущен новый процесс на
    старом коде — этот процесс должен завершиться, ничего больше не начиная).
    """
    pending_info = _read_pending()
    current = _local_commit()
    if not pending_info or not current:
        return False
    pending, age = pending_info
    if pending != current:
        return False    # это не тот коммит — маркер про другое обновление
    if age < MIN_CONFIRM_GRACE:
        # это, скорее всего, тот самый процесс, который только что запустил
        # _self_update_and_restart() — дать ему шанс дойти до _confirm_update_ok()
        log.info("на новом коде %s недавно (%.0fс из %.0fс) — рано считать "
                "обновление неудавшимся, продолжаю обычный старт",
                current[:8], age, MIN_CONFIRM_GRACE)
        return False

    good = _read_marker(LAST_GOOD_COMMIT_FILE)
    if not good or good == current:
        # не на что откатываться (первый запуск вообще, или пометка совпадает
        # с текущим — деградировать в бесконечный цикл отката на себя же нельзя)
        log.error("прошлый запуск на %s не подтвердил себя, но откатываться "
                 "некуда (last_good_commit=%r) — остаюсь как есть", current[:8], good)
        return False

    log.error("прошлый запуск на %s не подтвердил себя (упал раньше первого "
             "успешного круга) — откатываюсь на последний рабочий коммит %s",
             current[:8], good[:8])
    try:
        _run_git("reset", "--hard", good, timeout=30)
    except Exception as e:
        log.error("откат не удался: %s — остаюсь на текущем (плохом) коде", e)
        return False

    try:
        _write_marker(PENDING_COMMIT_FILE, "")   # больше не «в процессе обновления»
        import subprocess
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        _quiet_popen([pythonw, os.path.join(ROOT, "agent.py")], cwd=ROOT,
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    except Exception as e:
        log.error("откатился, но не запустил процесс на старом коде — "
                 "нужен ручной перезапуск: %s", e)
        return True     # код уже откачен на диске — следующий ручной/сторожевой
                        # запуск подхватит его сам, даже если этот Popen не удался

    _report_rollback(current, good)
    lock.close()
    sys.exit(0)


def _report_rollback(bad_commit: str, good_commit: str) -> None:
    """Сообщить серверу об автоматическом откате — основателю стоит знать,
    что сама машина заметила и исправила плохое обновление."""
    try:
        requests.post(f"{SERVER}/agent/update_notify",
                      json={"host": socket.gethostname(), "commit": good_commit,
                           "rollback_from": bad_commit[:8]},
                      headers={"X-Token": TOKEN}, timeout=15)
    except Exception as e:
        log.warning("не сообщил серверу об откате: %s", e)


def _confirm_update_ok() -> None:
    """Первый успешный круг на новом коде — подтверждаем: этот коммит теперь
    last_good_commit, а pending-отметка снимается. Вызывается один раз за
    время жизни процесса, как только реальная работа с терминалом удалась
    хотя бы на одном счёте."""
    current = _local_commit()
    if not current:
        return
    _write_marker(LAST_GOOD_COMMIT_FILE, current)
    if _read_marker(PENDING_COMMIT_FILE):
        _write_marker(PENDING_COMMIT_FILE, "")


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
    Роль (ROLE) шлём тоже — так сервер знает, какой hostname «ноутбук»,
    а какой «компьютер», не храня список машин в своих настройках.
    """
    try:
        requests.post(f"{SERVER}/agent/heartbeat",
                      json={"host": socket.gethostname(), "role": ROLE},
                      headers={"X-Token": TOKEN}, timeout=15)
    except Exception as e:
        log.warning("не отправил heartbeat: %s", e)


def check_for_update(lock: socket.socket, holding_terminal: bool = False) -> None:
    """Раз в UPDATE_CHECK_EVERY проверяет GitHub и обновляется, если можно.

    Три пути, по возрастанию осторожности:
    1. Машина, с которой коммит запушили (Origin-Host в трейлере коммита
       совпадает с её hostname), обновляется сразу — её только что явно
       попросили это сделать.
    2. standby, который СЕЙЧАС реально не держит терминал (просто ждёт молча
       или шлёт heartbeat) — обновляется сразу же следом, без задержки:
       рисковать нечем, а кто-то ведь должен реально погонять новый код,
       прежде чем на него перейдёт primary. holding_terminal=True — резерв
       взял управление после отказа primary (см. took_over в main()) — тогда
       это ровно тот случай, для которого канарейка и нужна, роль в .env
       всё ещё "standby", но по факту сейчас единственная живая машина
       активно опрашивает терминал, и обновлять её без обкатки нельзя.
    3. Все остальные (primary, и holding_terminal-резерв) ждут CANARY_DELAY
       секунд, за которые НЕ держащая терминал машина должна отчитаться о
       работе именно на этом коммите без сбоев — только так у canary_age
       вообще появляется ненулевое значение. Раньше все не-standby и
       не-источники ждали одинаково, и коммит с третьей машины (не primary
       и не standby) не мог обновить никого: некому было стать канарейкой
       первым — дедлок.

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

    if ROLE == "standby" and not holding_terminal:
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

        # живой инцидент: локальный коммит, ещё не успевший на GitHub (push
        # завис из-за сетевого сбоя — git push сам не ретраит и может висеть
        # минутами), тихо стирался следующим автообновлением. git status
        # --porcelain его не ловит — файлы уже закоммичены, «грязных»
        # изменений в рабочей копии нет, только сам коммит не на origin.
        # Проверяем именно это отдельно: если origin/<branch> не является
        # предком HEAD, здесь есть история, которой нет на GitHub —
        # reset --hard её стёр бы так же молча
        _run_git("fetch", GIT_REMOTE, GIT_BRANCH, timeout=20)
        ahead = _run_git("rev-list", f"{GIT_REMOTE}/{GIT_BRANCH}..HEAD")
        if ahead:
            log.warning("локальный коммит ещё не на GitHub (git push не прошёл?) — "
                       "автообновление пропущено, чтобы не стереть его:\n%s", ahead)
            return
        # текущий код уже дошёл сюда — значит он стабилен (иначе процесс не
        # выжил бы, чтобы дойти до планового автообновления). Запоминаем его
        # как последний рабочий ПЕРЕД переключением — это и есть то, куда
        # _check_and_rollback_bad_update откатится, если новый код окажется плохим
        current = _local_commit()
        if current:
            _write_marker(LAST_GOOD_COMMIT_FILE, current)
        # fetch уже свежий (см. проверку ahead выше) — второй раз дёргать
        # сеть незачем, это просто лишний риск нового таймаута
        _run_git("reset", "--hard", f"{GIT_REMOTE}/{GIT_BRANCH}", timeout=30)
        _write_pending(target_commit)
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
    notify_update(target_commit)
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
                      json={"host": socket.gethostname(), "session": SESSION, "became": became},
                      headers={"X-Token": TOKEN}, timeout=15)
    except Exception as e:
        log.warning("не сообщил серверу о смене роли: %s", e)


def notify_update(commit: str) -> None:
    """Сообщить серверу, что эта машина подтянула новый код и перезапустилась.

    Сервер сам решает, слать ли это основателю в Telegram (настройка
    update_alerts в боте) — агенту про неё знать не нужно."""
    try:
        requests.post(f"{SERVER}/agent/update_notify",
                      json={"host": socket.gethostname(), "commit": commit},
                      headers={"X-Token": TOKEN}, timeout=15)
    except Exception as e:
        log.warning("не сообщил серверу об обновлении: %s", e)


def _retry_request(fn, *, retries: int = 3, backoff: float = 3.0):
    """До нескольких коротких попыток вместо одной длинной.

    Живой инцидент показал: игра (даже свёрнутая, не в фокусе — по нашим же
    правилам это не должно её трогать вообще) может забивать канал не одним
    коротким всплеском, а затяжными периодами в десятки секунд. Один быстрый
    повтор после длинного (60с) таймаута почти ничего не давал — вторая
    попытка стартовала уже внутри того же перегруженного окна и падала так
    же. Короткий таймаут (10с на попытку) с несколькими повторами и
    растущей паузой между ними эффективнее: не ждём впустую там, где сеть
    явно не отвечает, и даём каналу больше шансов освободиться к следующей
    попытке, вместо одной ставки на удачу.
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    raise last_exc


def fetch_accounts() -> list[dict]:
    def _do():
        r = requests.get(f"{SERVER}/agent/accounts", headers={"X-Token": TOKEN,
                         "X-Agent-Host": socket.gethostname(), "X-Agent-Session": SESSION}, timeout=10)
        r.raise_for_status()
        return r.json()
    return _retry_request(_do)


def push(payload: dict) -> int:
    def _do():
        r = requests.post(f"{SERVER}/agent/sync", json=payload,
                          headers={"X-Token": TOKEN}, timeout=10)
        r.raise_for_status()
        return r.json().get("new", 0)
    return _retry_request(_do)


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
        "holder": getattr(info, "name", "") or "",
        "deals": [{**d, "time": d["time"].isoformat()} for d in deals],
        "command_done": done,       # сервер снимет команду после выполнения
        "host": socket.gethostname(),
        "role": ROLE,
        "session": SESSION,
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


# Раньше здесь была пауза опроса терминала на время игры в полноэкранном
# фокусе — снята: терминал управляется через MT5 API (mt5.initialize),
# без UI-автоматизации, окно всегда скрыто (hide_terminal(), см. main()),
# процесс держится на IDLE-приоритете (_lower_priority) и в фоновом режиме
# (PROCESS_MODE_BACKGROUND_BEGIN, см. _run_quietly()). Опрос сам по себе
# не создаёт заметной нагрузки на CPU/GPU и не может показать окно поверх
# игры — фоновая оптимизация уже полностью снимает саму причину, ради
# которой пауза когда-то вводилась.


def main():
    if not TOKEN:
        raise SystemExit("не задан WEBHOOK_TOKEN — агент не сможет авторизоваться")
    _run_quietly()
    # после самообновления старый процесс мог ещё держать порт — недолго
    # подождём вместо мгновенной смерти (см. RESPAWN_WAIT в _self_update_and_restart)
    retry = float(os.environ.pop("AGENT_RESPAWN_WAIT", 0) or 0)
    lock = only_one_copy(retry_seconds=retry)      # держим до конца работы

    if AUTO_UPDATE and _check_and_rollback_bad_update(lock):
        return      # откатились и запустили новый процесс на старом коде — этот выходит

    log.info("агент запущен (роль: %s), сервер %s, круг раз в %d с", ROLE, SERVER, INTERVAL)

    # None = роль ещё не определялась (первый круг); дальше True — в резерве,
    # False — активен. Уведомляем сервер только на смене None->False->True
    # или None->True->False, а не на самом первом определении роли: обычный
    # старт standby — это не авария, тревожить незачем
    standing_by = None
    took_over = False   # держит право опроса — важен для безопасного автообновления
    update_confirmed = False   # первый успешный круг на этом коде уже подтверждён
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
            check_for_update(lock, holding_terminal=took_over)     # обновится и выйдет сама
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

        # Проверяем владение на каждом круге, включая primary и уже активный
        # standby. Потеря связи с сервером означает ожидание, а не второй опрос.
        if not claim_terminal():
            if standing_by is not True:
                log.info("право опроса не получено, жду следующего круга")
                if standing_by is False:      # реальный переход, не первый запуск
                    notify_role_change("standby")
                standing_by = True
            send_heartbeat()
            took_over = False
            _touch_beat()       # цикл жив и осознанно молчит — не зависание
            if AUTO_UPDATE and not update_confirmed:
                # дошли досюда без падений — этот код рабочий, даже если он
                # просто ждёт в резерве и терминал ещё не трогал
                _confirm_update_ok()
                update_confirmed = True
            time.sleep(INTERVAL)
            continue
        if standing_by is True:
            log.info("получено исключительное право опроса терминала")
            notify_role_change("active")
            took_over = True
        standing_by = False
        took_over = True

        try:
            accs = fetch_accounts()
        except Exception as e:
            log.warning("не получил список счетов: %s", e)
            # дожили до сюда без необработанного исключения — сам код рабочий,
            # даже если сервер/сеть сейчас недоступны. Подтверждаем именно
            # это, а не «удалось поговорить с MT5»: иначе брокер, лежащий
            # дольше MIN_CONFIRM_GRACE, откатил бы совершенно исправный код
            # на следующем случайном перезапуске (реальный сценарий, не
            # теоретический — из красной команды)
            if AUTO_UPDATE and not update_confirmed:
                _confirm_update_ok()
                update_confirmed = True
            time.sleep(INTERVAL)
            continue

        # терминал может показать окно сам: при обновлении, всплывающих
        # сообщениях брокера или после переподключения — прячем каждый круг
        trades.hide_terminal()

        ok = False
        for acc in accs:
            if not claim_terminal():
                break
            try:
                payload = collect(acc)
                new = push(payload)
                ok = True
                log.info("%s: отправлено %d сделок, новых %d, баланс %.2f",
                         acc["name"], len(payload["deals"]), new, payload["balance"])
            except Exception as e:
                log.warning("%s: %s", acc.get("name", "?"), e)

        if ok:      # хоть один счёт прочитан — терминал жив, отмечаемся для сторожа
            _touch_beat()

        # подтверждаем по факту «дожили до конца цикла без краха», не по
        # успеху MT5/сети конкретно в этом круге — см. комментарий выше
        if AUTO_UPDATE and not update_confirmed:
            _confirm_update_ok()
            update_confirmed = True

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
