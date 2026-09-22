"""Хранилище сделок на сервере.

Агент на Windows читает терминал MT5 и присылает сделки сюда, бот берёт их
отсюда. Так бот живёт на сервере 24/7, а отчёты строятся из базы мгновенно —
без переключения терминала на каждый счёт.

Схема специально плоская: сделка целиком, как её отдал MT5, плюс логин счёта.
"""

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    """UTC без зоны. datetime.utcnow() объявлен устаревшим, а в базе лежат
    наивные значения — с ними и сравниваем, поэтому зону сразу отбрасываем.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

DB = os.getenv("TRADES_DB", os.path.join("data", "trades.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    login   INTEGER NOT NULL,
    ticket  INTEGER NOT NULL,
    time    TEXT    NOT NULL,      -- ISO, время как в портале (UTC)
    symbol  TEXT,
    side    TEXT,
    volume  REAL,
    price   REAL,
    profit  REAL,
    swap    REAL,
    commission REAL,
    net     REAL,
    is_balance  INTEGER,
    is_closing  INTEGER,
    is_opening  INTEGER,
    comment TEXT,
    PRIMARY KEY (login, ticket)
);
CREATE INDEX IF NOT EXISTS deals_by_time ON deals (login, time);

CREATE TABLE IF NOT EXISTS state (
    login    INTEGER PRIMARY KEY,
    balance  REAL,
    equity   REAL,
    currency TEXT,
    server   TEXT,
    synced   TEXT,                 -- когда агент последний раз выходил на связь
    max_ticket INTEGER DEFAULT 0,  -- переживает чистку сделок: иначе агент
                                   -- решит, что счёт новый, и зальёт всё заново
    capital_hist REAL,             -- капитал, сложенный агентом из всей истории
    profit_carry REAL DEFAULT 0    -- накопленный профит из свёрнутых месяцев
                                   -- (их сделок в deals уже нет — см. rollup)
);

-- Сделки храним за текущий месяц, прошлые сворачиваем сюда: детали за годы
-- не нужны, а итоги должны остаться навсегда.
CREATE TABLE IF NOT EXISTS months (
    login     INTEGER NOT NULL,
    month     TEXT    NOT NULL,    -- 'YYYY-MM'
    trades    INTEGER,             -- сколько закрытых сделок
    gross     REAL,                -- их результат до комиссии брокера
    platform  REAL,                -- платы платформы за месяц
    transfers REAL,                -- пополнения и выводы (капитал и профит вместе,
                                   -- только для отображения — см. capital_transfers
                                   -- для реконструкции капитала)
    deposits  REAL,                -- только пополнения — база для процентов
    capital_transfers REAL,        -- то же, но БЕЗ движений профита (Adjust/Upgrade):
                                   -- их нельзя делить на плечо как капитал
    wins      INTEGER,             -- прибыльных сделок: доля плюсовых нужна
    losses    INTEGER,             -- и после свёртки, а самих сделок уже нет
    best      REAL,                -- лучшая и худшая сделки месяца
    worst     REAL,
    volume    REAL,                -- суммарный объём
    growth    REAL,                -- доходность месяца, % (считается до удаления
                                   -- сделок: потом восстановить её уже нечем)
    PRIMARY KEY (login, month)
);

-- Команды агенту: бот на сервере кладёт сюда, агент на ПК забирает при опросе.
-- Так реализуем «кнопку запустить терминал» без прямого доступа сервер→ПК.
CREATE TABLE IF NOT EXISTS commands (
    login   INTEGER PRIMARY KEY,
    cmd     TEXT,
    created TEXT
);

-- Свечи M15 XAUUSD для графика цены на карточке стратегии. Общие для всех
-- пользователей (один символ), не привязаны к login. Хранится скользящее
-- окно (см. trim_candles) — детальная история глубже не нужна.
CREATE TABLE IF NOT EXISTS candles (
    time    TEXT PRIMARY KEY,      -- ISO, начало M15-бара (UTC)
    open    REAL,
    high    REAL,
    low     REAL,
    close   REAL
);
"""


