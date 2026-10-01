"""User projects in the server SQLite database; independent of MT5 accounts."""
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
import calendar
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
            multi INTEGER NOT NULL CHECK(multi IN (0,1)),
            capitalization INTEGER NOT NULL DEFAULT 0 CHECK(capitalization IN (0,1)),
            capitalization_from TEXT
        );
        CREATE INDEX IF NOT EXISTS projects_owner ON projects(owner_id);
        CREATE TABLE IF NOT EXISTS project_accounts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL DEFAULT '' CHECK(length(name) <= 96),
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0 AND amount_cents <= 100000000000000),
            position INTEGER NOT NULL,
            rate_percent REAL CHECK(rate_percent IS NULL OR rate_percent BETWEEN 0 AND 1000),
            capitalization INTEGER CHECK(capitalization IS NULL OR capitalization IN (0,1)),
            capitalization_from TEXT,
            bonus_cents INTEGER,
            bonus_activated_at TEXT,
            bonus_expires_at TEXT,
            bonus_capitalization INTEGER NOT NULL DEFAULT 0 CHECK(bonus_capitalization IN (0,1))
        );
        CREATE INDEX IF NOT EXISTS project_accounts_project ON project_accounts(project_id, position);
    """)
    for table, fields in {
        "projects": {"capitalization":"INTEGER NOT NULL DEFAULT 0 CHECK(capitalization IN (0,1))", "capitalization_from":"TEXT"},
        "project_accounts": {"rate_percent":"REAL CHECK(rate_percent IS NULL OR rate_percent BETWEEN 0 AND 1000)", "capitalization":"INTEGER CHECK(capitalization IS NULL OR capitalization IN (0,1))", "capitalization_from":"TEXT", "bonus_cents":"INTEGER", "bonus_activated_at":"TEXT", "bonus_expires_at":"TEXT", "bonus_capitalization":"INTEGER NOT NULL DEFAULT 0 CHECK(bonus_capitalization IN (0,1))"},
    }.items():
        existing = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        for name, definition in fields.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    db.execute("UPDATE projects SET capitalization_from=? WHERE capitalization_from IS NULL", (today().isoformat(),))
    db.commit()


def today():
    return datetime.now(timezone(timedelta(hours=3))).date()


def start_date(value):
    if not isinstance(value, str):
        raise ValueError("Укажите дату начала капитализации")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Некорректная дата начала капитализации") from None
    if parsed.isoformat() != value or not date(2000, 1, 1) <= parsed <= today():
        raise ValueError("Дата начала: с 2000 года до сегодняшнего дня")
    return value


def periods_since(start, period, end):
    first = date.fromisoformat(start)
    days = max(0, (end-first).days)
    if period != "month":
        return days // (7 if period == "week" else 1)
    months = max(0, (end.year-first.year)*12 + end.month-first.month)
    anniversary = min(first.day, calendar.monthrange(end.year, end.month)[1])
    return max(0, months-(end.day < anniversary))


def valid_expiration(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("Укажите срок действия бонуса")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Некорректный срок действия бонуса") from None
    if parsed.tzinfo is None:
        raise ValueError("У срока бонуса должен быть часовой пояс")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def optional_amount(value):
    if value is None or value == "":
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= MAX_AMOUNT:
        raise ValueError("Бонус должен быть конечной неотрицательной суммой")
    amount = Decimal(str(value))
    if amount * 100 != (amount * 100).to_integral_value():
        raise ValueError("Бонус должен содержать не более двух знаков после запятой")
    return int(amount * 100) or None


def valid_activation(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Некорректное время активации бонуса")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Некорректное время активации бонуса") from None
    if parsed.tzinfo is None:
        raise ValueError("У времени активации должен быть часовой пояс")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def bonus_active(account, now=None):
    if not account.get("bonus_amount") or not account.get("bonus_expires_at"):
        return False
    expiry = datetime.fromisoformat(account["bonus_expires_at"].replace("Z", "+00:00"))
    return expiry > (now or datetime.now(timezone.utc))


def forecast(db, owner, project_id, until, include_bonus=True):
    project = get(db, owner, project_id)
    try:
        target = date.fromisoformat(until)
    except (TypeError, ValueError):
        raise ValueError("Укажите корректную дату прогноза") from None
    start = today()
    if target < start or target > start + timedelta(days=3660):
        raise ValueError("Дата прогноза должна быть в пределах 10 лет")
    now = datetime.now(timezone.utc)
    total = initial = Decimal(0)
    for account in project["accounts"]:
        rate = Decimal(str(account["rate_percent"] if account["rate_percent"] is not None else project["rate_percent"])) / 100
        cap = account["capitalization"] if account["capitalization"] is not None else project["capitalization"]
        principal = Decimal(str(account["current_amount"] if account["current_amount"] is not None else account["amount"]))
        periods = fractional_periods(start, target, project["period"])
        personal = principal * ((1 + rate) ** Decimal(str(periods)) if cap else (1 + rate * Decimal(str(periods))))
        total += personal
        initial += principal
        if include_bonus and account["bonus_active"]:
            bonus = Decimal(str(account["bonus_amount"]))
            expiry = datetime.fromisoformat(account["bonus_expires_at"].replace("Z", "+00:00"))
            if expiry > now:
                end = min(target, expiry.date())
                if target < expiry.date() or (target == expiry.date() and expiry.time() > datetime.min.time()):
                    span = fractional_periods(start, target, project["period"])
                    participating = True
                else:
                    span = fractional_periods(start, end, project["period"])
                    participating = False
                bonus_value = bonus * ((1 + rate) ** Decimal(str(span)) if account["bonus_capitalization"] else (1 + rate * Decimal(str(span))))
                if participating:
                    total += bonus_value
                    initial += bonus
    if total > MAX_AMOUNT or initial > MAX_AMOUNT:
        return {"project_id": project_id, "currency": project["currency"], "total": None, "income": None, "calculation_limited": True, "until": target.isoformat(), "includes_bonus": bool(include_bonus)}
    return {"project_id": project_id, "currency": project["currency"], "total": float(total), "income": float(total - initial), "calculation_limited": False, "until": target.isoformat(), "includes_bonus": bool(include_bonus)}


def fractional_periods(start, end, period):
    days = (end - start).days
    if period == "day":
        return days
    if period == "week":
        return days / 7
    months = max(0, (end.year - start.year) * 12 + end.month - start.month)
    anniversary_day = min(start.day, calendar.monthrange(end.year, end.month)[1])
    completed = max(0, months - (end.day < anniversary_day))
    anchor_year = start.year + (start.month - 1 + completed) // 12
    anchor_month = (start.month - 1 + completed) % 12 + 1
    anchor_day = min(start.day, calendar.monthrange(anchor_year, anchor_month)[1])
    anchor = date(anchor_year, anchor_month, anchor_day)
    next_month = anchor_month % 12 + 1
    next_year = anchor_year + (anchor_month == 12)
    next_anchor = date(next_year, next_month, min(start.day, calendar.monthrange(next_year, next_month)[1]))
    return completed + (end - anchor).days / max(1, (next_anchor - anchor).days)


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
    row = db.execute("SELECT id,name,currency,rate_percent,period,multi,capitalization,capitalization_from FROM projects WHERE id=? AND owner_id=?",
                     (project_id, str(owner))).fetchone()
    if row is None:
        raise LookupError("Проект не найден")
    result = dict(zip(("id", "name", "currency", "rate_percent", "period", "multi", "capitalization", "capitalization_from"), row))
    result["multi"] = bool(result["multi"])
    result["capitalization"] = bool(result["capitalization"])
    result["calculation_date"] = today().isoformat()
    rows = db.execute("SELECT id,name,amount_cents,rate_percent,capitalization,capitalization_from,bonus_cents,bonus_activated_at,bonus_expires_at,bonus_capitalization FROM project_accounts WHERE project_id=? ORDER BY position,id",
                      (project_id,)).fetchall()
    now = datetime.now(timezone.utc)
    result["accounts"] = [{"id": r[0], "project_id": project_id, "name": r[1], "amount": r[2] / 100, "rate_percent": r[3], "capitalization": bool(r[4]) if r[4] is not None else None, "capitalization_from":r[5], "bonus_amount": r[6] / 100 if r[6] is not None else None, "bonus_activated_at": r[7], "bonus_expires_at": r[8], "bonus_capitalization": bool(r[9]), "bonus_active": bool(r[6] and r[8] and datetime.fromisoformat(r[8].replace('Z', '+00:00')) > now)} for r in rows]
    cents = sum(r[2] for r in rows)
    result["total"] = cents / 100
    current_total = income = bonus_total = Decimal(0)
    for account, row in zip(result["accounts"], rows):
        rate = Decimal(str(account["rate_percent"] if account["rate_percent"] is not None else result["rate_percent"])) / 100
        amount = Decimal(row[2]) / 100
        account["current_amount"] = float(amount)
        current_total += amount
        bonus = Decimal(row[6] or 0) / 100
        account["bonus_current_amount"] = float(bonus)
        if account["bonus_active"]:
            bonus_total += bonus
        income += (amount + (bonus if account["bonus_active"] else 0))*rate
        account["working_amount"] = None if account["current_amount"] is None else float(amount + (bonus if account["bonus_active"] else 0))
    result["calculation_limited"] = current_total > MAX_AMOUNT or income > MAX_AMOUNT
    result["current_total"] = float(current_total)
    result["expected_income"] = float(income)
    result["personal_total"] = result["current_total"]
    result["bonus_total"] = float(bonus_total)
    result["working_total"] = None if result["calculation_limited"] else float(current_total + bonus_total)
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
        capitalization = merged.get("capitalization", False)
        if type(capitalization) is not bool:
            raise ValueError("Некорректный режим капитализации")
        capitalization_from = start_date(merged.get("capitalization_from", today().isoformat()))
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
            prepared.append((account_id, text(row.get("name", "")), numeric(row.get("amount"), MAX_AMOUNT, amount=True),
                             numeric(row["rate_percent"], MAX_RATE) if row.get("rate_percent") is not None else None,
                             row.get("capitalization"), start_date(row["capitalization_from"]) if row.get("capitalization_from") is not None else (None if old is None or row.get("id") else today().isoformat()),
                             optional_amount(row.get("bonus_amount")), valid_activation(row.get("bonus_activated_at")), valid_expiration(row.get("bonus_expires_at")), row.get("bonus_capitalization", False)))
            if row.get("capitalization") is not None and type(row["capitalization"]) is not bool:
                raise ValueError("Некорректный режим капитализации аккаунта")
            if type(row.get("bonus_capitalization", False)) is not bool:
                raise ValueError("Некорректный режим капитализации бонуса")
            if prepared[-1][6] is not None and not prepared[-1][8]:
                raise ValueError("Для бонуса укажите дату окончания")
            if prepared[-1][6] is None:
                prepared[-1] = (*prepared[-1][:6], None, None, None, False)
        if sum(row[2] for row in prepared) > MAX_AMOUNT * 100:
            raise ValueError("Общая сумма проекта превышает допустимый предел")
        project_id = project_id or uuid.uuid4().hex
        if old:
            db.execute("UPDATE projects SET name=?,currency=?,rate_percent=?,period=?,multi=?,capitalization=?,capitalization_from=? WHERE id=? AND owner_id=?",
                       (name, currency, rate, period, int(multi), int(capitalization), capitalization_from, project_id, str(owner)))
            db.execute("DELETE FROM project_accounts WHERE project_id=?", (project_id,))
        else:
            db.execute("INSERT INTO projects (id,owner_id,name,currency,rate_percent,period,multi,capitalization,capitalization_from) VALUES (?,?,?,?,?,?,?,?,?)", (project_id, str(owner), name, currency, rate, period, int(multi), int(capitalization), capitalization_from))
        db.executemany("INSERT INTO project_accounts (id,project_id,name,amount_cents,position,rate_percent,capitalization,capitalization_from,bonus_cents,bonus_activated_at,bonus_expires_at,bonus_capitalization) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       [(aid, project_id, title, cents, i, rate, cap, start, bonus, activated or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if bonus else None, expires, int(bonus_cap)) for i, (aid, title, cents, rate, cap, start, bonus, activated, expires, bonus_cap) in enumerate(prepared)])
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
                rows[index] = {**rows[index], **{k: v for k, v in data.items() if k in {"name", "amount", "rate_percent", "capitalization", "capitalization_from", "bonus_amount", "bonus_activated_at", "bonus_expires_at", "bonus_capitalization"}}}
        else:
            if not project["multi"]:
                raise ValueError("Сначала включите «Несколько аккаунтов»")
            rows.append({"name": data.get("name", ""), "amount": data.get("amount"), "rate_percent": data.get("rate_percent"), "capitalization":data.get("capitalization"), "capitalization_from":data.get("capitalization_from", today().isoformat()), "bonus_amount":data.get("bonus_amount"), "bonus_activated_at":data.get("bonus_activated_at"), "bonus_expires_at":data.get("bonus_expires_at"), "bonus_capitalization":data.get("bonus_capitalization", False)})
        return save(db, owner, {"accounts": rows}, project_id)
