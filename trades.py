"""История сделок из терминала MT5, сводки по периодам и их оформление.

Свою базу не ведём: MT5 хранит историю сам и подтягивает её с сервера брокера.
"""

import os
import subprocess
import time
from datetime import date, datetime, time as dtime, timedelta, timezone

from dotenv import load_dotenv

try:                        # на сервере библиотеки MT5 нет — она только под Windows
    import MetaTrader5 as mt5
    HAS_MT5 = True
except ImportError:         # тогда те же отчёты строим из базы, которую наполняет агент
    mt5 = None
    HAS_MT5 = False
    import store

load_dotenv()  # настройки читаются при импорте, поэтому .env грузим здесь же

if HAS_MT5:
    BALANCE_TYPES = {mt5.DEAL_TYPE_BALANCE, mt5.DEAL_TYPE_CREDIT,
                     mt5.DEAL_TYPE_CORRECTION, mt5.DEAL_TYPE_BONUS}
    CLOSING = {mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT}

THIN = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"

# Счёт Amplify: торгуется баланс с плечом, но результат сделок целиком твой —
# из него лишь вычитается плата платформы (PF Deduction) и корректировки.
# Сверено с PnL в портале: 13.40 сделок − 3.91 платы = 9.23. Доли прибыли нет.
SHARE = float(os.getenv("INVESTOR_SHARE", 1) or 1)
# Доля брокера с прибыли: 30% удерживается, остальное — чистая прибыль инвестора
BROKER_FEE = float(os.getenv("BROKER_FEE", 0.30))
DUST = 0.5      # мельче этого — след округлений, а не остаток профита
# С какой даты показывать историю. Сделки до неё в базе остаются, но в отчёты
# не попадают — так отсечку можно двигать, ничего не теряя
REPORT_FROM = datetime.fromisoformat(os.getenv("REPORT_FROM", "2026-07-01"))
# Пояс сервера брокера: его время стоит в метках сделок, по нему же считаются
# дни и границы периодов. Совпадает с московским
TZ_HOURS = float(os.getenv("TZ_HOURS", 3))

# Брокер держит торговый баланс равным деньгам инвестора × множитель Amplify,
# поэтому свои деньги считаются из баланса — депозиты и выводы подхватываются сами.
# Сверено на SONIC: 6585.13 / 24 = 274.38 при 274.36 в портале.
_current: str = ""      # имя счёта, к терминалу которого сейчас подключены
_multiplier: float = 1
_base: float = None     # мои деньги на дату привязки (сверено с порталом)
_base_at: datetime = None


TERMINAL = os.getenv("MT5_TERMINAL", r"D:\MetaTrader5\terminal64.exe")
_history_seen: set[str] = set()     # у каких счетов история уже подгружалась


