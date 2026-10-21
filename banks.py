"""Банки и счета в «Общем балансе»: свои карты, счета, вклады и наличные.

Баланс счёта задаётся вручную или обновляется сам: банк присылает SMS или
пуш по каждой операции («Покупка 25,40 BYN, остаток 1 340,10 BYN»), а
автоматизация на телефоне пересылает этот текст сюда по личному ключу
синхронизации (тот же, что у шагов). Разбор — правилами, без внешних сервисов
и без доступа к самому банку: пароли от интернет-банка Станция не хранит.

Что не удалось привязать к счёту (новая карта, незнакомый формат), лежит во
«входящих» — пользователь подтверждает в один тап. Сумма в базе — целые
копейки; баланс может быть отрицательным (овердрафт, кредитка).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
import uuid

CURRENCIES = {"USD", "RUB", "BYN"}
KINDS = {"card": "Карта", "current": "Счёт", "deposit": "Вклад", "savings": "Накопительный", "cash": "Наличные"}
MAX_CENTS = 10**14
MAX_ACCOUNTS = 100
INBOX_LIMIT = 30
OPS_LIMIT = 200
MESSAGE_LIMIT = 600


def setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS bank_accounts (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            bank TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT 'card',
            currency TEXT NOT NULL,
            balance_cents INTEGER NOT NULL DEFAULT 0,
            last4 TEXT,
            counted INTEGER NOT NULL DEFAULT 1,
            position INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual'
        );
        CREATE INDEX IF NOT EXISTS bank_accounts_owner ON bank_accounts(owner_id, position);
        CREATE TABLE IF NOT EXISTS bank_ops (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES bank_accounts(id) ON DELETE CASCADE,
            at TEXT NOT NULL,
            amount_cents INTEGER,
            balance_cents INTEGER,
            note TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'manual'
        );
        CREATE INDEX IF NOT EXISTS bank_ops_account ON bank_ops(account_id, at);
        CREATE TABLE IF NOT EXISTS bank_inbox (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            received_at TEXT NOT NULL,
            text TEXT NOT NULL,
            parsed TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS bank_inbox_owner ON bank_inbox(owner_id, received_at);
    """)
    db.execute("PRAGMA foreign_keys=ON")
    db.commit()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cents(value, label="Сумма", *, allow_negative=True):
    """Число → копейки с проверкой; принимает int/float и строку «1 340,10»."""
    if isinstance(value, bool):
        raise ValueError(f"{label}: нужно число")
    if isinstance(value, str):
        value = amount_from_text(value)
    if not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{label}: нужно число")
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{label}: нужно число") from None
    if not dec.is_finite() or dec * 100 != (dec * 100).to_integral_value():
        raise ValueError(f"{label}: не больше двух знаков после запятой")
    out = int(dec * 100)
    if abs(out) > MAX_CENTS or (out < 0 and not allow_negative):
        raise ValueError(f"{label}: вне допустимого диапазона")
    return out


def text_field(value, limit, label, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str) or "\x00" in value or len(value.strip()) > limit:
        raise ValueError(f"{label}: до {limit} символов")
    if required and not value.strip():
        raise ValueError(f"Укажите: {label.lower()}")
    return value.strip()


def last4_field(value):
    if value in (None, ""):
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 4:
        raise ValueError("Последние 4 цифры карты или счёта")
    return digits[-4:]


# ── разбор сообщений банка ──────────────────────────────────────────────

CUR_WORDS = (("BYN", ("byn", "byr", "br", "руб.бел", "бел.руб", "белорусских")),
             ("RUB", ("rub", "rur", "₽", "руб", "р.")),
             ("USD", ("usd", "$", "дол")),)
MINUS_WORDS = ("покупка", "оплата", "списан", "снятие", "расход", "платеж", "платёж", "перевод на", "purchase", "payment",
               "withdraw", "debit", "комиссия", "отправлен", "pokupka", "oplata", "spisanie", "snyatie", "platezh")
