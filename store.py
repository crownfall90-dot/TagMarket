"""Хранилище сделок на сервере.

Агент на Windows читает терминал MT5 и присылает сделки сюда, бот берёт их
отсюда. Так бот живёт на сервере 24/7, а отчёты строятся из базы мгновенно —
без переключения терминала на каждый счёт.

Схема специально плоская: сделка целиком, как её отдал MT5, плюс логин счёта.
"""

import os
import sqlite3
from datetime import datetime, timezone


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
    max_ticket INTEGER DEFAULT 0   -- переживает чистку сделок: иначе агент
);                                 -- решит, что счёт новый, и зальёт всё заново

-- Сделки храним за текущий месяц, прошлые сворачиваем сюда: детали за годы
-- не нужны, а итоги должны остаться навсегда.
CREATE TABLE IF NOT EXISTS months (
    login     INTEGER NOT NULL,
    month     TEXT    NOT NULL,    -- 'YYYY-MM'
    trades    INTEGER,             -- сколько закрытых сделок
    gross     REAL,                -- их результат до комиссии брокера
    platform  REAL,                -- платы платформы за месяц
    transfers REAL,                -- пополнения и выводы
    deposits  REAL,                -- только пополнения — база для процентов
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
"""


def open_db(path: str = None) -> sqlite3.Connection:
    db = sqlite3.connect(path or DB)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    # база могла остаться от прежней версии — дописываем недостающие колонки
    have = {r["name"] for r in db.execute("PRAGMA table_info(state)").fetchall()}
    if "max_ticket" not in have:
        db.execute("ALTER TABLE state ADD COLUMN max_ticket INTEGER DEFAULT 0")
    # колонки статистики появились позже — базы прошлых версий дополняем
    have = {r["name"] for r in db.execute("PRAGMA table_info(months)").fetchall()}
    for col, kind in (("wins", "INTEGER"), ("losses", "INTEGER"),
                      ("best", "REAL"), ("worst", "REAL"), ("volume", "REAL"),
                      ("growth", "REAL")):
        if col not in have:
            db.execute(f"ALTER TABLE months ADD COLUMN {col} {kind}")
    db.commit()
    return db


FIELDS = ("ticket", "time", "symbol", "side", "volume", "price", "profit", "swap",
          "commission", "net", "is_balance", "is_closing", "is_opening", "comment")


def save_deals(db, login: int, deals: list[dict]) -> int:
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
    db.commit()
    return new


def save_state(db, login: int, balance: float, equity: float, currency: str, server: str) -> None:
    db.execute(
        "INSERT INTO state (login, balance, equity, currency, server, synced) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(login) DO UPDATE SET balance=excluded.balance, equity=excluded.equity, "
        "currency=excluded.currency, server=excluded.server, synced=excluded.synced",
        (int(login), balance, equity, currency, server, utcnow().isoformat()))
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


def clear_command(db, login: int) -> None:
    db.execute("DELETE FROM commands WHERE login=?", (int(login),))
    db.commit()


def last_ticket(db, login: int) -> int:
    """Максимальный виденный тикет. Берём из state: сделки чистятся помесячно,
    и по пустой таблице агент решил бы, что счёт новый, и залил всё заново."""
    row = db.execute("SELECT MAX(ticket) AS t FROM deals WHERE login=?", (int(login),)).fetchone()
    from_deals = row["t"] or 0
    row = db.execute("SELECT max_ticket FROM state WHERE login=?", (int(login),)).fetchone()
    from_state = (row["max_ticket"] if row else 0) or 0
    return max(from_deals, from_state)


def rollup(db, keep_from: str, is_transfer, is_perf_fee=None, growth_of=None) -> int:
    """Свернуть сделки старше keep_from ('YYYY-MM-01') в месячные итоги.

    Признак перевода живёт в комментарии сделки, поэтому считаем в Python той
    же функцией, что и везде — чтобы итоги сходились с отчётами.
    Возвращает, сколько сделок убрано: итоги остаются навсегда, детали — нет.
    """
    totals: dict = {}
    months_rows: dict = {}      # сделки месяца — по ним считается доходность
    for r in db.execute("SELECT * FROM deals WHERE time < ?", (keep_from,)).fetchall():
        row = dict(r)
        months_rows.setdefault((row["login"], row["time"][:7]), []).append(row)
        key = (row["login"], row["time"][:7])
        acc = totals.setdefault(key, {"trades": 0, "gross": 0.0, "platform": 0.0,
                                      "transfers": 0.0, "deposits": 0.0,
                                      "wins": 0, "losses": 0, "best": 0.0,
                                      "worst": 0.0, "volume": 0.0})
        if row["is_closing"]:
            net = row["net"] or 0.0
            acc["trades"] += 1
            acc["gross"] += net
            acc["volume"] += row["volume"] or 0.0
            if net > 0:
                acc["wins"] += 1
            elif net < 0:
                acc["losses"] += 1
            acc["best"] = max(acc["best"], net)
            acc["worst"] = min(acc["worst"], net)
        elif row["is_balance"]:
            if is_transfer(row):
                acc["transfers"] += row["net"] or 0.0
                if (row["net"] or 0.0) > 0:
                    acc["deposits"] += row["net"]
            elif not (is_perf_fee and is_perf_fee(row)):
                # удержание доли брокера уже учтено в net_of_fee — иначе двойной счёт
                acc["platform"] += row["net"] or 0.0

    for (login, month), a in totals.items():
        db.execute(
            "INSERT INTO months (login, month, trades, gross, platform, transfers, "
            "deposits, wins, losses, best, worst, volume, growth) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(login, month) DO UPDATE SET trades=excluded.trades, "
            "gross=excluded.gross, platform=excluded.platform, "
            "transfers=excluded.transfers, deposits=excluded.deposits, "
            "wins=excluded.wins, losses=excluded.losses, best=excluded.best, "
            "worst=excluded.worst, volume=excluded.volume, growth=excluded.growth",
            (login, month, a["trades"], a["gross"], a["platform"],
             a["transfers"], a["deposits"], a["wins"], a["losses"],
             a["best"], a["worst"], a["volume"],
             growth_of(login, months_rows.get((login, month), [])) if growth_of else None))

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
