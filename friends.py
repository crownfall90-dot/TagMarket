"""Друзья: общие вишлисты и общие траты.

Круг друзей — те, кого связывает приглашение: кто пригласил меня, кого
пригласил я и остальные приглашённые тем же человеком. Больше никого
Platformer не показывает.

Вишлист становится виден кругу, когда владелец включает «показать друзьям».
Друг может отметить желание «подарю» — остальные друзья видят, что оно
занято, а сам владелец не видит: сюрприз не портится.

Общие траты — кто за что платил и между кем делим. Из всех записей
считается, кто кому сколько должен; «вернул долг» — такая же запись.
"""
from datetime import datetime, timezone
import json
import uuid

import lists
import partner
from spend import CURRENCIES, _cents, _date, _text, today

MAX_SPLIT = 1000


def setup(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS wish_reservations (
            item_id TEXT PRIMARY KEY,
            by_uid TEXT NOT NULL,
            at TEXT NOT NULL
        );
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


# ── общие вишлисты ───────────────────────────────────────────────────────

def shared_ids(db, owner):
    return {r[0] for r in db.execute("SELECT id FROM wishlists WHERE owner_id=? AND shared=1", (str(owner),))}


def friend_wishlists(db, viewer, friend):
    """Открытые другом вишлисты — глазами viewer: с отметками «подарю»."""
    if not is_friend(db, viewer, friend):
        raise LookupError("Друг не найден")
    out = []
    for list_id in sorted(shared_ids(db, friend)):
        wl = lists.wishlist(db, friend, list_id)
        items = []
        for item in wl["items"]:
            if item["done"]:
                continue
            row = db.execute("SELECT by_uid FROM wish_reservations WHERE item_id=?", (item["id"],)).fetchone()
            items.append({**item, "reserved": bool(row), "mine": bool(row) and row[0] == str(viewer)})
        out.append({"id": wl["id"], "title": wl["title"], "emoji": wl["emoji"], "items": items})
    return out


def _wish_owner(db, item_id):
    row = db.execute("SELECT w.owner_id, w.shared, i.done FROM wish_items i JOIN wishlists w ON w.id=i.list_id WHERE i.id=?",
                     (item_id,)).fetchone()
    if row is None:
        raise LookupError("Желание не найдено")
    return row


def reserve(db, viewer, item_id, on=True):
    owner, shared, done = _wish_owner(db, item_id)
    if not shared or not is_friend(db, viewer, owner):
        raise LookupError("Желание не найдено")
    with db:
        row = db.execute("SELECT by_uid FROM wish_reservations WHERE item_id=?", (item_id,)).fetchone()
        if on:
            if done:
                raise ValueError("Это желание уже исполнено")
            if row and row[0] != str(viewer):
                raise ValueError("Это желание уже кто-то дарит")
            if not row:
                db.execute("INSERT INTO wish_reservations (item_id,by_uid,at) VALUES (?,?,?)", (item_id, str(viewer), _now()))
        elif row:
            if row[0] != str(viewer):
                raise ValueError("Снять отметку может только тот, кто её поставил")
            db.execute("DELETE FROM wish_reservations WHERE item_id=?", (item_id,))


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
        people.append({"id": f, "name": name(db, f), "balance": owed.get(f, {}),
                       "wishlists": friend_wishlists(db, viewer, f)})
    # бывшие друзья с незакрытым долгом тоже видны — иначе долг пропадает молча
    for f, bal in owed.items():
        if f not in friends and bal:
            people.append({"id": f, "name": name(db, f), "balance": bal, "wishlists": [], "former": True})
    return {"me": viewer, "friends": people, "split": [_split_row(db, r, viewer) for r in rows[:100]],
            "shared_lists": sorted(shared_ids(db, viewer)), "currencies": list(CURRENCIES)}
