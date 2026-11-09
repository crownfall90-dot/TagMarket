"""Друзья: общие траты.

Круг друзей — те, кого связывает приглашение: кто пригласил меня, кого
пригласил я и остальные приглашённые тем же человеком. Больше никого
Platformer не показывает.

Общие траты — кто за что платил и между кем делим. Из всех записей
считается, кто кому сколько должен; «вернул долг» — такая же запись.

Публичный профиль — человек сам решает, видят ли друзья его профиль и какие
разделы в нём открыты. По умолчанию профиль закрыт и всё в нём скрыто.
"""
from datetime import datetime, timezone
import json
import uuid

import goals
import partner
import projects
import spend
from spend import CURRENCIES, _cents, _date, _text, today

MAX_SPLIT = 1000


def setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS split_items (
            id TEXT PRIMARY KEY,
            created_by TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            currency TEXT NOT NULL,
            payer TEXT NOT NULL,
            members TEXT NOT NULL,
            day TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS split_day ON split_items(day);
    """)
    db.commit()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def name(db, uid):
    uid = str(uid)
    return (partner.kv_get(db, f"user_name:{uid}") or partner.kv_get(db, f"guest_name:{uid}") or "Друг").strip()


def _guests(db, host):
    out = []
    for key in partner.kv_keys(db, "guest:%"):
        uid = key.split(":", 1)[1]
        if partner.kv_get(db, key) == "1" and str(partner.kv_get(db, f"guest_by:{uid}")) == str(host):
            out.append(uid)
    return out


def circle(db, uid) -> list[str]:
    """Друзья uid: пригласивший, приглашённые им и приглашённые мной; без самого uid."""
    uid = str(uid)
    people = set(_guests(db, uid))
    host = partner.kv_get(db, f"guest_by:{uid}")
    if host and partner.kv_get(db, f"guest:{uid}") == "1":
        people.add(str(host))
        people.update(_guests(db, host))
    people.discard(uid)
    return sorted(people)


def is_friend(db, uid, other) -> bool:
    return str(other) in circle(db, uid)


# ── общие траты ──────────────────────────────────────────────────────────

def _split_row(db, r, viewer):
    members = json.loads(r[7])
    return {"id": r[0], "created_by": r[1], "kind": r[2], "title": r[3], "amount": r[4] / 100, "currency": r[5],
            "payer": r[6], "payer_name": "Вы" if r[6] == str(viewer) else name(db, r[6]),
            "members": [{"id": m, "name": "Вы" if m == str(viewer) else name(db, m)} for m in members],
            "share": round(r[4] / len(members) / 100, 2) if r[2] == "expense" else r[4] / 100,
            "day": r[8], "mine": r[1] == str(viewer)}


def _visible(db, viewer):
    viewer = str(viewer)
    rows = db.execute("SELECT id,created_by,kind,title,amount_cents,currency,payer,members,day,created_at FROM split_items "
                      "ORDER BY day DESC, created_at DESC").fetchall()
    return [r for r in rows if r[6] == viewer or viewer in json.loads(r[7])]


def balances(rows, viewer):
    """{друг: {валюта: сумма}}: плюс — друг должен мне, минус — я ему."""
    viewer = str(viewer)
    out = {}
    for r in rows:
        members, payer, cents, cur = json.loads(r[7]), r[6], r[4], r[5]
        share = cents / len(members)
        for m in members:
            if m == payer:
                continue
            if payer == viewer:
                other, sign = m, 1
            elif m == viewer:
                other, sign = payer, -1
            else:
                continue
            bucket = out.setdefault(other, {})
            bucket[cur] = bucket.get(cur, 0) + sign * share
    return {who: {cur: round(v / 100, 2) for cur, v in d.items() if abs(v) >= 0.5} for who, d in out.items()}


def add_split(db, viewer, data):
    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-объект")
    viewer = str(viewer)
    friends = set(circle(db, viewer))
    kind = data.get("kind", "expense")
    if kind not in ("expense", "settle"):
        raise ValueError("Тип записи: трата или возврат долга")
    cents = _cents(data.get("amount"))
    currency = data.get("currency")
    if currency not in CURRENCIES:
        raise ValueError("Валюта: " + ", ".join(CURRENCIES))
    day = _date(data.get("day") or today().isoformat())
    if kind == "settle":
        # «вернул долг»: from отдал деньги to — запись «from платил, делим на to»
        src, dst = str(data.get("from") or viewer), str(data.get("to") or "")
        if viewer not in (src, dst) or src == dst or ({src, dst} - {viewer}) - friends:
            raise ValueError("Возврат — между вами и другом")
        payer, members, title = src, [dst], "Возврат долга"
    else:
        title = _text(data.get("title"), 80, "За что", required=True)
        payer = str(data.get("payer") or viewer)
        raw = data.get("members")
        if not isinstance(raw, list) or not raw or len(raw) > 30:
            raise ValueError("Выберите, между кем делим")
        members = sorted({str(m) for m in raw})
        allowed = friends | {viewer}
        if payer not in allowed or set(members) - allowed:
            raise ValueError("Делить можно только с друзьями")
        if viewer not in members and payer != viewer:
            raise ValueError("Запись должна касаться вас")
        if members == [payer]:
            raise ValueError("Добавьте хотя бы одного друга")
    with db:
        if db.execute("SELECT COUNT(*) FROM split_items WHERE created_by=?", (viewer,)).fetchone()[0] >= MAX_SPLIT:
            raise ValueError(f"Не больше {MAX_SPLIT} записей")
        item_id = uuid.uuid4().hex
        db.execute("INSERT INTO split_items (id,created_by,kind,title,amount_cents,currency,payer,members,day,created_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (item_id, viewer, kind, title, cents, currency, payer, json.dumps(members), day, _now()))
    return item_id


def participants(db, item_id):
    """Кто затронут записью: платил и между кем делили."""
    row = db.execute("SELECT payer, members FROM split_items WHERE id=?", (item_id,)).fetchone()
    return sorted({row[0], *json.loads(row[1])}) if row else []


def delete_split(db, viewer, item_id):
    with db:
        row = db.execute("SELECT created_by FROM split_items WHERE id=?", (item_id,)).fetchone()
        if row is None or row[0] != str(viewer):
            raise LookupError("Запись не найдена")
        db.execute("DELETE FROM split_items WHERE id=?", (item_id,))


def overview(db, viewer):
    viewer = str(viewer)
    friends = circle(db, viewer)
    rows = _visible(db, viewer)
    owed = balances(rows, viewer)
    people = []
    for f in friends:
        people.append({"id": f, "name": name(db, f), "balance": owed.get(f, {})})
    # бывшие друзья с незакрытым долгом тоже видны — иначе долг пропадает молча
    for f, bal in owed.items():
        if f not in friends and bal:
            people.append({"id": f, "name": name(db, f), "balance": bal, "former": True})
    for person in people:
        person["public"] = bool(not person.get("former") and profile(db, person["id"])["public"])
    return {"me": viewer, "friends": people, "split": [_split_row(db, r, viewer) for r in rows[:100]],
            "currencies": list(CURRENCIES)}


# ── публичный профиль ────────────────────────────────────────────────────

PROFILE_SECTIONS = {
    "projects": ("Проекты", "Названия и суммы проектов, которые входят в ваш баланс"),
    "goals": ("Цели накоплений", "На что копите и сколько уже отложено"),
    "spend": ("Траты", "Регулярные траты в месяц и расходы этого месяца"),
}
ABOUT_LIMIT = 140


def _profile_raw(db, uid):
    try:
        data = json.loads(partner.kv_get(db, f"profile:{uid}") or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def profile(db, uid):
    """Настройки публичного профиля пользователя: открыт ли он и какие разделы видны друзьям."""
    raw = _profile_raw(db, uid)
    opened = raw.get("sections") if isinstance(raw.get("sections"), dict) else {}
    return {"public": raw.get("public") is True, "about": str(raw.get("about") or "")[:ABOUT_LIMIT],
            "sections": {key: opened.get(key) is True for key in PROFILE_SECTIONS},
            "available": [{"id": key, "label": label, "note": note} for key, (label, note) in PROFILE_SECTIONS.items()]}


def save_profile(db, uid, data):
    """Частичное обновление: public, about, sections {раздел: bool}. Лишнего не принимаем."""
    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-объект")
    current = profile(db, uid)
    if "public" in data:
        if type(data["public"]) is not bool:
            raise ValueError("Профиль открыт или закрыт")
        current["public"] = data["public"]
    if "about" in data:
        about = data["about"]
        if about is not None and not isinstance(about, str):
            raise ValueError("Описание — текст")
        about = " ".join((about or "").split())
        if len(about) > ABOUT_LIMIT:
            raise ValueError(f"Описание: не длиннее {ABOUT_LIMIT} символов")
        current["about"] = about
    if "sections" in data:
        sections = data["sections"]
        if not isinstance(sections, dict) or set(sections) - set(PROFILE_SECTIONS)                 or any(type(v) is not bool for v in sections.values()):
            raise ValueError("Разделы профиля: " + ", ".join(PROFILE_SECTIONS))
        current["sections"].update(sections)
    partner.kv_set(db, f"profile:{uid}", json.dumps(
        {"public": current["public"], "about": current["about"], "sections": current["sections"]}, ensure_ascii=False))
    return profile(db, uid)


def public_profile(db, viewer, friend):
    """Профиль друга глазами viewer. Только друзья, только если профиль открыт,
    и только те разделы, которые друг разрешил."""
    friend = str(friend)
    if not is_friend(db, viewer, friend):
        raise LookupError("Друг не найден")
    prof = profile(db, friend)
    if not prof["public"]:
        raise PermissionError("Профиль закрыт")
    out = {"id": friend, "name": name(db, friend), "about": prof["about"], "sections": {}, "shown": []}
    for key in PROFILE_SECTIONS:
        if not prof["sections"][key]:
            continue
        out["shown"].append(key)
        if key == "projects":
            # приостановленные и скрытые из баланса проекты в профиль не попадают
            out["sections"][key] = [{"name": p["name"], "currency": p["currency"],
                                     "amount": p["current_total"], "rate_percent": p["rate_percent"], "period": p["period"]}
                                    for p in projects.list_for(db, friend) if not p["paused"] and not p["hidden"]]
        elif key == "goals":
            out["sections"][key] = [{"title": g["title"], "emoji": g["emoji"], "saved": g["saved"], "target": g["target"],
                                     "currency": g["currency"], "progress": g["progress"], "done": g["done"]}
                                    for g in goals.overview(db, friend)["items"]]
        elif key == "spend":
            data = spend.overview(db, friend)
            out["sections"][key] = {"monthly": data["monthly"], "this_month": data["this_month"]}
    return out