PLUS_WORDS = ("зачисл", "пополнен", "поступлен", "возврат", "получен", "начислен", "credit", "deposit", "refund", "cashback",
              "кэшбэк", "zachislenie", "popolnenie", "postuplenie", "vozvrat")
BALANCE_WORDS = r"(?:остаток|остатки|баланс|доступно|доступный остаток|balance|available|avail\.?|ostatok|dostupno)"
NUMBER = r"(-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|-?\d[\d\s  ]*(?:[.,]\d{1,2})?)"
SYMBOL = r"(?:\$|€|₽)"
CURRENCY = r"(byn|byr|br\b|rub|rur|usd|eur|₽|\$|€|руб\.?|р\.|бел\.?\s*руб\.?)"
BALANCE_RE = re.compile(rf"{BALANCE_WORDS}\s*(?:по\s+карте|на\s+счете|на\s+счёте|карты|счета)?\s*[:=]?\s*({SYMBOL})?\s*{NUMBER}\s*{CURRENCY}?", re.I)
AMOUNT_RE = re.compile(rf"({SYMBOL})?\s*{NUMBER}\s*{CURRENCY}?", re.I)
STAR_RE = re.compile(r"(?:\*+|[xх]{2,})\s*(\d{4})\b", re.I)
WORD_LAST4_RE = re.compile(r"\b(?:карт[аыуе]?|card|karta|сч[её]т[аё]?|acc\w*)\s*№?\s*(\d{4})\b(?!\s*[.,]?\d)(?!\s*(?:byn|byr|br\b|rub|rur|usd|eur|₽|\$|€|руб|р\.))", re.I)


def amount_from_text(raw):
    """«1 340,10» / «1,340.10» / «−25.4» → Decimal; ValueError, если числа нет."""
    cleaned = re.sub(r"[\s  ]", "", str(raw)).replace("−", "-")
    match = re.search(r"-?\d+(?:[.,]\d+)*", cleaned)
    if not match:
        raise ValueError("нужно число")
    token = match.group()
    if "," in token and "." in token:        # «1,340.10» или «1.340,10»: последний знак — десятичный
        dec = "," if token.rfind(",") > token.rfind(".") else "."
        token = token.replace("," if dec == "." else ".", "").replace(dec, ".")
    elif "," in token or token.count(".") > 1:
        parts = re.split(r"[.,]", token)
        token = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) <= 2 else "".join(parts)
    return Decimal(token)


def _currency(code):
    low = (code or "").lower().replace(" ", "")
    for name, words in CUR_WORDS:
        if any(low == w.replace(" ", "") or low.startswith(w) for w in words):
            return name
    return "EUR" if low in ("eur", "€") else None


def parse_message(text):
    """Что можно понять из SMS/пуша: last4, currency, balance, amount (со знаком), op ('in'/'out'/None).

    Ничего не придумывает: чего нет в тексте — None. Баланс — число после слов
    «остаток», «баланс», «доступно»; сумма операции — первое другое число с валютой.
    """
    raw = str(text or "")[:MESSAGE_LIMIT]
    low = raw.lower()
    result = {"last4": None, "currency": None, "balance": None, "amount": None, "op": None}
    match = STAR_RE.search(raw) or WORD_LAST4_RE.search(raw)
    if match:
        result["last4"] = match.group(1)
    span = None
    bal = BALANCE_RE.search(raw)
    if bal:
        try:
            result["balance"] = amount_from_text(bal.group(2))
            span = bal.span()
            result["currency"] = _currency(bal.group(1) or bal.group(3))
        except (ValueError, InvalidOperation):
            result["balance"] = None
    minus = any(w in low for w in MINUS_WORDS)
    plus = any(w in low for w in PLUS_WORDS)
    result["op"] = "out" if minus and not plus else "in" if plus and not minus else None
    star_spans = [m.span() for m in STAR_RE.finditer(raw)] + [m.span() for m in WORD_LAST4_RE.finditer(raw)]
    for m in AMOUNT_RE.finditer(raw):
        pre, num, post = m.group(1), m.group(2), m.group(3)
        if not (pre or post):
            continue                        # число без валюты — не сумма (номер карты, код…)
        if span and m.start() >= span[0] and m.end() <= span[1]:
            continue                        # это сам остаток
        if any(a <= m.start() < b for a, b in star_spans):
            continue                        # «*1234» — не сумма
        try:
            value = amount_from_text(num)
        except (ValueError, InvalidOperation):
            continue
        if value:
            result["amount"] = abs(value)
            result["currency"] = result["currency"] or _currency(pre or post)
            break
    if result["amount"] is not None and result["op"] == "out":
        result["amount"] = -result["amount"]
    elif result["amount"] is not None and result["op"] is None:
        result["amount"] = None             # без понятного направления сумму не применяем
    return result