def open_db(path: str = None) -> sqlite3.Connection:
    db = sqlite3.connect(path or DB)
    db.row_factory = sqlite3.Row
    # bot.py и webhook_server.py — разные процессы на одном файле. Журнал
    # по умолчанию (rollback) блокирует читателей на время записи целиком;
    # WAL пускает чтение параллельно записи, а busy_timeout ждёт вместо
    # мгновенного "database is locked" — свёртка месяцев (DELETE, держит
    # блокировку дольше обычного) иначе роняла параллельный /agent/sync 500-й
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=10000")
    db.executescript(SCHEMA)
    # база могла остаться от прежней версии — дописываем недостающие колонки
    have = {r["name"] for r in db.execute("PRAGMA table_info(state)").fetchall()}
    if "max_ticket" not in have:
        db.execute("ALTER TABLE state ADD COLUMN max_ticket INTEGER DEFAULT 0")
    if "capital_hist" not in have:
        db.execute("ALTER TABLE state ADD COLUMN capital_hist REAL")
    if "profit_carry" not in have:
        db.execute("ALTER TABLE state ADD COLUMN profit_carry REAL DEFAULT 0")
    # колонки статистики появились позже — базы прошлых версий дополняем
    have = {r["name"] for r in db.execute("PRAGMA table_info(months)").fetchall()}
    for col, kind in (("wins", "INTEGER"), ("losses", "INTEGER"),
                      ("best", "REAL"), ("worst", "REAL"), ("volume", "REAL"),
                      ("growth", "REAL"), ("capital_transfers", "REAL")):
        if col not in have:
            db.execute(f"ALTER TABLE months ADD COLUMN {col} {kind}")
    db.commit()
    return db


FIELDS = ("ticket", "time", "symbol", "side", "volume", "price", "profit", "swap",
          "commission", "net", "is_balance", "is_closing", "is_opening", "comment")


def save_deals(db, login: int, deals: list[dict], *, commit: bool = True) -> int:
    """Сохраняет сделки. Возвращает, сколько из них новых."""
    new = 0
    for d in deals:
        row = [int(login)] + [d.get(f) for f in FIELDS]
        # время может прийти как datetime или строкой
        t = d.get("time")
        row[2] = t.isoformat() if isinstance(t, datetime) else str(t)
        cur = db.execute(
            f"INSERT OR IGNORE INTO deals (login, {', '.join(FIELDS)}) "
            f"VALUES ({', '.join('?' * (len(FIELDS) + 1))})", row)
        new += cur.rowcount
    if commit:
        db.commit()
    return new


CANDLE_KEEP_DAYS = 60   # глубже графику цены заходить незачем — см. схему candles


def save_candles(db, candles: list[dict], *, commit: bool = True) -> int:
    """Сохраняет M15-свечи XAUUSD. INSERT OR REPLACE: агент может прислать
    один и тот же ещё не закрытый бар повторно с уточнённым high/low/close.
    """
    new = 0
    for c in candles:
        cur = db.execute(
            "INSERT INTO candles (time, open, high, low, close) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(time) DO UPDATE SET high=excluded.high, low=excluded.low, close=excluded.close",
            (str(c["time"]), c["open"], c["high"], c["low"], c["close"]))
        new += cur.rowcount
    if commit:
        db.commit()
    return new


def trim_candles(db, *, commit: bool = True) -> None:
    edge = (utcnow() - timedelta(days=CANDLE_KEEP_DAYS)).isoformat()
    db.execute("DELETE FROM candles WHERE time < ?", (edge,))
    if commit:
        db.commit()


def get_candles(db, since: datetime, until: datetime) -> list[dict]:
    rows = db.execute("SELECT time, open, high, low, close FROM candles "
                      "WHERE time >= ? AND time <= ? ORDER BY time",
                      (since.isoformat(), until.isoformat())).fetchall()
    return [dict(r) for r in rows]


def save_state(db, login: int, balance: float, equity: float, currency: str,
               server: str, capital_hist: float = None, *, commit: bool = True) -> None:
    # DATA-02: state/deals/months/commands ключуются одним login, а физический
    # счёт — это login+server. Пока брокер один, номера не пересекаются и
    # проблема не проявляется; со вторым брокером два счёта начали бы молча
    # затирать друг другу баланс и капитал. Переписывать схему ради этого
    # рано — но молчать нельзя, поэтому ловим момент, когда риск станет
    # реальным. ponytail: заметка в логе, не защита; настоящее лечение —
    # составной ключ (login, server) во всех четырёх таблицах
    was = db.execute("SELECT server FROM state WHERE login=?", (int(login),)).fetchone()
    if was and was[0] and server and was[0] != server:
        log.error("DATA-02: счёт %s числится на «%s», а синк пришёл с «%s» — "
                  "историю и баланс этих счетов смешает, нужен ключ login+server",
                  login, was[0], server)
    db.execute(
        "INSERT INTO state (login, balance, equity, currency, server, synced, capital_hist) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(login) DO UPDATE SET balance=excluded.balance, equity=excluded.equity, "
        "currency=excluded.currency, server=excluded.server, synced=excluded.synced, "
        # капитал агент считает по всей истории; если не смог — держим прежний
        "capital_hist=COALESCE(excluded.capital_hist, state.capital_hist)",
        (int(login), balance, equity, currency, server, utcnow().isoformat(), capital_hist))
    if commit:
        db.commit()


