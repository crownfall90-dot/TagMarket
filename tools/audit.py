"""Сквозная проверка данных и расчётов на боевом сервере.

selfcheck.py проверяет логику на выдуманных числах, а этот скрипт — реальные:
сходятся ли экраны между собой, цела ли база, живы ли связи. Запускать после
изменений в расчётах и при подозрении, что цифры разъехались.

Запуск на сервере:  venv/bin/python3 audit.py
"""

import os
import sys

# запускаемся из tools/, а модули лежат в корне проекта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from datetime import datetime, timedelta

import accounts
import bot
import store
import trades

BAD = []


def check(ok: bool, what: str, detail: str = "") -> None:
    print(f"{'✔' if ok else '✘'} {what}{'  — ' + detail if detail else ''}")
    if not ok:
        BAD.append(f"{what}: {detail}")


def money_close(a: float, b: float, eps: float = 0.02) -> bool:
    return abs(a - b) < eps


db = store.open_db()
now = trades.clock()
month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

print("═══ ЦЕЛОСТНОСТЬ БАЗЫ ═══")
dupes = db.execute("SELECT login, ticket, COUNT(*) c FROM deals "
                   "GROUP BY login, ticket HAVING c > 1").fetchall()
check(not dupes, "сделки не задваиваются", f"дублей: {len(dupes)}")

early = db.execute("SELECT COUNT(*) FROM deals WHERE time < ?",
                   (trades.REPORT_FROM.isoformat(),)).fetchone()[0]
check(True, "сделок раньше отсечки в базе", f"{early} (в отчёты не идут)")

blank = db.execute("SELECT COUNT(*) FROM deals WHERE time IS NULL OR net IS NULL").fetchone()[0]
check(not blank, "у сделок заполнены время и результат", f"пустых: {blank}")

print("\n═══ СВЯЗЬ С АГЕНТОМ ═══")
# по логину, а не по записи: один счёт бывает роздан гостям, и проверять его
# столько раз, сколько копий, незачем
seen_logins = set()
for acc in accounts.load():
    if int(acc["login"]) in seen_logins:
        continue
    seen_logins.add(int(acc["login"]))
    st = store.get_state(db, acc["login"])
    gap = ((store.utcnow() - datetime.fromisoformat(st["synced"])).total_seconds()
           if st and st.get("synced") else None)
    check(gap is not None and gap < 600, f"{acc['name'][:28]} на связи",
          f"{gap:.0f} сек назад" if gap is not None else "данных нет")

print("\n═══ РАСЧЁТЫ ПО СЧЕТАМ ═══")
for acc in accounts.load():
    trades.use(acc)
    name = acc["name"][:26]
    rows = trades.fetch(datetime(2000, 1, 1), now)

    # 1. заработано = сделки в базе + свёрнутые месяцы
    live = trades.summary(rows)["total"]
    archived = trades.archived_before_now()[0]
    earned = trades.net_of_fee(trades.mine(live + archived))

    # 2. то же самое, собранное помесячно — должно совпасть до цента
    by_month = sum(trades.net_of_fee(trades.mine((m["gross"] or 0) + (m["platform"] or 0)))
                   for m in trades.monthly(limit=1000))
    check(money_close(earned, by_month), f"{name}: сумма месяцев = заработано",
          f"{earned:+.2f} против {by_month:+.2f}")

    # 3. число сделок сходится с помесячным
    live_count = trades.summary(rows)["count"]
    month_count = sum(m["trades"] or 0 for m in trades.monthly(limit=1000))
    check(live_count + trades.archived_before_now()[1] == month_count,
          f"{name}: число сделок сходится",
          f"{live_count + trades.archived_before_now()[1]} против {month_count}")

    # 4. капитал положительный и восстанавливается назад во времени
    cap = trades.capital()
    was = trades.capital_at(month_start, rows)
    check(cap > 0 and was > 0, f"{name}: капитал восстановим",
          f"1-е число {was:.2f} → сейчас {cap:.2f}")

    # 5. доходность за всё время = произведение месяцев
    compound = 1.0
    for m in trades.monthly(limit=1000):
        if m.get("_live"):
            continue
        if m.get("growth") is not None:
            compound *= 1 + m["growth"] / 100
    compound *= 1 + trades.growth_pct(rows, rows) / 100
    check(money_close((compound - 1) * 100, trades.growth_all(), 0.01),
          f"{name}: доходность = произведение месяцев",
          f"{(compound - 1) * 100:+.3f}% против {trades.growth_all():+.3f}%")

    # 6. у свёрнутых месяцев сохранена доходность — иначе история потеряна
    lost = [m["month"] for m in trades.monthly(limit=1000)
            if not m.get("_live") and m.get("growth") is None]
    check(not lost, f"{name}: у свёрнутых месяцев есть доходность", f"без неё: {lost}")