def _parsed_json(parsed):
    import json
    return json.dumps({k: (str(v) if isinstance(v, Decimal) else v) for k, v in parsed.items()}, ensure_ascii=False)


# ── счета ────────────────────────────────────────────────────────────────

def _account(r):
    return {"id": r[0], "bank": r[1], "title": r[2], "kind": r[3], "kind_label": KINDS.get(r[3], r[3]),
            "currency": r[4], "balance": r[5] / 100, "last4": r[6], "counted": bool(r[7]),
            "updated_at": r[8], "source": r[9]}


COLUMNS = "id,bank,title,kind,currency,balance_cents,last4,counted,updated_at,source"


def account(db, owner, account_id):
    row = db.execute(f"SELECT {COLUMNS} FROM bank_accounts WHERE id=? AND owner_id=?", (account_id, str(owner))).fetchone()
    if row is None:
        raise LookupError("Счёт не найден")
    return _account(row)


def accounts(db, owner):
    return [_account(r) for r in db.execute(
        f"SELECT {COLUMNS} FROM bank_accounts WHERE owner_id=? ORDER BY position, updated_at", (str(owner),))]


def totals(db, owner):
    """Суммы по валютам счетов, входящих в общий баланс."""
    out = {}
    for a in accounts(db, owner):
        if a["counted"]:
            out[a["currency"]] = round(out.get(a["currency"], 0) + a["balance"], 2)
    return out


def save_account(db, owner, data, account_id=None):
    with db:
        old = account(db, owner, account_id) if account_id else {
            "bank": "", "title": "", "kind": "card", "currency": "USD", "balance": 0, "last4": None, "counted": True}
        allowed = {"bank", "title", "kind", "currency", "balance", "last4", "counted"}
        if set(data) - allowed:
            raise ValueError("Неизвестное поле: " + ", ".join(sorted(set(data) - allowed)))
        merged = {**old, **data}
        bank = text_field(merged["bank"], 48, "Банк", required=True)
        title = text_field(merged.get("title"), 64, "Название")
        kind = merged.get("kind")
        currency = merged.get("currency")
        if kind not in KINDS:
            raise ValueError("Выберите тип счёта")
        if currency not in CURRENCIES:
            raise ValueError("Валюта: USD, RUB или BYN")
        if account_id and currency != old["currency"]:
            raise ValueError("Валюту счёта менять нельзя — создайте отдельный счёт")
        balance = cents(merged.get("balance", 0), "Баланс")
        last4 = last4_field(merged.get("last4"))
        counted = merged.get("counted", True)
        if type(counted) is not bool:
            raise ValueError("Некорректная отметка «в общий баланс»")
        stamp = now()
        if account_id:
            changed = balance != round(old["balance"] * 100)
            db.execute("UPDATE bank_accounts SET bank=?,title=?,kind=?,balance_cents=?,last4=?,counted=?,updated_at=?,source=? WHERE id=? AND owner_id=?",
                       (bank, title, kind, balance, last4, int(counted), stamp if changed else _stamp(db, account_id),
                        "manual" if changed else _source(db, account_id), account_id, str(owner)))
            if changed:
                _op(db, account_id, balance - round(old["balance"] * 100), balance, "Исправлено вручную", "manual")
        else:
            if db.execute("SELECT COUNT(*) FROM bank_accounts WHERE owner_id=?", (str(owner),)).fetchone()[0] >= MAX_ACCOUNTS:
                raise ValueError(f"Не больше {MAX_ACCOUNTS} счетов")
            account_id = uuid.uuid4().hex
            position = db.execute("SELECT COALESCE(MAX(position)+1,0) FROM bank_accounts WHERE owner_id=?", (str(owner),)).fetchone()[0]
            db.execute("INSERT INTO bank_accounts (id,owner_id,bank,title,kind,currency,balance_cents,last4,counted,position,updated_at,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,'manual')",
                       (account_id, str(owner), bank, title, kind, currency, balance, last4, int(counted), position, stamp))
            _op(db, account_id, balance, balance, "Начальный баланс", "manual")
        return account(db, owner, account_id)