def _launch() -> None:
    """Поднять терминал скрытым, если он ещё не запущен.

    Терминалу нужен рабочий стол, поэтому службой его не сделать, но окно
    можно не показывать вовсе: работает молча, не мешает и не закрывается
    случайным кликом.
    """
    startup = None
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0     # SW_HIDE — ни окна, ни кнопки в панели задач
    proc = subprocess.Popen([TERMINAL], cwd=os.path.dirname(TERMINAL), startupinfo=startup,
                            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    time.sleep(20)      # терминалу нужно время подняться
    hide_terminal(proc.pid)


def hide_terminal(pid: int = None) -> int:
    """Спрятать окна терминала. Возвращает, сколько окон скрыто.

    Флага при запуске мало: MT5 показывает окно сам, уже после старта.
    """
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hidden = 0

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        nonlocal hidden
        if not user32.IsWindowVisible(hwnd):
            return True
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if pid is not None and owner.value != pid:
            return True
        # опознаём по классу окна: заголовок у терминала меняется вместе со счётом
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if "MetaQuotes::MetaTrader" in cls.value:
            user32.ShowWindow(hwnd, 0)      # SW_HIDE
            hidden += 1
        return True

    user32.EnumWindows(visit, 0)
    return hidden


class _Account:
    """Счёт так, как его видит бот на сервере — данные приносит агент."""

    def __init__(self, row: dict):
        self.login = row["login"]
        self.balance = row["balance"] or 0.0
        self.equity = row["equity"] or 0.0
        self.currency = row["currency"] or "USD"
        self.server = row["server"] or ""


_db = None          # соединение с базой сделок, если работаем без терминала
_login: int = 0


def _store_db():
    global _db
    if _db is None:
        _db = store.open_db()
    return _db


def use(acc: dict) -> None:
    """Переключить терминал на этот счёт.

    Терминал один на всех: его IPC-порт (127.0.0.1:22346) жёстко зашит, поэтому
    второй запущенный терминал получает bind error и Python до него не достучится.
    Смена счёта логином занимает около секунды — этого достаточно.
    """
    global _current, _multiplier, _login, _base, _base_at
    _multiplier = float(acc.get("multiplier", 1) or 1)
    _login = int(acc["login"])
    _base = float(acc["base"]) if acc.get("base") is not None else None
    _base_at = datetime.fromisoformat(acc["base_at"]) if acc.get("base_at") else None
    if not HAS_MT5:     # на сервере терминала нет: всё уже лежит в базе
        _current = acc["name"]
        return

    # сверяем не имя, а реальный логин в терминале: терминал общий, и другой
    # процесс мог переключить его на свой счёт — тогда мы бы отдали чужие цифры
    info = mt5.account_info()
    if _current == acc["name"] and info and int(info.login) == int(acc["login"]):
        return
    mt5.shutdown()

    def start() -> bool:
        return mt5.initialize(path=acc.get("terminal") or TERMINAL, login=int(acc["login"]),
                              password=acc["password"], server=acc["server"], timeout=60000)

    ok = start()
    if not ok:                  # терминал ещё не запущен — поднимаем сами и пробуем снова
        _launch()
        ok = start()
    if not ok:
        _current = ""
        raise RuntimeError(f"{acc['name']}: не удалось войти в счёт — {mt5.last_error()}")

    # смена счёта в терминале не мгновенна: пока она идёт, account_info отдаёт
    # прежний счёт — без этой проверки отчёт покажет чужие цифры
    for _ in range(20):
        info = mt5.account_info()
        if info and info.login == int(acc["login"]):
            break
        time.sleep(0.5)
    else:
        _current = ""
        raise RuntimeError(f"{acc['name']}: терминал остался на другом счёте")

    # после смены счёта история подтягивается с сервера не мгновенно, и первый
    # отчёт показал бы «сделок не было» — ждём только при первом входе в счёт
    if acc["name"] not in _history_seen:
        end, seen = clock() + timedelta(days=1), -1
        for _ in range(30):     # ждём, пока счётчик перестанет расти: догрузка идёт порциями,
            total = mt5.history_deals_total(datetime(2000, 1, 1), end)   # и половина истории
            if total and total == seen:                                  # выглядела бы как
                break                                                    # новые сделки
            seen = total
            time.sleep(0.5)
        _history_seen.add(acc["name"])
    _current = acc["name"]


def _capital_moves(since: datetime) -> float:
    """Движение капитала после даты, ÷ плечо. Прибыль (Profit) — не капитал."""
    total = 0.0
    for r in fetch(since, clock() + timedelta(days=1)):
        if r["is_balance"] and is_transfer(r) and not is_profit_side(r):
            total += r["net"]
    return total / _multiplier if _multiplier else total


def capital() -> float:
    """Вложенный капитал (аналог Invested в портале).

    Если задан acc['base'] (Invested из портала на дату base_at) — берём его и
    прибавляем движения капитала после этой даты: реинвест и пополнения сразу
    подхватываются, а прибыль не считается капиталом. Так точно и актуально.
    Без привязки — оценка из всей истории (может недосчитать капитал до августа).
    """
    if _base is not None:
        extra = _capital_moves(_base_at) if _base_at else 0.0
        return _base + extra
    # без привязки: баланс = капитал×плечо + прибыль. Прибыль лежит 1:1 и мала
    # относительно капитала, поэтому баланс÷плечо — верная оценка вложенного.
    # Считать по переводам из базы нельзя: депозиты до августа уже свёрнуты в
    # месячные итоги, и капитал занизился бы почти до нуля (тогда invested()
    # показывал бы весь торговый баланс ×24 — это и была ошибка «60055$»).
    # ponytail: overshoot на удержанную_прибыль÷плечо (~0.06%). Задай acc['base']
    # (Invested из портала) — тогда капитал точный до цента.
    a = account()
    if a and _multiplier and _multiplier != 1:
        return a.balance / _multiplier
    return _capital_moves(datetime(2000, 1, 1))


def capital_moves_after(rows: list[dict], when: datetime) -> float:
    """Сколько капитала завели или вывели после этой даты (в реальных деньгах).

    Вывод прибыли капитал не меняет, поэтому такие строки не в счёт.
    """
    return sum(own_amount(r) for r in rows
               if r["is_balance"] and is_transfer(r) and r["time"] > when
               and not is_profit_side(r))


def capital_at(when: datetime, rows: list[dict]) -> float:
    """Капитал на дату: сегодняшний минус всё, что пришло после неё.

    Без этого проценты врут при пополнениях: прибыль заработана на прежнем,
    меньшем капитале, а делилась бы на нынешний. Счёт, куда в середине месяца
    завели денег, показывал +1.84% вместо честных +6.6% — при том, что копирует
    ту же стратегию, что и соседние счета.
    """
    return capital() - capital_moves_after(rows, when)


def capital_around(row: dict) -> tuple[float, float]:
    """Капитал до и после этой операции.

    Брать текущий капитал и вычитать сумму нельзя: если операций в один момент
    несколько (вывод и следом реинвест), каждая посчитает «было» от одного и
    того же «сейчас», и соседние уведомления будут спорить друг с другом —
    «было 794.02» и «было 786.82» про один и тот же счёт.
    Поэтому отматываем назад все движения капитала, случившиеся позже этой
    строки, и получаем состояние ровно на её момент.
    """
    try:
        later = fetch(row["time"], clock() + timedelta(days=1))
    except Exception:       # истории под рукой нет — довольствуемся текущим
        later = []
    mark = (row["time"], row.get("ticket", 0))
    after = sum(own_amount(r) for r in later
                if r["is_balance"] and is_transfer(r) and not is_profit_side(r)
                and (r["time"], r.get("ticket", 0)) > mark)
    became = capital() - after
    own = own_amount(row)
    # вывод прибыли капитал не трогает — до и после он один и тот же
    if is_profit_side(row):     # прибыль капитал не трогает
        return became, became
    return became - own, became


def growth_pct(rows: list[dict], flows: list[dict] = None) -> float:
    """Доходность за период: доходности сделок к капиталу на их момент, сложенные.

    Складываем, а не перемножаем. Прибыль не остаётся на стратегии и не
    увеличивает базу — она копится отдельно, а торгует всё тот же вложенный
    капитал. Сложное перемножение давало 19.8% там, где у стратегии в отчёте
    18.20% (455.01 ÷ 2500 — ровно их цифра).

    Капитал берётся на момент каждой сделки, поэтому пополнение в середине
    месяца не занижает прежние сделки: счёт с довнесением показывал +2.1%
    вместо +7.1% при той же стратегии, что и соседние.
    """
    flows = rows if flows is None else flows
    total = 0.0
    for r in rows:
        if not r["is_closing"]:
            continue
        base = capital_at(r["time"], flows)
        if base > 0:
            total += net_of_fee(mine(r["net"])) / base
    return total * 100


def retained() -> float:
    """Накопленный профит чистыми — то, что реально лежит на стратегии.

    В баланс счёта прибыль попадает валовой: свою долю брокер списывает не с
    каждой сделки, а раз в неделю строкой PF Deduction. Поэтому «баланс минус
    капитал» — это профит ДО удержания, и показывать его рядом с суммами
    «чистыми» нельзя: после сделки на 36.31 валовых бот писал 49.21 накоплено,
    хотя на руки причиталось 25.42.
    Вычитаем долю с тех сделок, по которым брокер ещё не прошёлся.
    """
    gross = invested() - capital()
    if not gross:
        return 0.0
    try:
        rows = fetch(REPORT_FROM, clock() + timedelta(days=1))
    except Exception:       # истории под рукой нет — отдаём как есть
        return gross
    last_fee = max((r["time"] for r in rows if is_perf_fee(r)), default=None)
    pending = sum(r["net"] for r in rows
                  if r["is_closing"] and (last_fee is None or r["time"] > last_fee))
    left = gross - BROKER_FEE * max(pending, 0.0)
    # Выводы записываются с точностью до копейки, и после нескольких операций
    # остаётся пыль: вывели весь профит, а бот показывал +0.16. Считаем нулём —
    # это не деньги, а округление.
    return 0.0 if abs(left) < DUST else left


def invested() -> float:
    """Мои деньги на стратегии сейчас = капитал + удержанная прибыль.

    Баланс = капитал×плечо + прибыль (прибыль лежит 1:1). Поэтому весь баланс
    на плечо делить нельзя. Сверено с порталом: 2500 + 39.40 = баланс 60039.40.
    """
    a = account()
    if not a or not _multiplier:
        return a.balance if a else 0.0
    return a.balance - capital() * (_multiplier - 1)

# пополнения, выводы, апгрейды и сопутствующие им корректировки —
# это перемещение денег, а не результат торговли
TRANSFER_WORDS = ("deposit", "withdraw", "upgrade", "transfer", "credit", "adjust")


def mine(v: float) -> float:
    """Результат в деньгах инвестора."""
    return v * SHARE


def net_of_fee(v: float) -> float:
    """Чистый результат: то, что реально можно вывести или реинвестировать.

    Доля брокера 30% применяется и к прибыли, и к убытку — на счёт инвестора
    попадает 70% результата сделки.
    """
    return v * (1 - BROKER_FEE)


def is_transfer(row: dict) -> bool:
    return any(w in (row["comment"] or "").lower() for w in TRANSFER_WORDS)


def is_perf_fee(row: dict) -> bool:
    """Еженедельное удержание доли брокера («PF Deduction»).

    Это те же 30%, что уже сняты net_of_fee: сверено — удержание равно ровно
    30% от валовой прибыли закрытых сделок за прошедшую неделю. Считать его
    ещё и расходом значит вычесть комиссию дважды (месяц показывал +108.39
    вместо +164.56 — на две недели, +73.01 и +91.56, приходились два таких
    удержания).
    """
    return "pf deduction" in (row["comment"] or "").lower()


def is_profit_side(row: dict) -> bool:
    """Движение по прибыли, а не по капиталу — значит реальные деньги, 1:1.

    Реинвест приходит парой строк в один момент: «Adjust-6.92» (из прибыли
    списали 6.92) и «Upgrade-166.08» (в капитал добавили 166.08 ÷ 24 = 6.92).
    Adjust мы принимали за капитал и делили на плечо — выходило −0.29 вместо
    −6.92, и уведомления спорили друг с другом.
    """
    note = (row.get("comment") or "").lower()
    return "profit" in note or "adjust" in note


def own_amount(row: dict) -> float:
    """Сколько это в реальных деньгах инвестора.

    Сверено с Tag Wallet: капитал усиливается плечом (Deposit 92.79 в кошельке =
    2226.96 на счёте, ×24), а прибыль лежит в балансе 1:1 — поэтому вывод прибыли
    приходит уже в реальных деньгах и делить его на плечо нельзя.
    """
    net = row["net"]
    if is_profit_side(row):
        return net                      # прибыль — уже реальные деньги
    return net / _multiplier if _multiplier else net


def connect():
    """Подключение к уже запущенному терминалу."""
    if not HAS_MT5:
        return account()
    if not mt5.initialize():
        raise RuntimeError(f"терминал MT5 недоступен: {mt5.last_error()}")
    return mt5.account_info()


def currency() -> str:
    info = account()
    return info.currency if info else ""


def account():
    if not HAS_MT5:
        row = store.get_state(_store_db(), _login) if _login else None
        return _Account(row) if row else None
    return mt5.account_info()


def clock(ts: float = None) -> datetime:
    """Часы в том же масштабе, что и метки сделок.

    Терминал отдаёт время сервера брокера, а это московское: реинвест с меткой
    15:29:26 пришёл в Telegram в 15:30. Часы же возвращали UTC и отставали на
    три часа — всё, что случилось за последние три часа, не попадало в выборку
    «до сейчас». Из-за этого пропущенного пополнения доходность счёта считалась
    от завышенного капитала: 6.72% вместо 7.79%.
    """
    base = (datetime.now(timezone.utc) if ts is None
            else datetime.fromtimestamp(ts, timezone.utc))
    return (base + timedelta(hours=TZ_HOURS)).replace(tzinfo=None)


def local(when: datetime) -> datetime:
    """Время события для показа человеку.

    Часы и метки сделок уже идут по Москве, так что переводить нечего —
    функция осталась точкой правки, если сервер брокера сменит пояс.
    """
    return when


def _convert(deal) -> dict:
    net = deal.profit + deal.swap + deal.commission + getattr(deal, "fee", 0.0)
    is_balance = deal.type in BALANCE_TYPES
    return {
        "ticket": deal.ticket,
        # по нему находим, когда позиция была открыта: у входа и выхода он общий
        "position": getattr(deal, "position_id", 0),
        "time": clock(deal.time),
        "symbol": deal.symbol,
        # закрывающая сделка противоположна направлению позиции
        "side": "" if is_balance else ("SELL" if deal.type == mt5.DEAL_TYPE_BUY else "BUY"),
        "volume": deal.volume,
        "price": deal.price,
        "profit": deal.profit,
        "swap": deal.swap,
        "commission": deal.commission,
        "net": net,
        "is_balance": is_balance,
        "is_closing": (not is_balance) and deal.entry in CLOSING,
        "is_opening": (not is_balance) and deal.entry == mt5.DEAL_ENTRY_IN,
        "comment": deal.comment,
    }


def fetch(since: datetime, until: datetime) -> list[dict]:
    """Сделки за период. Границы — по времени портала (UTC)."""
    if since < REPORT_FROM:
        # отсечка одна на все отчёты: убрать месяц только из разбивки нельзя —
        # «за всё время» продолжало бы его считать, и суммы не сошлись бы
        since = REPORT_FROM
    if not HAS_MT5:
        return store.fetch(_store_db(), _login, since, until)
    # MT5 трактует границы как время сервера, поэтому берём с запасом и режем сами
    raw = mt5.history_deals_get(since - timedelta(days=2), until + timedelta(days=2))
    if raw is None:
        raise RuntimeError(f"история недоступна: {mt5.last_error()}")
    rows = [_convert(d) for d in raw]
    return sorted((r for r in rows if since <= r["time"] <= until), key=lambda r: r["time"])


def since_ticket(ticket: int) -> list[dict]:
    """Сделки, появившиеся после указанного тикета — для уведомлений."""
    if not HAS_MT5:
        return store.after_ticket(_store_db(), _login, ticket)
    raw = mt5.history_deals_get(clock() - timedelta(days=3), clock() + timedelta(days=1))
    if not raw:
        return []
    return sorted((_convert(d) for d in raw if d.ticket > ticket), key=lambda r: r["ticket"])


def last_ticket() -> int:
    if not HAS_MT5:
        return store.last_ticket(_store_db(), _login)
    raw = mt5.history_deals_get(datetime(2000, 1, 1), clock() + timedelta(days=1))
    return max((d.ticket for d in raw), default=0)


def opened_at(position: int, closed: datetime) -> datetime | None:
    """Когда была открыта позиция: ищем её входную сделку по общему номеру."""
    if not position:
        return None
    for r in fetch(closed - timedelta(days=14), closed + timedelta(minutes=1)):
        if r.get("position") == position and r["is_opening"]:
            return r["time"]
    return None




def positions() -> list[dict]:
    """Открытые сейчас позиции."""
    if not HAS_MT5:
        return []       # открытые позиции агент пока не синхронизирует
    raw = mt5.positions_get()
    if not raw:
        return []
    return [{"symbol": p.symbol,
             "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
             "volume": p.volume, "price": p.price_open, "current": p.price_current,
             "net": p.profit + p.swap, "time": clock(p.time)}
            for p in raw]


# ── оформление ────────────────────────────────────────────────────────────

SIGNS = {"USD": "$", "EUR": "€", "GBP": "£", "RUB": "₽"}


def sign(cur: str) -> str:
    """Значок валюты: «2500.00$» читается быстрее, чем «2500.00 USD»."""
    return SIGNS.get((cur or "").upper(), f" {cur}" if cur else "")


NBSP = " "     # узкий неразрывный пробел: не даёт числу переноситься
SPARK = "▁▂▃▄▅▆▇█"


def amount(v: float, cur: str = "", signed: bool = False) -> str:
    """Сумма с разделителями тысяч: «2 500.00 $» читается быстрее, чем «2500.00$»."""
    s = f"{v:+,.2f}" if signed else f"{v:,.2f}"
    s = s.replace(",", NBSP)
    return s + (NBSP + sign(cur).strip() if cur else "")


def spark(values: list[float]) -> str:
    """Мини-график одной строкой: форма периода видна раньше, чем прочитаны цифры."""
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return SPARK[3] * len(values)
    step = (len(SPARK) - 1) / (hi - lo)
    return "".join(SPARK[round((v - lo) * step)] for v in values)


def money(v: float) -> str:
    return f"{v:+.2f}"


def pct(v: float, signed: bool = True) -> str:
    """Процент как в канале стратегии: до трёх знаков, лишние нули убраны.

    У них 0.951%, но 3.73% и 86.6% — то есть три знака после запятой с
    отброшенными нулями. Так наши цифры сравнимы с их отчётами один в один.
    """
    s = f"{v:+.3f}" if signed else f"{v:.3f}"
    return s.rstrip("0").rstrip(".") + "%"


def vol(v: float) -> str:
    """Объём: у копи-трейдинга лоты бывают микроскопические."""
    return f"{v:.2f}" if v >= 0.01 else f"{v:.4f}"


def short(symbol: str, width: int = 9) -> str:
    return symbol[:width]


FIG = " "      # пробел шириной цифры


def col(value: str, width: int) -> str:
    """Дополнить число слева до общей ширины — для колонок внутри цитаты.

    В цитате шрифт обычный, а не моноширинный, но цифры почти во всех шрифтах
    одной ширины. Поэтому числа выравниваются, если добивать их «цифровым»
    пробелом U+2007, а переменный текст (день недели, символ) держать в конце
    строки, где его ширина уже ни на что не влияет.
    """
    return FIG * max(0, width - len(value)) + value


def widest(values) -> int:
    return max((len(v) for v in values), default=0)


def quote(lines: list[str], fold_over: int = 10) -> str:
    """Список строк цитатой; длинный — сворачиваемой.

    Цитата вместо <pre>: моноширинный шрифт Telegram на телефоне не содержит
    кириллицу и подставляет обычную, отчего колонки, набитые пробелами,
    разъезжаются. В цитате выравнивания нет вовсе — значения разделяем «·»,
    и строка читается одинаково на любом экране.
    """
    body = "\n".join(lines)
    tag = "blockquote expandable" if len(lines) > fold_over else "blockquote"
    return f"<{tag}>{body}</blockquote>"


def bar(value: float, scale: float, width: int = 8) -> str:
    """Полоса пропорционально максимуму периода."""
    if not scale:
        return ""
    n = max(1, round(abs(value) / scale * width))
    return ("█" if value >= 0 else "░") * min(n, width)


def summary(rows: list[dict]) -> dict:
    closed = [r for r in rows if r["is_closing"]]
    balance = [r for r in rows if r["is_balance"]]
    costs = [r for r in balance if not is_transfer(r) and not is_perf_fee(r)]
    transfers = [r for r in balance if is_transfer(r)]        # пополнения и выводы
    wins = [r for r in closed if r["net"] > 0]
    losses = [r for r in closed if r["net"] < 0]
    trading = sum(r["net"] for r in closed)
    platform = sum(r["net"] for r in costs)
    return {
        "count": len(closed),
        "net": trading,
        "platform": platform,
        "total": trading + platform,       # итог в кармане инвестора
        "transfers": sum(r["net"] for r in transfers),     # как лежит на счёте
        # в реальных деньгах: капитал усилен плечом, а прибыль лежит 1:1 —
        # складывать их напрямую нельзя, вышло бы -196.10 вместо -180.46
        "moves": sum(own_amount(r) for r in transfers),
        # пополнения и выводы порознь: одна итоговая цифра прячет, что денег и
        # заводили, и снимали — а это разные события
        "put_in": sum(own_amount(r) for r in transfers if r["net"] > 0),
        "took_out": sum(own_amount(r) for r in transfers if r["net"] < 0),
        "gross_profit": sum(r["net"] for r in wins),
        "gross_loss": sum(r["net"] for r in losses),
        "wins": len(wins),
        "losses": len(losses),
        "best": max((r["net"] for r in closed), default=0.0),
        "worst": min((r["net"] for r in closed), default=0.0),
        "volume": sum(r["volume"] for r in closed),
        "fees": sum(r["swap"] + r["commission"] for r in closed),
    }


def winrate_bar(wins: int, total: int, width: int = 10) -> str:
    if not total:
        return ""
    filled = round(wins / total * width)
    return "▰" * filled + "▱" * (width - filled)


def fmt_report(title: str, rows: list[dict], cur: str, subtitle: str = "",
               since: datetime = None, with_deals: bool = False,
               until: datetime = None) -> str:
    """Сводка за период: итог, статистика, разбивка по дням и символам."""
    s = summary(rows)
    head = f"<b>{title}</b>"
    if subtitle:
        head += f"  <i>{subtitle}</i>"

    if not s["count"] and not s["transfers"] and not s["platform"]:
        # за один выходной день пустой отчёт — не повод искать поломку;
        # для периода в несколько дней пометка не нужна, поэтому нужен until
        if since and until and is_weekend(since) and since.date() == until.date():
            return f"{head}\n{THIN}\n\n{WEEKEND}"
        return f"{head}\n{THIN}\n\nЗа этот период сделок не было."

    # отчёт за всё время должен включать и свёрнутые месяцы: их сделок в базе
    # уже нет, есть только суммы
    old = archived_before_now() if (since and since <= REPORT_FROM) else (0.0, 0, 0, 0)
    old_gross, old_count, old_wins, old_losses = old
    gross = mine(s["total"] + old_gross)
    net = net_of_fee(gross)     # чистыми — то, что можно вывести или реинвестировать
    mark = "▲" if net > 0 else ("▼" if net < 0 else "•")
    cap = capital()             # баланс стратегии (профит лежит отдельно)

    # Процент — доходность каждой сделки к капиталу на её момент, перемноженные.
    # Простое «профит ÷ капитал» врёт при пополнениях: прибыль заработана на
    # прежнем, меньшем капитале. По капиталу на начало дня тоже неточно —
    # деньги заводят и в середине дня: счёт показывал 7.599% там, где соседние
    # с той же стратегией давали 7.12%. По моменту сделки все сходятся.
    flows = fetch(since, clock() + timedelta(days=1)) if since else []
    by_day: dict = {}
    for r in rows:
        if r["is_closing"]:
            by_day.setdefault(r["time"].date(), []).append(r["net"])

    weighed = any(r["is_closing"] for r in rows)
    if old_count:
        # период захватывает свёрнутые месяцы: их сделок в базе нет, и процент
        # по одним живым строкам показывал бы только текущий месяц — вдвое
        # меньше денег, что стоят рядом
        grew = growth_all()
    elif weighed:
        grew = growth_pct(rows, flows)
    else:
        grew = net / cap * 100 if cap else 0.0
    roi = f"  <i>{pct(grew)}</i>" if (weighed or cap) else ""

    # главная строка — крупно результат, под ней мини-график формы периода
    out = [head, THIN, f"{mark} <b>{amount(net, cur, signed=True)}</b>{roi}"]
    shape = spark([net_of_fee(mine(sum(by_day[d]))) for d in sorted(by_day)])
    if shape:
        out.append(f"<code>{shape}</code>  <i>по дням</i>")
    out.append("<i>чистыми, на руки</i>")

    detail = []
    if gross != net:
        # человеку понятнее «сколько забрал брокер», чем «сколько было до него»
        detail.append(f"заработано {amount(gross, signed=True)}, брокер удержал "
                      f"{amount(abs(gross - net))} ({BROKER_FEE * 100:.0f}%)")
    if s["platform"]:
        detail.append(f"плата платформы {amount(mine(s['platform']), signed=True)}")
    if detail:
        out.append("<i>" + " · ".join(detail) + "</i>")

    count = s["count"] + old_count
    if count:
        # свёртка месяца сохраняет плюсовые и минусовые сделки, поэтому доля
        # верна и для периодов, чьи сделки уже удалены из базы
        wins, losses = s["wins"] + old_wins, s["losses"] + old_losses
        rate = wins / count * 100
        out.append(f"📈 <b>{count}</b> сделок: <b>{wins}</b> в плюс, "
                   f"<b>{losses}</b> в минус <i>({rate:.2f}% удачных)</i>")
    if s["put_in"] or s["took_out"]:
        moves = []
        if s["put_in"]:
            moves.append(f"завёл <b>{amount(s['put_in'], cur)}</b>")
        if s["took_out"]:
            moves.append(f"вывел <b>{amount(abs(s['took_out']), cur)}</b>")
        out.append("💵 " + " · ".join(moves) + f" <i>(это не заработок, "
                   f"а перемещение денег)</i>")

    # по дням — только чистый профит и число сделок, без путающего баланса
    if len(by_day) > 1:
        days = sorted(by_day)[-31:]
        totals = {d: net_of_fee(mine(sum(by_day[d]))) for d in days}
        scale = max(abs(v) for v in totals.values())
        # процент дня — перемноженные доходности его сделок, каждая к капиталу
        # на свой момент: пополнение в середине дня иначе задирает весь день
        # доходности складываем, а не перемножаем: прибыль не остаётся на
        # стратегии и базу не увеличивает. Иначе недельный блок расходился с
        # процентом того же периода в заголовке — 3.759% против 3.709%
        gains = {d: 0.0 for d in days}
        for r in rows:
            if r["is_closing"] and r["time"].date() in gains:
                base = capital_at(r["time"], flows)
                if base > 0:
                    gains[r["time"].date()] += net_of_fee(mine(r["net"])) / base
        vals = {d: money(totals[d]) for d in days}
        pcts = {d: pct(gains[d] * 100) for d in days}
        wv, wp = widest(vals.values()), widest(pcts.values())
        lines = []
        week = None
        for d in days:
            if week is not None and d.isocalendar().week != week:
                lines.append("")        # пустая строка между неделями
            week = d.isocalendar().week
            share = f" · <i>{col(pcts[d], wp)}</i>" if cap else ""
            lines.append(f"{d:%d.%m} · <b>{col(vals[d], wv)}</b>{share} · "
                         f"{len(by_day[d])} сд · <i>{WEEKDAYS[d.weekday()]}</i>")
        out += ["", "📅 <b>По дням</b> <i>(МСК)</i>", quote(lines)]

        # Недели отдельным блоком: в месячном отчёте тридцать строк по дням
        # не складываются в голове, а по неделям картина видна сразу.
        weeks: dict = {}
        for d in days:
            key = d.isocalendar()[:2]       # год и номер недели
            w = weeks.setdefault(key, {"from": d, "to": d, "money": 0.0,
                                       "gain": 0.0, "trades": 0})
            w["to"] = d
            w["money"] += totals[d]
            w["gain"] += gains[d]
            w["trades"] += len(by_day[d])
        if len(weeks) > 1:
            wm = widest([money(w["money"]) for w in weeks.values()])
            wp2 = widest([pct(w["gain"] * 100) for w in weeks.values()])
            wl = [f"{w['from']:%d.%m}–{w['to']:%d.%m} · <b>{col(money(w['money']), wm)}</b>"
                  f" · <i>{col(pct(w['gain'] * 100), wp2)}</i> · {w['trades']} сд"
                  for w in weeks.values()]
            out += ["", "🗓 <b>По неделям</b>", quote(wl)]
    elif with_deals:
        shown = [r for r in rows if r["is_closing"]]
        vals = [net_of_fee(mine(r["net"])) for r in shown[-40:]]
        wv = widest([money(v) for v in vals])
        bases = [capital_at(r["time"], flows) or cap for r in shown[-40:]]
        wp = widest([pct(v / b * 100) for v, b in zip(vals, bases) if b])
        lines = []
        for r, val, base in zip(shown[-40:], vals, bases):
            share = f" · <i>{col(pct(val / base * 100), wp)}</i>" if base else ""
            lines.append(f"{r['time']:%H:%M} · <b>{col(money(val), wv)}</b>{share} · "
                         f"<i>{r['side']} {short(r['symbol'])}</i>")
        if lines:
            out += ["", "📊 <b>Сделки</b> <i>(МСК)</i>", quote(lines)]
        if len(shown) > 40:
            out.append(f"<i>последние 40 из {len(shown)}</i>")

    # история по месяцам — в отчёте за всё время: там её и ищут, а в отчёте
    # за неделю она только мешала бы
    if since is not None and since.year <= 2000:
        block = fmt_archive(cur)
        if block:
            out.append(block)

    # по инструментам — только если их несколько
    by_sym = {}
    for r in rows:
        if r["is_closing"]:
            agg = by_sym.setdefault(r["symbol"], [0.0, 0])
            agg[0] += r["net"]
            agg[1] += 1
    if len(by_sym) > 1:
        top = sorted(by_sym.items(), key=lambda kv: -abs(kv[1][0]))[:8]
        wv = widest([money(net_of_fee(mine(net))) for _, (net, _) in top])
        lines = [f"<b>{col(money(net_of_fee(mine(net))), wv)}</b> · {cnt} сд · "
                 f"<i>{short(sym, 10)}</i>" for sym, (net, cnt) in top]
        out += ["", "💱 <b>По инструментам</b>", quote(lines)]

    return "\n".join(out)


MONTHS = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
          7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь",
          12: "Декабрь"}

WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница",
            "суббота", "воскресенье")
# рынок закрыт в выходные, поэтому пустой отчёт за субботу и воскресенье —
# это норма, а не пропавшие сделки
WEEKEND = "🌴 <i>выходной, сделок нема</i>"


def is_weekend(d) -> bool:
    return d.weekday() >= 5


def with_weekday(d) -> str:
    """Дата с днём недели: «15.08.2026, сб»."""
    return f"{d:%d.%m.%Y}, {WEEKDAYS[d.weekday()]}"


def workdays(year: int, month: int, until=None) -> int:
    """Будние дни месяца; для текущего — сколько их уже прошло.

    Биржевые праздники не учитываем: календаря выходных у брокера нет, а
    расхождение в день-два картину не меняет — это мера «сколько было
    возможностей торговать», а не точный табель.
    """
    import calendar
    last = calendar.monthrange(year, month)[1]
    if until and (until.year, until.month) == (year, month):
        last = min(last, until.day)
    return sum(1 for day in range(1, last + 1)
               if date(year, month, day).weekday() < 5)


def archive(since: datetime = None, until: datetime = None) -> list[dict]:
    """Итоги свёрнутых месяцев: детали удалены, суммы остались."""
    if HAS_MT5 or not _login:       # у терминала история своя, архив не нужен
        return []
    return store.months(_store_db(), _login,
                        since.isoformat() if since else None,
                        until.isoformat() if until else None)


