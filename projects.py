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
            business_days_only INTEGER NOT NULL DEFAULT 0 CHECK(business_days_only IN (0,1)),
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
            bonus_capitalization INTEGER NOT NULL DEFAULT 0 CHECK(bonus_capitalization IN (0,1)),
            fixed_income_cents INTEGER CHECK(fixed_income_cents IS NULL OR (fixed_income_cents > 0 AND fixed_income_cents <= 100000000000000))
        );
        CREATE INDEX IF NOT EXISTS project_accounts_project ON project_accounts(project_id, position);
    """)
    for table, fields in {
        "projects": {"business_days_only":"INTEGER NOT NULL DEFAULT 0 CHECK(business_days_only IN (0,1))", "capitalization":"INTEGER NOT NULL DEFAULT 0 CHECK(capitalization IN (0,1))", "capitalization_from":"TEXT", "income_fixed_cents":"INTEGER CHECK(income_fixed_cents IS NULL OR income_fixed_cents > 0)"},
        "project_accounts": {"rate_percent":"REAL CHECK(rate_percent IS NULL OR rate_percent BETWEEN 0 AND 1000)", "capitalization":"INTEGER CHECK(capitalization IS NULL OR capitalization IN (0,1))", "capitalization_from":"TEXT", "bonus_cents":"INTEGER", "bonus_activated_at":"TEXT", "bonus_expires_at":"TEXT", "bonus_capitalization":"INTEGER NOT NULL DEFAULT 0 CHECK(bonus_capitalization IN (0,1))", "fixed_income_cents":"INTEGER CHECK(fixed_income_cents IS NULL OR (fixed_income_cents > 0 AND fixed_income_cents <= 100000000000000))"},
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


def periods_since(start, period, end, business_days_only=False):
    first = date.fromisoformat(start)
    days = max(0, (end-first).days)
    if period != "month":
        if period == "week":
            return days // 7
        if business_days_only:
            weeks, remainder = divmod(days, 7)
            elapsed = weeks * 5
            cursor = first + timedelta(days=weeks * 7)
            return elapsed + sum((cursor + timedelta(days=i)).weekday() < 5 for i in range(remainder))
        return days
    months = max(0, (end.year-first.year)*12 + end.month-first.month)
    anniversary = min(first.day, calendar.monthrange(end.year, end.month)[1])
    return max(0, months-(end.day < anniversary))


def period_days(period, on=None):
    """Календарных дней в периоде ставки: день — 1, неделя — 7, месяц — дней в текущем месяце.

    Те же единицы, что в fractional_periods: неделя = 7 календарных дней, месяц —
    фактическая длина календарного месяца."""
    if period == "day":
        return 1
    if period == "week":
        return 7
    on = on or today()
    return calendar.monthrange(on.year, on.month)[1]


def daily_rate_percent(rate_percent, period, on=None):
    """Средний процент в день: ставка за день остаётся как есть, недельная и месячная делятся на дни периода."""
    return float(Decimal(str(rate_percent)) / period_days(period, on))


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


def optional_fixed(value):
    """Фиксированная доплата аккаунту за период проекта: пусто или 0 — без доплаты."""
    if value is None or value == "":
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= MAX_AMOUNT:
        raise ValueError("Фиксированная сумма аккаунта должна быть конечной неотрицательной суммой")
    amount = Decimal(str(value))
    if amount * 100 != (amount * 100).to_integral_value():
        raise ValueError("Фиксированная сумма аккаунта: не более двух знаков после запятой")
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
    now = now or datetime.now(timezone.utc)
    expiry = datetime.fromisoformat(account["bonus_expires_at"].replace("Z", "+00:00"))
    activated = account.get("bonus_activated_at")
    if activated:
        activated_at = datetime.fromisoformat(activated.replace("Z", "+00:00"))
        if activated_at > now:
            return False
    return expiry > now


def _growth(amount, rate, periods, compound):
    factor = (Decimal(1) + rate) ** Decimal(str(periods)) if compound else Decimal(1) + rate * Decimal(str(periods))
    return amount * factor


def _month_after(start):
    month = start.month % 12 + 1
    year = start.year + (start.month == 12)
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _bounded(value):
    return None if value > MAX_AMOUNT else float(value)


def _current_account(account, project, as_of):
    rate = Decimal(str(account["rate_percent"] if account["rate_percent"] is not None else project["rate_percent"])) / 100
    enabled = account["capitalization"] if account["capitalization"] is not None else project["capitalization"]
    personal = Decimal(str(account["amount"]))
    if enabled:
        start = account["capitalization_from"] or project["capitalization_from"]
        personal = _growth(personal, rate, periods_since(start, project["period"], as_of,
                            project.get("business_days_only", False)), True)
    bonus = Decimal(0)
    if account["bonus_active"]:
        bonus = Decimal(str(account["bonus_amount"]))
        if account["bonus_capitalization"]:
            activated = datetime.fromisoformat((account["bonus_activated_at"] or "").replace("Z", "+00:00")) if account["bonus_activated_at"] else datetime.combine(as_of, datetime.min.time(), timezone.utc)
            bonus = _growth(bonus, rate, periods_since(activated.date().isoformat(), project["period"], as_of,
                                project.get("business_days_only", False)), True)
    return rate, bool(enabled), personal, bonus


def _checkpoint(project, accounts, target, include_bonus, start):
    details = []
    personal_total = bonus_total = fixed_total = total = initial = Decimal(0)
    for account in accounts:
        rate, personal_cap, personal_now, bonus_now = account["_current"]
        business_only = project.get("business_days_only", False)
        periods_to_target = fractional_periods(start, target, project["period"], business_only)
        personal = _growth(personal_now, rate, periods_to_target, personal_cap)
        fixed_extra = Decimal(str(account.get("fixed_income") or 0)) * Decimal(str(periods_to_target))  # доплата не капитализируется
        bonus = Decimal(0)
        bonus_expires = None
        if include_bonus and account["bonus_active"]:
            expiry = datetime.fromisoformat(account["bonus_expires_at"].replace("Z", "+00:00"))
            bonus_expires = expiry.date()
            end_of_target = datetime.combine(target, datetime.max.time(), timezone.utc)
            active_at_checkpoint = expiry > end_of_target
            if target == start:
                active_at_checkpoint = expiry > datetime.now(timezone.utc)
            if active_at_checkpoint:
                span = fractional_periods(start, target, project["period"], business_only)
                bonus = _growth(bonus_now, rate, span, account["bonus_capitalization"])
        working = personal + bonus + fixed_extra
        fixed_total += fixed_extra
        initial += personal_now + (bonus_now if include_bonus and account["bonus_active"] else 0)
        personal_total += personal
        bonus_total += bonus
        total += working
        details.append({
            "account_id": account["id"], "name": account["name"],
            "currency": project["currency"], "rate_percent": float(rate * 100),
            "current_personal": _bounded(personal_now),
            "current_bonus": _bounded(bonus_now) if include_bonus and account["bonus_active"] else 0,
            "current_working": _bounded(personal_now + (bonus_now if include_bonus and account["bonus_active"] else 0)),
            "personal": _bounded(personal), "bonus": _bounded(bonus), "fixed": _bounded(fixed_extra),
            "working": _bounded(working), "growth": _bounded(working - (personal_now + (bonus_now if include_bonus and account["bonus_active"] else 0))),
            "personal_capitalization": personal_cap,
            "bonus_capitalization": bool(account["bonus_capitalization"]),
            "bonus_active": bool(include_bonus and account["bonus_active"] and (bonus_expires is not None) and (target == start or active_at_checkpoint)),
            "bonus_expires_at": account["bonus_expires_at"],
            "calculation_limited": any(value is None for value in (_bounded(personal_now), _bounded(personal), _bounded(working))),
        })
    limited = total > MAX_AMOUNT or initial > MAX_AMOUNT or any(a["calculation_limited"] for a in details)
    return {
        "until": target.isoformat(), "currency": project["currency"],
        "personal": _bounded(personal_total), "bonus": _bounded(bonus_total), "fixed": _bounded(fixed_total),
        "total": None if limited else float(total),
        "growth": None if limited else float(total - initial),
        "calculation_limited": limited, "accounts": details,
    }


def forecast(db, owner, project_id, until, include_bonus=True):
    project = get(db, owner, project_id)
    try:
        target = date.fromisoformat(until)
    except (TypeError, ValueError):
        raise ValueError("Укажите корректную дату прогноза") from None
    start = today()
    if target < start or target > start + timedelta(days=3660):
        raise ValueError("Дата прогноза должна быть в пределах 10 лет")
    accounts = []
    for source in project["accounts"]:
        account = dict(source)
        account["_current"] = _current_account(account, project, start)
        accounts.append(account)
    dates = {
        "now": start,
        "day": start + timedelta(days=1),
        "week": start + timedelta(days=7),
        "month": _month_after(start),
        "selected": target,
    }
    checkpoints = {key: _checkpoint(project, accounts, when, include_bonus, start) for key, when in dates.items()}
    current = checkpoints["now"]
    selected = checkpoints["selected"]
    return {
        "project_id": project_id, "currency": project["currency"], "until": target.isoformat(),
        "includes_bonus": bool(include_bonus), "current": current,
        "checkpoints": checkpoints, "accounts": selected["accounts"],
        "total": selected["total"], "income": selected["growth"],
        "calculation_limited": selected["calculation_limited"],
    }


def fractional_periods(start, end, period, business_days_only=False):
    days = (end - start).days
    if period == "day":
        if business_days_only:
            weeks, remainder = divmod(max(0, days), 7)
            cursor = start + timedelta(days=weeks * 7)
            return weeks * 5 + sum((cursor + timedelta(days=i)).weekday() < 5 for i in range(remainder))
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


TAG_MIN_DAYS = 5
TAG_WINDOW_DAYS = 30


def weekdays_between(start, end):
    """Будние дни в (start, end]: сегодняшний день ещё не завершён и не считается."""
    days = max(0, (end - start).days)
    weeks, remainder = divmod(days, 7)
    first = start + timedelta(days=1 + weeks * 7)
    return weeks * 5 + sum((first + timedelta(days=i)).weekday() < 5 for i in range(remainder))


def tag_return_stats(days):
    """Средняя историческая доходность TagMarket по завершённым торговым дням.

    days — [{"day", "net", "base"}]: чистый результат дня и капитал на его начало
    (сумма по собственным счетам, в одной валюте). День без положительной базы
    не входит в выборку. Берутся последние TAG_WINDOW_DAYS таких дней; меньше
    TAG_MIN_DAYS — прогноз не строится. Нулевые дни не добавляются: в выборке
    только дни, когда счета реально торговали.
    """
    valid = sorted((d for d in days if d["base"] > 0 and math.isfinite(d["net"])), key=lambda d: d["day"])
    window = valid[-TAG_WINDOW_DAYS:]
    returns = [d["net"] / d["base"] for d in window]
    average = sum(returns) / len(returns) if returns else None
    sufficient = len(returns) >= TAG_MIN_DAYS and average is not None and average > -1
    return {
        "sufficient": sufficient, "days_used": len(returns), "min_days": TAG_MIN_DAYS,
        "window_days": TAG_WINDOW_DAYS,
        "average_daily_return": average if sufficient else None,
        "average_daily_profit": sum(d["net"] for d in window) / len(window) if window else None,
        "from": window[0]["day"] if window else None, "to": window[-1]["day"] if window else None,
    }


def tag_forecast(days, start, target):
    """Множители капитала TagMarket: (1 + средняя дневная доходность) ^ торговые дни."""
    stats = tag_return_stats(days)
    dates = {"day": start + timedelta(days=1), "week": start + timedelta(days=7),
             "month": _month_after(start), "selected": target}
    counts = {key: weekdays_between(start, when) for key, when in dates.items()}
    multipliers = {}
    for key, count in counts.items():
        value = (1 + stats["average_daily_return"]) ** count if stats["sufficient"] else None
        multipliers[key] = value if value is not None and math.isfinite(value) else None
    return {**stats, "until": target.isoformat(), "trading_days": counts, "multipliers": multipliers,
            "model": "compound_average_daily_return"}


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
    row = db.execute("SELECT id,name,currency,rate_percent,period,multi,business_days_only,capitalization,capitalization_from,income_fixed_cents FROM projects WHERE id=? AND owner_id=?",
                     (project_id, str(owner))).fetchone()
    if row is None:
        raise LookupError("Проект не найден")
    result = dict(zip(("id", "name", "currency", "rate_percent", "period", "multi", "business_days_only", "capitalization", "capitalization_from", "income_fixed_cents"), row))
    fixed_cents = result.pop("income_fixed_cents")
    result["income_mode"] = "fixed" if fixed_cents else "percent"
    result["fixed_income"] = fixed_cents / 100 if fixed_cents else None
    result["multi"] = bool(result["multi"])
    result["business_days_only"] = bool(result["business_days_only"])
    result["capitalization"] = bool(result["capitalization"])
    result["calculation_date"] = today().isoformat()
    rows = db.execute("SELECT id,name,amount_cents,rate_percent,capitalization,capitalization_from,bonus_cents,bonus_activated_at,bonus_expires_at,bonus_capitalization,fixed_income_cents FROM project_accounts WHERE project_id=? ORDER BY position,id",
                      (project_id,)).fetchall()
    now = datetime.now(timezone.utc)
    result["accounts"] = [{"id": r[0], "project_id": project_id, "position": index + 1, "name": r[1], "amount": r[2] / 100, "rate_percent": r[3], "capitalization": bool(r[4]) if r[4] is not None else None, "capitalization_from":r[5], "bonus_amount": r[6] / 100 if r[6] is not None else None, "bonus_activated_at": r[7], "bonus_expires_at": r[8], "bonus_capitalization": bool(r[9]), "fixed_income": r[10] / 100 if r[10] else None, "bonus_active": bool(r[6] and r[8] and datetime.fromisoformat(r[8].replace('Z', '+00:00')) > now)} for index, r in enumerate(rows)]
    cents = sum(r[2] for r in rows)
    result["total"] = cents / 100
    current_total = income = bonus_total = fixed_extra_total = Decimal(0)
    expired_bonus_total = Decimal(0)
    for account, row in zip(result["accounts"], rows):
        amount = Decimal(row[2]) / 100
        rate, enabled, personal, bonus = _current_account(account, result, today())
        account["current_amount"] = _bounded(personal)
        account["capitalization_active"] = enabled
        account["bonus_current_amount"] = _bounded(bonus) if account["bonus_active"] else 0
        account["working_amount"] = _bounded(personal + (bonus if account["bonus_active"] else 0))
        account["bonus_status"] = "active" if account["bonus_active"] else "expired" if account["bonus_amount"] else None
        account["bonus_rate_income"] = _bounded((bonus if account["bonus_active"] else 0) * rate)
        current_total += personal
        if account["bonus_active"]:
            bonus_total += bonus
        income += (personal + (bonus if account["bonus_active"] else 0)) * rate
        account["personal_amount"] = float(amount)
        account["personal_capitalization"] = enabled
        account["personal_income"] = _bounded(personal * rate)
        fixed_extra = Decimal(row[10] or 0) / 100
        fixed_extra_total += fixed_extra
        account["expected_income"] = _bounded((personal + (bonus if account["bonus_active"] else 0)) * rate + fixed_extra)
        account["daily_rate_percent"] = daily_rate_percent(rate * 100, result["period"])
        account["daily_income"] = _bounded(((personal + (bonus if account["bonus_active"] else 0)) * rate + fixed_extra) / period_days(result["period"]))
        if account["bonus_status"] == "expired":
            expired_bonus_total += Decimal(row[6] or 0) / 100
    result["calculation_limited"] = current_total > MAX_AMOUNT or current_total + bonus_total > MAX_AMOUNT or income > MAX_AMOUNT
    result["total"] = _bounded(cents and Decimal(cents) / 100 or Decimal(0))
    result["current_total"] = _bounded(current_total)
    if fixed_cents and not result["calculation_limited"]:
        income = Decimal(fixed_cents) / 100  # доход задан суммой за период, а не процентом
    income += fixed_extra_total  # доплаты аккаунтам идут сверх процента и сверх общей суммы проекта
    result["fixed_extra_total"] = _bounded(fixed_extra_total)
    result["expected_income"] = _bounded(income)
    result["daily_rate_percent"] = daily_rate_percent(result["rate_percent"], result["period"])
    result["daily_income"] = _bounded(income / period_days(result["period"]))
    result["personal_total"] = result["current_total"]
    result["bonus_total"] = _bounded(bonus_total)
    result["expired_bonus_total"] = _bounded(expired_bonus_total)
    result["working_total"] = _bounded(current_total + bonus_total)
    result["has_capitalization"] = result["current_total"] is not None and result["current_total"] != result["total"]
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
        income_mode = merged.get("income_mode", "percent")
        if income_mode not in ("percent", "fixed"):
            raise ValueError("Доходность задаётся процентом или фиксированной суммой")
        fixed_cents = numeric(merged.get("fixed_income"), MAX_AMOUNT, amount=True) if income_mode == "fixed" else None
        rate = 0.0 if fixed_cents else numeric(merged.get("rate_percent"), MAX_RATE)
        capitalization = merged.get("capitalization", False)
        business_days_only = merged.get("business_days_only", False)
        if type(capitalization) is not bool or type(business_days_only) is not bool:
            raise ValueError("Некорректный режим капитализации")
        if fixed_cents:
            capitalization = False  # фиксированная сумма начисляется без капитализации
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
                             optional_amount(row.get("bonus_amount")), valid_activation(row.get("bonus_activated_at")), valid_expiration(row.get("bonus_expires_at")), row.get("bonus_capitalization", False), optional_fixed(row.get("fixed_income"))))
            if row.get("capitalization") is not None and type(row["capitalization"]) is not bool:
                raise ValueError("Некорректный режим капитализации аккаунта")
            if type(row.get("bonus_capitalization", False)) is not bool:
                raise ValueError("Некорректный режим капитализации бонуса")
            if prepared[-1][6] is not None and not prepared[-1][8]:
                raise ValueError("Для бонуса укажите дату окончания")
            if prepared[-1][6] is None:
                prepared[-1] = (*prepared[-1][:6], None, None, None, False, prepared[-1][10])
        if sum(row[2] for row in prepared) > MAX_AMOUNT * 100:
            raise ValueError("Общая сумма проекта превышает допустимый предел")
        if fixed_cents:
            base = sum(row[2] + (row[6] or 0) for row in prepared)
            rate = fixed_cents / base * 100  # ставка, при которой доход за период равен заданной сумме
            if rate > MAX_RATE:
                raise ValueError("Фиксированная сумма слишком велика для вложений проекта")
            prepared = [(*row[:3], None, None, None, *row[6:]) for row in prepared]
        project_id = project_id or uuid.uuid4().hex
        if old:
            db.execute("UPDATE projects SET name=?,currency=?,rate_percent=?,period=?,multi=?,business_days_only=?,capitalization=?,capitalization_from=?,income_fixed_cents=? WHERE id=? AND owner_id=?",
                       (name, currency, rate, period, int(multi), int(business_days_only), int(capitalization), capitalization_from, fixed_cents, project_id, str(owner)))
            db.execute("DELETE FROM project_accounts WHERE project_id=?", (project_id,))
        else:
            db.execute("INSERT INTO projects (id,owner_id,name,currency,rate_percent,period,multi,business_days_only,capitalization,capitalization_from,income_fixed_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (project_id, str(owner), name, currency, rate, period, int(multi), int(business_days_only), int(capitalization), capitalization_from, fixed_cents))
        db.executemany("INSERT INTO project_accounts (id,project_id,name,amount_cents,position,rate_percent,capitalization,capitalization_from,bonus_cents,bonus_activated_at,bonus_expires_at,bonus_capitalization,fixed_income_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       [(aid, project_id, title, cents, i, rate, cap, start, bonus, activated or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if bonus else None, expires, int(bonus_cap), fixed) for i, (aid, title, cents, rate, cap, start, bonus, activated, expires, bonus_cap, fixed) in enumerate(prepared)])
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
                rows[index] = {**rows[index], **{k: v for k, v in data.items() if k in {"name", "amount", "rate_percent", "capitalization", "capitalization_from", "bonus_amount", "bonus_activated_at", "bonus_expires_at", "bonus_capitalization", "fixed_income"}}}
        else:
            if not project["multi"]:
                raise ValueError("Сначала включите «Несколько аккаунтов»")
            rows.append({"name": data.get("name", ""), "amount": data.get("amount"), "rate_percent": data.get("rate_percent"), "capitalization":data.get("capitalization"), "capitalization_from":data.get("capitalization_from", today().isoformat()), "bonus_amount":data.get("bonus_amount"), "bonus_activated_at":data.get("bonus_activated_at"), "bonus_expires_at":data.get("bonus_expires_at"), "bonus_capitalization":data.get("bonus_capitalization", False), "fixed_income":data.get("fixed_income")})
        return save(db, owner, {"accounts": rows}, project_id)


def reorder_account(db, owner, project_id, account_id, position):
    """Переносит аккаунт на позицию position (с 1), остальные сдвигаются."""
    if type(position) is not int:
        raise ValueError("Укажите номер позиции аккаунта")
    with db:
        rows = get(db, owner, project_id)["accounts"]
        index = next((i for i, account in enumerate(rows) if account["id"] == account_id), None)
        if index is None:
            raise LookupError("Аккаунт проекта не найден")
        if not 1 <= position <= len(rows):
            raise ValueError("Номер позиции вне списка аккаунтов")
        rows.insert(position - 1, rows.pop(index))
        db.executemany("UPDATE project_accounts SET position=? WHERE id=? AND project_id=?",
                       [(i, account["id"], project_id) for i, account in enumerate(rows)])
        return get(db, owner, project_id)