def _stamp(db, account_id):
    return db.execute("SELECT updated_at FROM bank_accounts WHERE id=?", (account_id,)).fetchone()[0]


def _source(db, account_id):
    return db.execute("SELECT source FROM bank_accounts WHERE id=?", (account_id,)).fetchone()[0]


def _op(db, account_id, amount_cents, balance_cents, note, source, at=None):
    db.execute("INSERT INTO bank_ops (id,account_id,at,amount_cents,balance_cents,note,source) VALUES (?,?,?,?,?,?,?)",
               (uuid.uuid4().hex, account_id, at or now(), amount_cents, balance_cents, note[:200], source))
    db.execute("DELETE FROM bank_ops WHERE account_id=? AND id NOT IN (SELECT id FROM bank_ops WHERE account_id=? ORDER BY at DESC LIMIT ?)",
               (account_id, account_id, OPS_LIMIT))


def delete_account(db, owner, account_id):
    with db:
        account(db, owner, account_id)
        db.execute("DELETE FROM bank_ops WHERE account_id=?", (account_id,))
        db.execute("DELETE FROM bank_accounts WHERE id=? AND owner_id=?", (account_id, str(owner)))


def operations(db, owner, account_id, limit=50):
    account(db, owner, account_id)
    rows = db.execute("SELECT id,at,amount_cents,balance_cents,note,source FROM bank_ops WHERE account_id=? ORDER BY at DESC LIMIT ?",
                      (account_id, max(1, min(int(limit), OPS_LIMIT)))).fetchall()
    return [{"id": r[0], "at": r[1], "amount": None if r[2] is None else r[2] / 100,
             "balance": None if r[3] is None else r[3] / 100, "note": r[4], "source": r[5]} for r in rows]


# ── входящие сообщения ───────────────────────────────────────────────────

def _apply(db, acc, parsed, message, source="sms"):
    """Обновляет счёт по разобранному сообщению; возвращает, что сделано."""
    balance = parsed.get("balance")
    amount = parsed.get("amount")
    if balance is not None:
        new = cents(balance, "Остаток")
        delta = round(amount * 100) if amount is not None else new - round(acc["balance"] * 100)
    elif amount is not None:
        delta = cents(amount, "Сумма")
        new = round(acc["balance"] * 100) + delta
    else:
        return {"applied": False}
    if abs(new) > MAX_CENTS:
        raise ValueError("Баланс вне допустимого диапазона")
    db.execute("UPDATE bank_accounts SET balance_cents=?,updated_at=?,source=? WHERE id=?", (new, now(), source, acc["id"]))
    _op(db, acc["id"], delta, new, message, source)
    return {"applied": True, "balance": new / 100, "amount": delta / 100}


def _match(db, owner, parsed):
    """Единственный подходящий счёт: по последним цифрам (и валюте, если известна)."""
    candidates = accounts(db, owner)
    if parsed.get("last4"):
        candidates = [a for a in candidates if a["last4"] == parsed["last4"]]
    else:
        return None
    if parsed.get("currency"):
        narrowed = [a for a in candidates if a["currency"] == parsed["currency"]]
        candidates = narrowed or candidates
    return candidates[0] if len(candidates) == 1 else None