def monthly(limit: int = 12) -> list[dict]:
    """Итоги по месяцам: свёрнутый архив плюс месяцы, ещё лежащие в сделках.

    Один архив показывать мало: пока месяц не свёрнут (а сворачивается он в
    начале следующего), история выглядела бы пустой. Поэтому недостающие
    месяцы считаем прямо по сделкам — теми же правилами, что и в rollup.
    """
    floor = REPORT_FROM.strftime("%Y-%m")
    out = {m["month"]: dict(m) for m in archive() if m["month"] >= floor}
    for r in fetch(datetime(2000, 1, 1), clock() + timedelta(days=1)):
        key = f"{r['time']:%Y-%m}"
        if key in out and not out[key].get("_live"):
            continue            # месяц уже свёрнут — детали не задваиваем
        m = out.setdefault(key, {"month": key, "trades": 0, "gross": 0.0,
                                 "platform": 0.0, "deposits": 0.0, "wins": 0,
                                 "losses": 0, "_live": True})
        if r["is_closing"]:
            net = r["net"] or 0.0
            m["trades"] += 1
            m["gross"] += net
            if net > 0:
                m["wins"] += 1
            elif net < 0:
                m["losses"] += 1
        elif r["is_balance"]:
            if is_transfer(r):
                if (r["net"] or 0.0) > 0:
                    m["deposits"] += r["net"]
            elif not is_perf_fee(r):    # доля брокера уже снята net_of_fee
                m["platform"] += r["net"] or 0.0
    return [out[k] for k in sorted(out)][-limit:]