print("\n═══ ЭКРАНЫ СХОДЯТСЯ МЕЖДУ СОБОЙ ═══")
for owner in {a["owner"] for a in accounts.load()}:
    mine_accs = accounts.load(owner)
    text, _ = bot.dashboard(owner)
    plain = re.sub("<[^>]+>", "", text)

    # сумма капиталов из дашборда против суммы по счетам
    total = 0.0
    for acc in mine_accs:
        t = bot.account_totals(acc)
        if t:
            total += t["now"]
    # числа печатаются с узким неразрывным пробелом между тысячами — убираем его
    shown = [float(x.replace(" ", "").replace(" ", ""))
             for x in re.findall(r"💎 ([\d  ]+\.\d{2})", plain)]
    check(shown and money_close(max(shown), total, 0.05),
          f"владелец {owner}: капитал в дашборде = сумме счетов",
          f"{max(shown) if shown else 0:.2f} против {total:.2f}")

    # процент за месяц у счетов одной стратегии должен совпадать
    same = {}
    for acc in mine_accs:
        if not acc.get("strategy"):
            continue        # без названия стратегии сравнивать не с чем
        trades.use(acc)
        # На счёте в 10$ сделки бывают по 0.07$, а MT5 округляет профит до
        # копеек — округление там весит около процента. Сравнивать такой счёт
        # с крупным бессмысленно: разойдутся из-за данных, а не из-за расчёта
        if trades.capital() < 100:
            continue
        trades.use(acc)
        rows = trades.fetch(month_start, now + timedelta(days=1))
        if any(r["is_closing"] for r in rows):
            same.setdefault(acc["strategy"], []).append(
                trades.growth_pct(rows, trades.fetch(datetime(2000, 1, 1), now)))
    for strategy, values in same.items():
        if len(values) > 1:
            check(max(values) - min(values) < 0.5,
                  f"стратегия {strategy}: процент одинаков на всех счетах",
                  f"{[f'{v:.3f}%' for v in values]}")

print("\n═══ НАСТРОЙКИ И ССЫЛКИ ═══")
import partner

pdb = partner.open_db()
for key in partner.kv_keys(pdb, "invite:%"):
    token = key.split(":", 1)[1]
    inv = bot.invite_get(pdb, token, active_only=False)
    if not inv:
        continue
    known = {int(a["login"]) for a in accounts.load(inv["owner"])}
    missing = [x for x in bot.invite_logins(inv) if x not in known]
    check(not missing, f"ссылка {token[:8]}: счета существуют", f"нет: {missing}")

for key in partner.kv_keys(pdb, "guest:%"):
    uid = key.split(":", 1)[1]
    if partner.kv_get(pdb, key) == "1":
        check(bool(partner.kv_get(pdb, f"guest_by:{uid}")),
              f"гость {uid}: известно, кто пригласил")

dupes = {}
for acc in accounts.load():
    dupes.setdefault((acc["owner"], acc.get("holder"), (acc.get("strategy") or "").casefold()),
                     []).append(acc["login"])
for (owner, holder, strategy), logins in dupes.items():
    if strategy and len(logins) > 1:
        check(False, f"{holder}: стратегия {strategy} повторяется", f"счета {logins}")

print("\n" + "═" * 40)
if BAD:
    print(f"НАЙДЕНО ПРОБЛЕМ: {len(BAD)}")
    for b in BAD:
        print("  •", b)
    raise SystemExit(1)
print("ВСЁ СХОДИТСЯ")