def get_state(db, login: int) -> dict | None:
    row = db.execute("SELECT * FROM state WHERE login=?", (int(login),)).fetchone()
    return dict(row) if row else None


def set_command(db, login: int, cmd: str) -> None:
    db.execute("INSERT OR REPLACE INTO commands VALUES (?, ?, ?)",
               (int(login), cmd, utcnow().isoformat()))
    db.commit()


def get_command(db, login: int) -> str | None:
    row = db.execute("SELECT cmd FROM commands WHERE login=?", (int(login),)).fetchone()
    return row["cmd"] if row else None


def clear_command(db, login: int, *, commit: bool = True) -> None:
    db.execute("DELETE FROM commands WHERE login=?", (int(login),))
    if commit:
        db.commit()


def save_sync(db, login: int, state: dict, deals: list[dict], command_done: bool) -> int:
    """Apply one agent packet atomically, including command acknowledgement."""
    with db:
        save_state(db, login, state["balance"], state["equity"],
                   state["currency"], state["server"], state["capital_hist"],
                   commit=False)
        new = save_deals(db, login, deals, commit=False)
        if command_done:
            clear_command(db, login, commit=False)
    return new


def last_ticket(db, login: int) -> int:
    """Максимальный виденный тикет. Берём из state: сделки чистятся помесячно,
    и по пустой таблице агент решил бы, что счёт новый, и залил всё заново."""
    row = db.execute("SELECT MAX(ticket) AS t FROM deals WHERE login=?", (int(login),)).fetchone()
    from_deals = row["t"] or 0
    row = db.execute("SELECT max_ticket FROM state WHERE login=?", (int(login),)).fetchone()
    from_state = (row["max_ticket"] if row else 0) or 0
    return max(from_deals, from_state)