def growth_all() -> float:
    """Доходность за всю показываемую историю, %.

    Месяцы перемножаются: у свёрнутых берём сохранённый при свёртке процент,
    живые считаем по сделкам. Складывать профит и делить на нынешний капитал
    нельзя — счёт, куда завели денег, показывал +2.6% вместо +25%.
    """
    # месяцы перемножаются: между ними прибыль выводится и реинвестируется,
    # так что новый месяц стартует с уже изменившегося капитала
    g = 1.0
    for m in monthly(limit=1000):
        if not m.get("_live") and m.get("growth") is not None:
            g *= 1 + m["growth"] / 100
    live = fetch(REPORT_FROM, clock() + timedelta(days=1))
    g *= 1 + growth_pct(live, live) / 100
    return (g - 1) * 100


def archived_before_now() -> tuple[float, int]:
    """Валовый итог и число сделок месяцев, свёрнутых в архив.

    Свёртка удаляет сами сделки, оставляя только месячные суммы. Поэтому итог
    «за всё время», посчитанный по одним сделкам, терял всю прошлую историю —
    архив нужно прибавлять отдельно.
    """
    gross = 0.0
    count = wins = losses = 0
    for m in monthly(limit=1000):
        if m.get("_live"):          # этот месяц ещё лежит сделками, он уже учтён
            continue
        gross += (m["gross"] or 0.0) + (m["platform"] or 0.0)
        count += m["trades"] or 0
        wins += m.get("wins") or 0
        losses += m.get("losses") or 0
    return gross, count, wins, losses


