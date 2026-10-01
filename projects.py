"""User projects in the server SQLite database; independent of MT5 accounts."""
from decimal import Decimal
import math
import uuid

CURRENCIES = {"USD", "RUB", "BYN"}
PERIODS = {"day", "week", "month"}
MAX_AMOUNT = 1_000_000_000_000
MAX_RATE = 1000
MAX_ACCOUNTS = 100


def setup(db):
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 96),
            currency TEXT NOT NULL CHECK(currency IN ('USD','RUB','BYN')),
            rate_percent REAL NOT NULL CHECK(rate_percent BETWEEN 0 AND 1000),
            period TEXT NOT NULL CHECK(period IN ('day','week','month')),
            multi INTEGER NOT NULL CHECK(multi IN (0,1))
        );
        CREATE INDEX IF NOT EXISTS projects_owner ON projects(owner_id);
        CREATE TABLE IF NOT EXISTS project_accounts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL DEFAULT '' CHECK(length(name) <= 96),
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0 AND amount_cents <= 100000000000000),
            position INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS project_accounts_project ON project_accounts(project_id, position);
    """)


def text(value, required=False):
    if not isinstance(value, str) or "\x00" in value or len(value.strip()) > 96 or (required and not value.strip()):
        raise ValueError("Укажите название длиной до 96 символов")
    return value.strip()


def numeric(value, maximum, *, amount=False):
    if type(value) not in (int, float) or not 0 <= value <= maximum or not math.isfinite(value):
        raise ValueError("Сумма или процент вне допустимого диапазона")
    decimal = Decimal(str(value))
    if amount:
        if decimal <= 0 or decimal * 100 != (decimal * 100).to_integral_value():
            raise ValueError("Сумма должна быть больше нуля и содержать не более двух знаков после запятой")
        return int(decimal * 100)
    if decimal != decimal.quantize(Decimal("0.0001")):
        raise ValueError("Процент: не более четырёх знаков после запятой")
    return float(decimal)


def get(db, owner, project_id):
    row = db.execute("SELECT id,name,currency,rate_percent,period,multi FROM projects WHERE id=? AND owner_id=?",
                     (project_id, str(owner))).fetchone()
    if row is None:
        raise LookupError("Проект не найден")
    result = dict(zip(("id", "name", "currency", "rate_percent", "period", "multi"), row))
    result["multi"] = bool(result["multi"])
    rows = db.execute("SELECT id,name,amount_cents FROM project_accounts WHERE project_id=? ORDER BY position,id",
                      (project_id,)).fetchall()
    result["accounts"] = [{"id": r[0], "project_id": project_id, "name": r[1], "amount": r[2] / 100} for r in rows]
    cents = sum(r[2] for r in rows)
    result["total"] = cents / 100
    result["expected_income"] = float(Decimal(cents) * Decimal(str(result["rate_percent"])) / 10000)
    return result


def list_for(db, owner):
    return [get(db, owner, r[0]) for r in db.execute("SELECT id FROM projects WHERE owner_id=? ORDER BY rowid", (str(owner),)).fetchall()]


def save(db, owner, data, project_id=None):
    with db:
        old = get(db, owner, project_id) if project_id else None
        merged = {**(old or {}), **data}
        name = text(merged.get("name"), True)
        currency, period, multi = merged.get("currency"), merged.get("period"), merged.get("multi", False)
        if not isinstance(currency, str) or currency not in CURRENCIES or not isinstance(period, str) or period not in PERIODS or type(multi) is not bool:
            raise ValueError("Проверьте валюту, период и режим аккаунтов")
        rate = numeric(merged.get("rate_percent"), MAX_RATE)
        if old and currency != old["currency"]:
            raise ValueError("Валюту проекта с вложениями менять нельзя. Создайте отдельный проект")
        rows = merged.get("accounts")
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ACCOUNTS or (not multi and len(rows) != 1):
            raise ValueError("Нужен один аккаунт или до 100 аккаунтов в режиме «Несколько аккаунтов»")
        existing = {a["id"] for a in old["accounts"]} if old else set()
        prepared, ids = [], set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Некорректный аккаунт проекта")
            account_id = row.get("id")
            if account_id is not None and (not isinstance(account_id, str) or account_id not in existing):
                raise LookupError("Аккаунт проекта не найден")
            account_id = account_id or uuid.uuid4().hex
            if account_id in ids:
                raise ValueError("Аккаунт указан дважды")
            ids.add(account_id)
            prepared.append((account_id, text(row.get("name", "")), numeric(row.get("amount"), MAX_AMOUNT, amount=True)))
        if sum(row[2] for row in prepared) > MAX_AMOUNT * 100:
            raise ValueError("Общая сумма проекта превышает допустимый предел")
        project_id = project_id or uuid.uuid4().hex
        if old:
            db.execute("UPDATE projects SET name=?,currency=?,rate_percent=?,period=?,multi=? WHERE id=? AND owner_id=?",
                       (name, currency, rate, period, int(multi), project_id, str(owner)))
            db.execute("DELETE FROM project_accounts WHERE project_id=?", (project_id,))
        else:
            db.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?)", (project_id, str(owner), name, currency, rate, period, int(multi)))
        db.executemany("INSERT INTO project_accounts VALUES (?,?,?,?,?)",
                       [(aid, project_id, title, cents, i) for i, (aid, title, cents) in enumerate(prepared)])
        return get(db, owner, project_id)


def delete(db, owner, project_id):
    with db:
        get(db, owner, project_id)
        db.execute("DELETE FROM projects WHERE id=? AND owner_id=?", (project_id, str(owner)))


def account_change(db, owner, project_id, data, account_id=None, *, remove=False):
    with db:
        project = get(db, owner, project_id)
        rows = project["accounts"]
        if account_id:
            index = next((i for i, a in enumerate(rows) if a["id"] == account_id), None)
            if index is None:
                raise LookupError("Аккаунт проекта не найден")
            if remove:
                if len(rows) == 1:
                    raise ValueError("Последний аккаунт удаляется вместе с проектом")
                rows.pop(index)
            else:
                rows[index] = {**rows[index], **{k: v for k, v in data.items() if k in {"name", "amount"}}}
        else:
            if not project["multi"]:
                raise ValueError("Сначала включите «Несколько аккаунтов»")
            rows.append({"name": data.get("name", ""), "amount": data.get("amount")})
        return save(db, owner, {"accounts": rows}, project_id)