def rollup(db, keep_from: str, is_transfer, is_perf_fee=None, growth_of=None,
          is_profit_side=None, report_from: str = None) -> int:
    """Свернуть сделки старше keep_from ('YYYY-MM-01') в месячные итоги.

    Признак перевода живёт в комментарии сделки, поэтому считаем в Python той
    же функцией, что и везде — чтобы итоги сходились с отчётами.
    Возвращает, сколько сделок убрано: итоги остаются навсегда, детали — нет.

    Свёртка накопительная (ON CONFLICT ... = months.x + excluded.x), а не
    заменяющая: опоздавшая сделка (терминал был выключен, досылает её позже)
    раньше СТИРАЛА весь месяц значением из одной этой строки — сами сделки
    месяца уже удалены прошлой свёрткой, восстановить было нечем.

    profit_carry в state — то же самое, что capital_hist: агент считает его
    сам по полной истории терминала, и он остаётся приоритетом (см.
    trades._profit_on_account). Здесь копится запасной вариант на случай,
    если агент офлайн — без него нераспределённый профит закрытых месяцев
    становился невидим сразу после первой же свёртки (не только «до первого
    ответа агента», а навсегда, потому что деталей сделок уже нет).

    report_from — та же отсечка, что и в trades.REPORT_FROM: живой
    _profit_on_account() считает профит только с неё, а keep_from (граница
    свёртки) может быть заметно раньше (HISTORY_FROM у агента). Без этого
    параметра profit_carry заранее включал бы профит месяцев ДО отсечки, и
    в день, когда такой месяц наконец сворачивается, _profit_on_account()
    скачком менялся бы на его PnL без единой сделки на счёте.
    """
    totals: dict = {}
    months_rows: dict = {}      # сделки месяца — по ним считается доходность
    profit_delta: dict = {}     # login -> сколько профита добавила эта свёртка
    for r in db.execute("SELECT * FROM deals WHERE time < ?", (keep_from,)).fetchall():
        row = dict(r)
        months_rows.setdefault((row["login"], row["time"][:7]), []).append(row)
        key = (row["login"], row["time"][:7])
        acc = totals.setdefault(key, {"trades": 0, "gross": 0.0, "platform": 0.0,
                                      "transfers": 0.0, "deposits": 0.0,
                                      "capital_transfers": 0.0,
                                      "wins": 0, "losses": 0, "best": 0.0,
                                      "worst": 0.0, "volume": 0.0})
        net = row["net"] or 0.0
        counts_as_profit = report_from is None or row["time"] >= report_from
        if row["is_closing"]:
            acc["trades"] += 1
            acc["gross"] += net
            acc["volume"] += row["volume"] or 0.0
            if net > 0:
                acc["wins"] += 1
            elif net < 0:
                acc["losses"] += 1
            acc["best"] = max(acc["best"], net)
            acc["worst"] = min(acc["worst"], net)
            if counts_as_profit:
                profit_delta[row["login"]] = profit_delta.get(row["login"], 0.0) + net
        elif row["is_balance"]:
            if is_perf_fee and is_perf_fee(row):
                # удержание доли брокера уже учтено в net_of_fee — иначе двойной счёт
                if counts_as_profit:
                    profit_delta[row["login"]] = profit_delta.get(row["login"], 0.0) + net
            elif is_transfer(row):
                acc["transfers"] += net
                if net > 0:
                    acc["deposits"] += net
                if is_profit_side and is_profit_side(row):
                    if counts_as_profit:
                        profit_delta[row["login"]] = profit_delta.get(row["login"], 0.0) + net
                else:
                    # только капитал — эту сумму (и только её) можно потом
                    # делить на плечо при реконструкции капитала из архива
                    acc["capital_transfers"] += net
            else:
                acc["platform"] += net

    for (login, month), a in totals.items():
        db.execute(
            "INSERT INTO months (login, month, trades, gross, platform, transfers, "
            "deposits, capital_transfers, wins, losses, best, worst, volume, growth) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            # COALESCE(...,0) на всех колонках, что могли остаться NULL у строк,
            # заведённых до ALTER TABLE ADD COLUMN (без DEFAULT) — иначе
            # NULL+x=NULL и MAX/MIN(NULL,x)=NULL в SQLite тихо стирают всю
            # строку при первом же накоплении новой пачки сверху старой
            "ON CONFLICT(login, month) DO UPDATE SET "
            "trades=COALESCE(months.trades,0)+excluded.trades, "
            "gross=COALESCE(months.gross,0)+excluded.gross, "
            "platform=COALESCE(months.platform,0)+excluded.platform, "
            "transfers=COALESCE(months.transfers,0)+excluded.transfers, "
            "deposits=COALESCE(months.deposits,0)+excluded.deposits, "
            "capital_transfers=COALESCE(months.capital_transfers,0)+excluded.capital_transfers, "
            "wins=COALESCE(months.wins,0)+excluded.wins, "
            "losses=COALESCE(months.losses,0)+excluded.losses, "
            "best=MAX(COALESCE(months.best, excluded.best), excluded.best), "
            "worst=MIN(COALESCE(months.worst, excluded.worst), excluded.worst), "
            "volume=COALESCE(months.volume,0)+excluded.volume, "
            "growth=CASE WHEN excluded.growth IS NULL THEN months.growth "
            "ELSE COALESCE(months.growth, 0) + excluded.growth END",
            (login, month, a["trades"], a["gross"], a["platform"],
             a["transfers"], a["deposits"], a["capital_transfers"], a["wins"], a["losses"],
             a["best"], a["worst"], a["volume"],
             growth_of(login, months_rows.get((login, month), [])) if growth_of else None))

    for login, delta in profit_delta.items():
        db.execute("UPDATE state SET profit_carry = COALESCE(profit_carry, 0) + ? "
                   "WHERE login = ?", (delta, login))

    # тикеты запоминаем до удаления, иначе агент зальёт историю заново
    db.execute("UPDATE state SET max_ticket = MAX(COALESCE(max_ticket, 0), "
               "COALESCE((SELECT MAX(ticket) FROM deals d WHERE d.login = state.login), 0))")
    removed = db.execute("DELETE FROM deals WHERE time < ?", (keep_from,)).rowcount
    db.commit()
    return removed


def months(db, login: int, since: str = None, until: str = None) -> list[dict]:
    """Месячные итоги по счёту, по возрастанию месяца."""
    sql = "SELECT * FROM months WHERE login=?"
    args = [int(login)]
    if since:
        sql += " AND month >= ?"
        args.append(since[:7])
    if until:
        sql += " AND month <= ?"
        args.append(until[:7])
    return [dict(r) for r in db.execute(sql + " ORDER BY month", args).fetchall()]


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["time"] = datetime.fromisoformat(d["time"])
    for flag in ("is_balance", "is_closing", "is_opening"):
        d[flag] = bool(d[flag])
    return d


def fetch(db, login: int, since: datetime, until: datetime) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM deals WHERE login=? AND time BETWEEN ? AND ? ORDER BY time",
        (int(login), since.isoformat(), until.isoformat())).fetchall()
    return [_row(r) for r in rows]


def after_ticket(db, login: int, ticket: int) -> list[dict]:
    rows = db.execute("SELECT * FROM deals WHERE login=? AND ticket>? ORDER BY ticket",
                      (int(login), int(ticket))).fetchall()
    return [_row(r) for r in rows]