def fmt_archive(cur: str, since: datetime = None, until: datetime = None) -> str:
    """История по месяцам: чистый профит, процент и сколько сделок."""
    rows = monthly()
    if not rows:
        return ""

    # процент к балансу стратегии — та же мера, что у дней и сделок. От
    # пополнений месяца считать нельзя: месяц с одним пополнением давал
    # бессмысленные сотни процентов
    cap = capital()
    now = clock().strftime("%Y-%m")
    nets = [net_of_fee(mine(m["gross"] + m["platform"])) for m in rows]
    wv = widest([f"{v:+.2f}" for v in nets])
    wp = widest([pct(v / cap * 100) for v in nets]) if cap else 0
    lines = []
    today = clock().date()
    for m, net in zip(rows, nets):
        share = f" · <i>{col(pct(net / cap * 100), wp)}</i>" if cap else ""
        name = MONTHS.get(int(m["month"][5:7]), m["month"])
        year = f" {m['month'][:4]}" if m["month"][:4] != now[:4] else ""
        mark = " <i>(идёт)</i>" if m["month"] == now else ""
        # будние дни — мера, с чем сравнивать число сделок: 15 сделок за 10 дней
        # и за 21 день это разная активность
        work = workdays(int(m["month"][:4]), int(m["month"][5:7]), today)
        lines.append(f"<b>{col(f'{net:+.2f}', wv)}</b>{share} · "
                     f"{m['trades']} сд за {work} дн · <i>{name}{year}</i>{mark}")

    return ("\n📦 <b>По месяцам</b>  <i>чистыми, % к балансу, сделок за будние дни</i>\n"
            + quote(lines))