def ingest(db, owner, message):
    """SMS или пуш от банка: обновить счёт или положить во входящие на подтверждение."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Пустое сообщение")
    message = message.strip()[:MESSAGE_LIMIT]
    parsed = parse_message(message)
    if parsed["balance"] is None and parsed["amount"] is None:
        return {"ok": True, "status": "ignored", "reason": "В сообщении нет суммы или остатка"}
    with db:
        acc = _match(db, owner, parsed)
        if acc is not None:
            if parsed["currency"] and parsed["currency"] != acc["currency"] and parsed["currency"] in CURRENCIES:
                raise ValueError("Валюта сообщения не совпадает со счётом")
            done = _apply(db, acc, parsed, message)
            if done["applied"]:
                return {"ok": True, "status": "applied", "account": acc["id"], **done}
        inbox_id = uuid.uuid4().hex
        db.execute("INSERT INTO bank_inbox (id,owner_id,received_at,text,parsed) VALUES (?,?,?,?,?)",
                   (inbox_id, str(owner), now(), message, _parsed_json(parsed)))
        db.execute("DELETE FROM bank_inbox WHERE owner_id=? AND id NOT IN (SELECT id FROM bank_inbox WHERE owner_id=? ORDER BY received_at DESC LIMIT ?)",
                   (str(owner), str(owner), INBOX_LIMIT))
    return {"ok": True, "status": "inbox", "inbox": inbox_id}


def inbox(db, owner):
    import json
    rows = db.execute("SELECT id,received_at,text,parsed FROM bank_inbox WHERE owner_id=? ORDER BY received_at DESC", (str(owner),)).fetchall()
    return [{"id": r[0], "received_at": r[1], "text": r[2], "parsed": json.loads(r[3])} for r in rows]


def resolve_inbox(db, owner, item_id, data):
    """Подтвердить сообщение из входящих: привязать к счёту или создать счёт под него."""
    import json
    with db:
        row = db.execute("SELECT text,parsed FROM bank_inbox WHERE id=? AND owner_id=?", (item_id, str(owner))).fetchone()
        if row is None:
            raise LookupError("Сообщение не найдено")
        message, parsed = row[0], json.loads(row[1])
        for key in ("amount", "balance"):
            if parsed.get(key) is not None:
                parsed[key] = Decimal(parsed[key])
        if data.get("account_id"):
            acc = account(db, owner, data["account_id"])
            if parsed.get("currency") and parsed["currency"] in CURRENCIES and parsed["currency"] != acc["currency"]:
                raise ValueError("Валюта сообщения не совпадает со счётом")
            # запоминаем цифры карты — следующие сообщения привяжутся сами
            if parsed.get("last4") and not acc["last4"]:
                db.execute("UPDATE bank_accounts SET last4=? WHERE id=?", (parsed["last4"], acc["id"]))
            done = _apply(db, acc, parsed, message, source="sms")
            if not done["applied"]:
                raise ValueError("В сообщении нет суммы или остатка")
        elif isinstance(data.get("create"), dict):
            body = {"balance": float(parsed["balance"]) if parsed.get("balance") is not None else 0,
                    "last4": parsed.get("last4"), "currency": parsed.get("currency") or "BYN", **data["create"]}
            created = save_account(db, owner, body)
            acc = created
        else:
            raise ValueError("Выберите счёт или создайте новый")
        db.execute("DELETE FROM bank_inbox WHERE id=?", (item_id,))
        return account(db, owner, acc["id"])


def dismiss_inbox(db, owner, item_id):
    with db:
        if not db.execute("SELECT 1 FROM bank_inbox WHERE id=? AND owner_id=?", (item_id, str(owner))).fetchone():
            raise LookupError("Сообщение не найдено")
        db.execute("DELETE FROM bank_inbox WHERE id=?", (item_id,))


def overview(db, owner):
    return {"accounts": accounts(db, owner), "totals": totals(db, owner), "inbox": inbox(db, owner),
            "kinds": KINDS, "currencies": sorted(CURRENCIES)}


def stale_days(acc, today=None):
    """Сколько дней баланс не обновлялся (для подсказки «обновите»)."""
    when = datetime.fromisoformat(acc["updated_at"])
    return ((today or datetime.now(timezone.utc)) - when) // timedelta(days=1)