def fmt_head(cur: str) -> str:
    """Шапка счёта: баланс стратегии и весь заработок с процентом — одной строкой."""
    cap = capital()
    if not cap:
        return ""
    # к сделкам в базе прибавляем свёрнутые месяцы, иначе история обрывается
    # на текущем месяце
    gross = summary(fetch(datetime(2000, 1, 1), clock()))["total"] + archived_before_now()[0]
    earned = net_of_fee(mine(gross))
    grew = growth_all()
    # процент к балансу стратегии — единая мера во всём боте (дни, месяцы,
    # сделки). От заведённых денег считать нельзя: пополнение усилено плечом,
    # и месяц с одним взносом давал сотни процентов
    roi = f" ({pct(grew)})" if cap else ""
    return (f"💎 <b>{amount(cap, cur)}</b>\n"
            f"◆ всего <b>{amount(earned, signed=True)}</b>{roi}")


def fmt_deals(title: str, rows: list[dict], cur: str, limit: int = 50) -> str:
    """Подробный список сделок."""
    shown = [r for r in rows if r["is_closing"] or r["is_balance"]]
    if not shown:
        return f"<b>📋 {title}</b>\n{THIN}\n\nСделок не было."

    lines = []
    for r in shown[-limit:]:
        if r["is_balance"]:
            lines.append(f"{r['time']:%d.%m %H:%M} · 💵 баланс · "
                         f"<b>{money(mine(r['net']))}</b>")
        else:
            lines.append(f"{r['time']:%d.%m %H:%M} · {r['side']} {short(r['symbol'])} "
                         f"{vol(r['volume'])} · <b>{money(mine(r['net']))}</b>")

    total = net_of_fee(mine(sum(r["net"] for r in shown if r["is_closing"])))
    out = [f"<b>📋 {title}</b>", THIN, quote(lines)]
    if len(shown) > limit:
        out.append(f"<i>показаны последние {limit} из {len(shown)}</i>")
    out.append(f"<b>Итого: {money(total)}{sign(cur)}</b>")
    if SHARE != 1:
        out.append("<i>суммы — ваша доля результата</i>")
    return "\n".join(out)


def fmt_status(cur: str) -> str:
    """Текущее состояние счёта и открытых позиций."""
    a = account()
    if not a:
        return "⚠️ Счёт недоступен."
    pos = positions()
    floating = mine(sum(p["net"] for p in pos))

    cap = capital()
    earned = net_of_fee(mine(summary(fetch(datetime(2000, 1, 1), clock()))["total"]))
    roi = f" ({pct(earned / cap * 100)})" if cap else ""

    out = [f"💼 <b>Счёт {a.login}</b>", THIN,
           f"На стратегии <b>{cap:.2f}{sign(cur)}</b>",
           f"Заработано <b>{earned:+.2f}{sign(cur)}</b>{roi}"]

    if pos:     # открытые позиции — тоже в моих деньгах
        lines = [f"{p['side']} {short(p['symbol'])} · <b>{money(mine(p['net']))}</b>" for p in pos]
        out += ["", f"📌 <b>Открыто позиций: {len(pos)}</b>", quote(lines),
                f"Плавающий результат <b>{money(floating)}{sign(cur)}</b>"]
    else:
        out.append("📌 Открытых позиций нет")
    return "\n".join(out)


def ordinal_today(row: dict) -> tuple[int, int]:
    """(какая это по счёту сделка за день, сколько всего закрытых за день)."""
    day = row["time"].date()
    try:
        closed = [r for r in fetch(datetime.combine(day, dtime.min),
                                   datetime.combine(day, dtime.max)) if r["is_closing"]]
    except Exception:
        return 1, 1     # история недоступна — не мешаем уведомлению
    total = len(closed)
    nth = sum(1 for r in closed if r["ticket"] <= row["ticket"])
    return max(nth, 1), max(total, 1)


def _nth_word(n: int) -> str:
    words = {1: "Первая", 2: "Вторая", 3: "Третья", 4: "Четвёртая", 5: "Пятая",
             6: "Шестая", 7: "Седьмая", 8: "Восьмая", 9: "Девятая", 10: "Десятая"}
    return words.get(n, f"{n}-я")


def late_note(row: dict) -> str:
    """Пометка, если событие догнало нас с опозданием.

    Пока ноутбук выключен, сделки не отслеживаются, а после включения приходят
    пачкой. Время в уведомлении — самой операции, но без оговорки старое
    событие читается как только что случившееся.
    """
    behind = (clock() - row["time"]).total_seconds() / 60
    if behind < 30:
        return ""
    if behind < 600:
        return f"<i>пришло с опозданием на {behind / 60:.0f} ч — терминал был offline</i>"
    return f"<i>событие от {row['time']:%d.%m}, пришло после включения терминала</i>"


def fmt_notification(row: dict, cur: str, day_net: float = None, day_count: int = None,
                     total_net: float = None) -> str:
    """Уведомление о событии на счёте. Про открытие позиций не пишем."""
    when = f"{row['time']:%d.%m.%Y  %H:%M:%S}"

    if row["is_balance"]:
        own = own_amount(row)           # реальные деньги: капитал ÷плечо, прибыль ×1
        cap = capital()                 # баланс стратегии = вложенный капитал
        is_profit = is_profit_side(row)
        # Adjust — это списание из профита в пару к Upgrade: те же деньги через
        # секунду вернутся капиталом. Называть это «выводом» неверно
        moved_in = "adjust" in (row["comment"] or "").lower()
        note = f"<i>{row['comment']}</i>" if row["comment"] else ""

        if is_profit and is_transfer(row):
            # профит лежит отдельно от капитала, поэтому капитал не меняется
            head = ("♻️ <b>Реинвест: профит → капитал</b>" if moved_in
                    else "💸 <b>Вывод профита</b>")
            where = ("⬇️ Списано из профита, сейчас уйдёт в капитал" if moved_in
                     else "➡️ Профит ушёл на баланс Tag Markets")
            out = [f"🕒 <b>{when}</b>", head, THIN,
                   f"<b>{money(own)}{sign(cur)}</b>", where]
            if note:
                out.append(note)
            out.append(f"💰 На стратегии: <b>{cap:.2f}{sign(cur)}</b> (не изменилось)")
            return "\n".join(out)

        if is_transfer(row):
            # изменение капитала: пополнение/реинвест (+) или вывод капитала (−)
            out_of = own < 0
            head = ("💸 <b>Вывод капитала</b>" if out_of
                    else "💵 <b>Пополнение / реинвест</b>")
            where = ("➡️ Ушло на баланс Tag Markets" if out_of
                     else "⬅️ Капитал добавлен в стратегию")
            was, became = capital_around(row)   # состояние ровно на момент операции
            out = [f"🕒 <b>{when}</b>", head, THIN, f"<b>{money(own)}{sign(cur)}</b>", where]
            if note:
                out.append(note)
            out.append(f"💰 Капитал: было {amount(was)} → стало "
                       f"<b>{amount(became, cur)}</b>")
            return "\n".join(out)

        # плата платформы — просто издержка
        out = [f"🕒 <b>{when}</b>", "🧾 <b>Плата платформы</b>", THIN,
               f"<b>{money(own)}{sign(cur)}</b>"]
        if note:
            out.append(note)
        return "\n".join(out)

    if row["is_opening"]:
        return ""       # про открытие не пишем: интересен результат, а он при закрытии

    # ── закрытие позиции ──────────────────────────────────────────────────
    gross = mine(row["net"])          # результат сделки до комиссии брокера
    profit = net_of_fee(gross)        # чистыми — профит именно этой сделки
    plus = profit >= 0
    cap = capital()                   # баланс стратегии (профит лежит отдельно)
    nth, total = ordinal_today(row)

    # порядок как просили: дата/время, какая сделка за день, потом профит крупно
    out = [f"🕒 <b>{row['time']:%d.%m.%Y  %H:%M:%S}</b>",
           f"📊 {_nth_word(nth)} сделка за день{'' if total == nth else f' из {total}'}",
           f"{'✅' if plus else '❌'} <b>{money(profit)}{sign(cur)}</b> чистыми"
           + (f"  <i>{pct(profit / cap * 100)}</i>" if cap else "")]

    details = [f"{short(row['symbol'], 12)} {row['side']}"]
    if gross != profit:
        details.append(f"до комиссии {money(gross)}")
    opened = opened_at(row.get("position", 0), row["time"])
    if opened:
        mins = (row["time"] - opened).total_seconds() / 60
        held = f", держал {mins:.0f} мин" if mins < 600 else ""
        details.append(f"вход {opened:%H:%M:%S}{held}")
    out.append("<i>" + " · ".join(details) + "</i>")

    # профит за все сделки дня
    day_profit = net_of_fee(mine(day_net)) if day_net is not None else profit
    n = day_count if day_count is not None else 1
    word = "сделка" if n == 1 else "сделки" if n < 5 else "сделок"
    out.append(f"💵 За день: <b>{money(day_profit)}{sign(cur)}</b> <i>({n} {word})</i>")

    # Накопленный профит: пока его не вывели и не реинвестировали, он лежит на
    # стратегии, и новые сделки прибавляются к нему. Раньше «всего» считалось
    # как капитал + профит одного дня — вчерашний нетронутый профит терялся.
    if cap:
        kept = retained()           # чистыми, за вычетом доли брокера
        total = cap + kept
        out.append(f"💰 Капитал: <b>{amount(cap, cur)}</b>")
        if abs(kept) >= 0.01:
            out.append(f"📈 Накоплено профита: <b>{amount(kept, cur, signed=True)}</b> "
                       f"<i>(не выведен)</i>")
        out.append(f"📊 Всего на стратегии: <b>{amount(total, cur)}</b>")
    out.append(late_note(row))
    return "\n".join(out)
