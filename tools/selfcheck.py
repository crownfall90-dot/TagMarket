"""Проверка логики дедупликации, форматирования и сводок. python selfcheck.py"""

import os
import sys

# запускаемся из tools/, а модули лежат в корне проекта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import os
import tempfile
from datetime import datetime

os.environ.setdefault("STATE_DB", os.path.join(tempfile.mkdtemp(), "t.db"))
for k in ("TELEGRAM_BOT_TOKEN", "TM_ROOT", "TM_USER", "TM_PUBLIC_KEY", "TM_PRIVATE_KEY"):
    os.environ.setdefault(k, "x")

import trades
from bot import fmt_deposit, fmt_lead, open_db, parse_date, period, row_id, unseen

db = open_db()

# ── дедупликация ──────────────────────────────────────────────────────────
rows = [{"id": "1", "amount": "500", "currency": "USD"}, {"id": "2", "amount": "10"}]
fresh, first = unseen(db, "deposit", rows)
assert first and len(fresh) == 2, (first, fresh)

fresh, first = unseen(db, "deposit", rows)
assert not first and fresh == [], fresh

fresh, first = unseen(db, "deposit", rows + [{"id": "3", "amount": "70"}])
assert not first and [r["id"] for r in fresh] == ["3"], fresh

a, b = {"amount": "5", "email": "a@b.c"}, {"amount": "9", "email": "a@b.c"}
assert row_id(a) != row_id(b)
assert row_id(a) == row_id(dict(reversed(list(a.items()))))

fresh, _ = unseen(db, "lead", [{"id": "1"}])
assert len(fresh) == 1, "разные kind не должны пересекаться по id"

# таблица дедупликации не должна расти бесконечно
import partner as _partner
_keep, _partner.SEEN_KEEP = _partner.SEEN_KEEP, 10
try:
    unseen(db, "grow", [{"id": str(i)} for i in range(40)])
    left = db.execute("SELECT COUNT(*) FROM seen WHERE kind='grow'").fetchone()[0]
    assert left == 10, f"должно остаться 10 последних, осталось {left}"
    # свежая запись всё ещё распознаётся как новая
    fresh, _ = unseen(db, "grow", [{"id": "999"}])
    assert len(fresh) == 1
finally:
    _partner.SEEN_KEEP = _keep

# ── форматирование партнёрских событий ────────────────────────────────────
import partner

# портал склеивает &currency= в HTML-сущность &curren; — валюта уезжает в сумму
assert partner.money({"amount": "3073.00¤cy=ZAR"}) == "3073.00 ZAR", \
    partner.money({"amount": "3073.00¤cy=ZAR"})
assert partner.money({"amount": "50", "currency": "EUR"}) == "50 EUR"
assert partner.money({"amount": "50"}) == "50 USD", "без валюты подставляем USD"

# первый депозит клиента выделяется отдельно от обычного
assert "Первый депозит" in fmt_deposit({"id": "9", "amount": "100", "is_ftd": "true"})
assert "Первый депозит" not in fmt_deposit({"id": "8", "amount": "100"})
# свой кабинет узнаётся по номеру: это не «депозит клиента», а свои деньги
import partner as _p
assert _p.whose({"customer_no": "CU-неизвестный"}) == ("CU-неизвестный", False)
assert "&lt;b&gt;" in fmt_lead({"id": "7", "name": "<b>x"}), "HTML в именах должен экранироваться"
assert fmt_deposit({}) and fmt_lead({}), "пустая запись не должна ронять форматтер"


# ── сводка по сделкам ─────────────────────────────────────────────────────
def deal(net_parts, day=11, closing=True, balance=False, comment=""):
    profit, swap, comm = net_parts
    return {"ticket": 1, "time": datetime(2026, 8, day, 12, 0), "symbol": "EURUSD",
            "side": "BUY", "volume": 0.1, "price": 1.1, "profit": profit, "swap": swap,
            "commission": comm, "net": profit + swap + comm, "is_balance": balance,
            "is_closing": closing, "is_opening": False, "comment": comment}


rows = [deal((100.0, -2.0, -3.0)),          # чистыми +95
        deal((-50.0, 0.0, -3.0), day=10),   # чистыми -53
        deal((7.0, 0.0, 0.0), closing=False),                                    # открытие
        deal((500.0, 0, 0), closing=False, balance=True, comment="Deposit"),     # перевод
        deal((-4.0, 0, 0), closing=False, balance=True, comment="Inactivity Fee"),  # издержка
        # доля брокера: уже снята net_of_fee, расходом считать нельзя
        deal((-12.6, 0, 0), closing=False, balance=True, comment="PF Deduction")]

s = trades.summary(rows)
assert s["count"] == 2, s
assert abs(s["net"] - 42.0) < 1e-9, s["net"]          # 95 - 53, своп и комиссия учтены
assert (s["wins"], s["losses"]) == (1, 1), s
assert abs(s["best"] - 95.0) < 1e-9 and abs(s["worst"] + 53.0) < 1e-9, s
assert abs(s["transfers"] - 500.0) < 1e-9, "пополнение — перевод, не результат"

# движение денег считается в реальных деньгах: капитал усилен плечом, а вывод
# прибыли лежит 1:1 — сложение «как на счёте» завышало сумму
trades._multiplier = 24
_moves = trades.summary([
    deal((720.0, 0, 0), closing=False, balance=True, comment="Deposit"),
    deal((-736.32, 0, 0), closing=False, balance=True, comment="Capital Withdrawal"),
    deal((-47.13, 0, 0), closing=False, balance=True, comment="Profit Withdrawal")])
assert abs(_moves["moves"] - (30.0 - 30.68 - 47.13)) < 0.01, _moves["moves"]
assert abs(_moves["transfers"] + 63.45) < 0.01, "сырая сумма остаётся как есть"
trades._multiplier = 1
assert abs(s["platform"] + 4.0) < 1e-9, "плата платформы — издержка"
assert abs(s["total"] - 38.0) < 1e-9, "итог инвестора = сделки минус плата платформы"

# сверка классификации с реальными комментариями брокера
assert trades.is_transfer({"comment": "Profit Withdrawal"})
assert trades.is_transfer({"comment": "Upgrade-54.00"})
assert trades.is_transfer({"comment": "Adjust-2.25"}), "корректировка апгрейда — перевод, не расход"

# Реинвест приходит парой: Adjust списывает из профита (реальные деньги, 1:1),
# Upgrade добавляет столько же в капитал (×24 на счёте). Приняв Adjust за
# капитал, бот делил его на плечо и показывал -0.29 вместо -6.92
trades._multiplier = 24
assert trades.is_profit_side({"comment": "Adjust-6.92"}), "Adjust — движение по профиту"
assert not trades.is_profit_side({"comment": "Upgrade-166.08"}), "Upgrade — капитал"
assert abs(trades.own_amount({"net": -6.92, "comment": "Adjust-6.92"}) + 6.92) < 1e-9,     "Adjust не делится на плечо"
assert abs(trades.own_amount({"net": 166.08, "comment": "Upgrade-166.08"}) - 6.92) < 0.01,     "Upgrade делится: 166.08 ÷ 24 = 6.92"
trades._multiplier = 1
assert not trades.is_transfer({"comment": "PF Deduction"}), "плата платформы — расход инвестора"

# капитал в отчётах берётся из терминала — в тесте фиксируем
_cap0 = trades.capital
trades.capital = lambda: 1000.0
report = trades.fmt_report("Тест", rows, "USD", "подзаголовок")
# главная цифра — чистыми: (95 − 53 − 4 платы) = 38 валовых, минус 30% комиссии брокера
assert "+26.60" in report and "$" in report, report
assert "заработано: +38.00" in report and "удержано:" in report, report
assert "по дням" in report, "мини-график формы периода"
assert "11.40" in report, "видно, сколько именно удержал брокер: 38.00 − 26.60"
assert "плата платформы: -4.00" in report, report

# капитал усиливается плечом (÷24), а вывод прибыли — реальные деньги (×1)
trades._multiplier = 24
assert abs(trades.own_amount({"net": 2226.96, "comment": "Deposit"}) - 92.79) < 0.01, \
    "пополнение капитала делится на плечо"
assert abs(trades.own_amount({"net": -47.13, "comment": "Profit Withdrawal"}) + 47.13) < 1e-9, \
    "вывод прибыли — реальные деньги, без деления"
assert abs(trades.own_amount({"net": -736.32, "comment": "Capital Withdrawal"}) + 30.68) < 0.01, \
    "вывод капитала делится на плечо"
trades._multiplier = 1

# формула профита сделки (сверено со скриншотом канала 14.08.2026):
# (валовый профит − лот-комиссия) × 0.7. Пример: (94.32 − 10.97) × 0.7 = 58.345
_trade = {"net": 94.32 - 10.97}          # profit + commission, как в _convert
assert abs(trades.net_of_fee(trades.mine(_trade["net"])) - 58.345) < 0.001, \
    trades.net_of_fee(trades.mine(_trade["net"]))

# доля брокера 30% применяется и к прибыли, и к убытку
assert abs(trades.net_of_fee(100.0) - 70.0) < 1e-9
assert abs(trades.net_of_fee(-50.0) + 35.0) < 1e-9, "убыток тоже уменьшается на долю брокера"
assert trades.net_of_fee(0.0) == 0.0
assert "10.08" in report and "11.08" in report, "при периоде больше суток нужна разбивка по дням"
assert "подзаголовок" in report
assert "сделок не было" in trades.fmt_report("Пусто", [], "USD").lower()

deals = trades.fmt_deals("Список", rows, "USD")
trades.capital = _cap0
# итог списка — чистыми: (95 − 53) валовых × 0.7
assert "EURUSD" in deals and "+29.40$" in deals, deals
assert "баланс" in deals, "балансовые операции видны в списке"

# мои деньги = капитал + удержанная прибыль (прибыль ×1, не делится на плечо).
# Сверено с порталом: SONIC капитал 2500, баланс 60039.40 → мои 2539.40.
class _Acc:
    login, balance, currency, server, equity = 50712138, 60039.40, "USD", "s", 60039.40


trades._base, trades._base_at, trades._multiplier = 2500.0, datetime(2026, 8, 14), 24
_saved_account = trades.account
_saved_capmoves = trades._capital_moves
trades.account = lambda: _Acc()
trades._capital_moves = lambda since: 0.0       # пока движений капитала нет
try:
    assert abs(trades.invested() - 2539.40) < 0.01, trades.invested()
    assert abs(trades.capital() - 2500.0) < 0.01
    # реинвест 30$ (на счёте +720) после привязки → капитал 2530
    trades._capital_moves = lambda since: 30.0
    assert abs(trades.capital() - 2530.0) < 0.01, trades.capital()
    trades._capital_moves = lambda since: 0.0
    # пополнение/реинвест меняет капитал: было → стало
    dep = {"is_balance": True, "is_opening": False, "is_closing": False,
           "net": 720.0, "comment": "Deposit", "time": datetime(2026, 8, 14, 12, 0)}
    n = trades.fmt_notification(dep, "USD")
    assert "+30.00$" in n and "Пополнение" in n, n     # 720 ÷ 24 = 30 реальных
    # разряды разделяет узкий неразрывный пробел — сверяем через него же
    _sep = trades.NBSP
    assert f"было 2{_sep}470.00" in n and f"2{_sep}500.00" in n, n

    # вывод чистого профита баланс стратегии НЕ меняет
    pw = {"is_balance": True, "is_opening": False, "is_closing": False,
          "net": -11.14, "comment": "Profit Withdrawal", "time": datetime(2026, 8, 14, 13, 0)}
    n = trades.fmt_notification(pw, "USD")
    assert "-11.14$" in n and "не изменил" in n, n
    assert "2500.00" in n, "баланс стратегии = капитал, при выводе профита не меняется"
finally:
    trades.account = _saved_account
    trades._capital_moves = _saved_capmoves
    trades._base, trades._base_at, trades._multiplier = None, None, 1

# ── оформление ────────────────────────────────────────────────────────────
assert trades.vol(0.5) == "0.50" and trades.vol(0.0004) == "0.0004", "микро-лоты не должны схлопываться в 0.00"
assert trades.bar(10, 10, 8) == "█" * 8 and trades.bar(-10, 10, 8) == "░" * 8
assert trades.bar(0.1, 10, 8) == "█", "маленькое значение всё равно рисует полосу"
assert trades.bar(1, 0) == "", "нулевой масштаб не должен делить на ноль"
assert trades.winrate_bar(5, 10, 10).count("▰") == 5

_saved_capital, _saved_invested = trades.capital, trades.invested
trades.capital = lambda: 100.0          # капитал стратегии
trades.invested = lambda: 142.63        # он же плюс накопленный профит
note = trades.fmt_notification(rows[0], "USD", day_net=1.5, day_count=3, total_net=9.0)
trades.capital, trades.invested = _saved_capital, _saved_invested
# порядок: дата/время, какая сделка за день, потом чистый профит
assert note.index("11.08.2026") < note.index("сделка за день") < note.index("66.50"), note
assert "+66.50" in note, "результат сделки чистыми (95 × 0.7)"
assert "Капитал" in note, "капитал показываем всегда"
assert "За день" in note and "+1.05" in note, "профит за все сделки дня (1.5 × 0.7)"
assert "3 сделки" in note, "количество сделок за день"
# накопленный профит: он лежит на стратегии, пока его не вывели, и новые
# сделки прибавляются к нему — раньше «всего» считалось за один день
assert "Накоплено профита" in note and "+42.63" in note, note
assert "142.63" in note, "всего на стратегии = капитал + накопленный профит"
assert "до комиссии +95.00" in note, "видно валовую сумму"
assert "12:00:00" in note, "нужно время сделки"
# про открытие позиции больше не пишем — важен результат, а он при закрытии
opening = dict(rows[0], is_closing=False, is_opening=True)
assert trades.fmt_notification(opening, "USD") == "", "уведомления об открытии быть не должно"

# ── периоды и даты ────────────────────────────────────────────────────────
title, since, until, subtitle = period("today")
assert since.date() == until.date() and subtitle
# в понедельник начало недели совпадает с сегодня — не строгое неравенство
assert period("week")[1].date() <= period("today")[1].date()
assert period("lastweek")[1].date() < period("week")[1].date(), "прошлая неделя раньше"
assert period("all")[1].year == 2000
assert parse_date("05.08.2026") == parse_date("2026-08-05") == parse_date("05/08/2026")

# ── изоляция пользователей ────────────────────────────────────────────────
import accounts as accmod

orig_path = accmod.PATH
accmod.PATH = os.path.join(tempfile.mkdtemp(), "accounts.json")
try:
    accmod.add({"owner": 111, "name": "A", "login": 1, "password": "x", "server": "s"})
    accmod.add({"owner": 222, "name": "B", "login": 2, "password": "x", "server": "s"})
    assert [a["name"] for a in accmod.load(111)] == ["A"], "владелец 111 не должен видеть B"
    assert [a["name"] for a in accmod.load(222)] == ["B"], "владелец 222 не должен видеть A"
    assert len(accmod.load()) == 2, "без owner load() должен отдавать всех — это нужно опросу"
    assert accmod.by_name("A", 222) is None, "чужое имя счёта не должно резолвиться"
    try:
        accmod.add({"owner": 111, "name": "A", "login": 9, "password": "x", "server": "s"})
        assert False, "повторное имя у того же владельца должно падать"
    except ValueError:
        pass
    # то же имя у другого владельца — это разные счета, конфликта быть не должно
    accmod.add({"owner": 222, "name": "A", "login": 3, "password": "x", "server": "s"})
    # кабинеты: счета разных кабинетов не должны смешиваться
    accmod.add({"owner": 111, "name": "C1", "login": 11, "password": "x", "server": "s",
                "cabinet": "CU228816", "holder": "Ivan Petrov"})
    accmod.add({"owner": 111, "name": "C2", "login": 12, "password": "x", "server": "s",
                "cabinet": "CU228816", "holder": "Ivan Petrov"})
    accmod.add({"owner": 111, "name": "D1", "login": 13, "password": "x", "server": "s",
                "cabinet": "CU261780", "holder": "Other Person"})
    cabs = accmod.cabinets(111)
    assert set(cabs) >= {"CU228816", "CU261780"}, cabs
    assert cabs["CU228816"]["holder"] == "Ivan Petrov"
    assert sorted(a["name"] for a in cabs["CU228816"]["accounts"]) == ["C1", "C2"]
    assert [a["name"] for a in accmod.in_cabinet(111, "CU261780")] == ["D1"]
    assert accmod.cabinets(222).get("CU228816") is None, "чужие кабинеты не видны"
    # счёт без кабинета попадает в отдельную группу, а не теряется
    assert accmod.NO_CABINET in accmod.cabinets(111)
    for n in ("C1", "C2", "D1"):
        accmod.remove(n, 111)

    # общий выключатель уведомлений по стратегии гасит все типы разом,
    # но не мешает обновлять данные для отчётов
    acc = {"enabled": True, "notify": {"all": False, "trades": True, "deposits": True}}
    assert not accmod.notifies(acc, "trades"), "общий выключатель должен гасить всё"
    assert not accmod.notifies(acc, "deposits")
    acc["notify"]["all"] = True
    assert accmod.notifies(acc, "trades"), "включённые уведомления должны проходить"
    acc["notify"]["trades"] = False
    assert not accmod.notifies(acc, "trades"), "отдельный тип можно выключить"
    assert accmod.notifies(acc, "deposits"), "остальные типы при этом работают"
    acc["enabled"] = False
    assert not accmod.notifies(acc, "deposits"), "выключенные обновления гасят всё"

    # настройки уведомлений
    a111 = accmod.by_name("A", 111)
    assert accmod.notifies(a111, "trades"), "по умолчанию уведомления включены"
    assert accmod.toggle("A", 111, "trades") is False, "первое нажатие выключает"
    assert not accmod.notifies(accmod.by_name("A", 111), "trades"), "выключение должно сохраниться"
    assert accmod.notifies(accmod.by_name("A", 111), "deposits"), "другие типы не задеты"
    assert accmod.toggle("A", 111, "enabled") is False, "счёт можно приглушить целиком"
    assert not accmod.notifies(accmod.by_name("A", 111), "deposits"), \
        "приглушённый счёт молчит по всем типам"
    accmod.toggle("A", 111, "enabled")      # возвращаем как было
    accmod.toggle("A", 111, "trades")

    # переименование
    accmod.rename("A", 111, "A-new")
    assert accmod.by_name("A-new", 111) and not accmod.by_name("A", 111)
    try:
        accmod.rename("A-new", 111, "B")     # B принадлежит другому владельцу — не конфликт
        accmod.rename("B", 111, "A-new")     # вернём обратно
    except ValueError:
        assert False, "имя, занятое другим владельцем, не должно мешать"
    accmod.add({"owner": 111, "name": "Z", "login": 7, "password": "x", "server": "s"})
    try:
        accmod.rename("Z", 111, "A-new")
        assert False, "переименование в своё же занятое имя должно падать"
    except ValueError:
        pass
    accmod.remove("Z", 111)
    accmod.rename("A-new", 111, "A")

    # обмен счетами: выбираем по логину — имя может смениться
    _login_a = accmod.by_name("A", 111)["login"]
    added = accmod.share([_login_a], 111, 222)
    assert added == ["A (2)"], f"у получателя уже есть свой A, ждём переименование: {added}"
    assert accmod.by_name("A", 111), "оригинал остаётся у владельца"
    assert accmod.by_name("A (2)", 222)["login"] == accmod.by_name("A", 111)["login"]
    try:
        accmod.share([_login_a], 111, 111)
        assert False, "поделиться с самим собой нельзя"
    except ValueError:
        pass
    accmod.remove("A (2)", 222)

    assert not accmod.remove("A", 999), "удаление чужого счёта не должно находить его"
    assert accmod.remove("A", 111), "владелец должен уметь удалить свой счёт"
    assert [a["name"] for a in accmod.load(111)] == [], "у владельца 111 счетов не осталось"
    assert sorted(a["name"] for a in accmod.load(222)) == ["A", "B"], \
        "одноимённый счёт другого владельца не должен пострадать"
finally:
    accmod.PATH = orig_path

# ── свёртка прошлых месяцев ───────────────────────────────────────────────
import store as storemod

sdb = storemod.open_db(os.path.join(tempfile.mkdtemp(), "t.db"))
storemod.save_state(sdb, 777, 2400.0, 2400.0, "USD", "srv")


def _deal(ticket, when, net, closing=True, balance=False, comment=""):
    return {"ticket": ticket, "time": when, "symbol": "XAUUSD", "side": "BUY",
            "volume": 0.1, "price": 1.0, "profit": net, "swap": 0.0, "commission": 0.0,
            "net": net, "is_balance": balance, "is_closing": closing,
            "is_opening": False, "comment": comment, "position": 0}


storemod.save_deals(sdb, 777, [
    _deal(1, "2026-07-05T10:00:00", 100.0),                     # прошлый месяц
    _deal(2, "2026-07-20T10:00:00", -40.0),
    _deal(3, "2026-07-25T10:00:00", -6.0, closing=False, balance=True, comment="PF Deduction"),
    _deal(4, "2026-07-01T09:00:00", 1200.0, closing=False, balance=True, comment="Deposit"),
    _deal(9, "2026-08-10T10:00:00", 50.0),                      # текущий месяц
])
assert storemod.last_ticket(sdb, 777) == 9

removed = storemod.rollup(sdb, "2026-08-01", trades.is_transfer)
assert removed == 4, f"свернуть должно было 4 записи июля, свернуло {removed}"

left = storemod.fetch(sdb, 777, datetime(2000, 1, 1), datetime(2030, 1, 1))
assert [r["ticket"] for r in left] == [9], "в базе остаётся только текущий месяц"
assert storemod.last_ticket(sdb, 777) == 9, "тикет пережил чистку — агент не зальёт заново"

(july,) = storemod.months(sdb, 777)
assert july["month"] == "2026-07"
assert july["trades"] == 2, july
assert abs(july["gross"] - 60.0) < 1e-9, "100 − 40 до комиссии"
assert abs(july["platform"] + 6.0) < 1e-9, "плата платформы отдельно"
assert abs(july["deposits"] - 1200.0) < 1e-9, "пополнение — база для процентов"
# статистика переживает свёртку: сделок в базе уже нет, а доля плюсовых нужна
assert (july["wins"], july["losses"]) == (1, 1), july
assert abs(july["best"] - 100.0) < 1e-9 and abs(july["worst"] + 40.0) < 1e-9, july

# повторная свёртка ничего не ломает и не задваивает
storemod.rollup(sdb, "2026-08-01", trades.is_transfer)
assert len(storemod.months(sdb, 777)) == 1, "месяц не должен задвоиться"

# Удержание доли брокера («PF Deduction») приходит раз в неделю и равно ровно
# 30% от валовой прибыли — те же 30%, что уже сняты net_of_fee. Если считать
# его ещё и расходом, месяц занижается на величину удержаний.
_week = [
    {"is_closing": True, "is_balance": False, "net": 104.29, "comment": "",
     "volume": 0.0, "swap": 0.0, "commission": 0.0},
    {"is_closing": False, "is_balance": True, "net": -31.29, "comment": "PF Deduction",
     "volume": 0.0, "swap": 0.0, "commission": 0.0},
]
_s = trades.summary(_week)
assert abs(_s["platform"]) < 1e-9, "удержание доли брокера — не расход платформы"
assert abs(_s["total"] - 104.29) < 1e-9, "итог не уменьшается на уже учтённые 30%"
assert abs(trades.net_of_fee(_s["total"]) - 73.003) < 1e-3, "чистыми остаётся 70%"

# Приглашения по ссылке и отключение бота.
import bot as _bot                                          # noqa: E402
import partner as _partner                                  # noqa: E402

_idb = _partner.open_db(":memory:")      # рабочую базу проверкой не трогаем
_tok = _bot.invite_new(_idb, 111, [50712138])   # приглашение хранит логин
_inv = _bot.invite_get(_idb, _tok)
assert _inv["owner"] == 111 and _inv["logins"] == [50712138], _inv
assert _inv["uses"] == 0 and not _inv["revoked"], "новая ссылка чистая"
assert _inv["max_uses"] == 1, "ссылка одноразовая — на одного человека"

# после входа одного человека ссылка гаснет (как в accept_invite)
_inv["uses"] += 1
_inv["revoked"] = _inv["uses"] >= _inv["max_uses"]
_bot.invite_save(_idb, _tok, _inv)
assert _bot.invite_get(_idb, _tok) is None, "второй человек по ней не войдёт"
_inv["revoked"] = False                      # вернём для проверок ниже
_bot.invite_save(_idb, _tok, _inv)
assert _bot.invite_get(_idb, "подделка") is None, "чужой токен доступа не даёт"
assert _bot.invite_get(_idb, "../../etc/passwd") is None, "мусор в токене отбивается"
assert len(_tok) > 8, "токен должен быть неугадываемым"
# ссылки, выданные до перехода на логины, хранят имена — понимаем и их
_acc2 = os.path.join(tempfile.mkdtemp(), "accounts.json")
import accounts as _a2                                       # noqa: E402
_old_path, _a2.PATH = _a2.PATH, _acc2
_a2.save([{"owner": 111, "name": "СТАРОЕ ИМЯ", "login": 50712138, "password": "x",
           "server": "s", "holder": "ALA", "strategy": "SONIC 1"}])
_partner.kv_set(_idb, "invite:legacy", __import__("json").dumps(
    {"owner": 111, "accounts": ["СТАРОЕ ИМЯ"], "uses": 0, "max_uses": 1, "revoked": False}))
assert _bot.invite_logins(_bot.invite_get(_idb, "legacy"), 111) == [50712138], \
    "старая ссылка с именем должна разрешаться в логин"
# после переименования ссылка на логин продолжает работать — имя ей не нужно
_a2.rename("СТАРОЕ ИМЯ", 111, "SONIC 2")
assert _bot.invite_logins({"logins": [50712138]}, 111) == [50712138], \
    "переименование не рвёт выданные ссылки"
_a2.PATH = _old_path
_partner.kv_del(_idb, "invite:legacy")      # проверили — дальше она мешает

_empty = _bot.invite_new(_idb, 111, [])
assert _bot.invite_get(_idb, _empty)["logins"] == [], "ссылка без счетов допустима"
assert _tok != _empty, "токены не повторяются"

# кого пускать по ссылке: решение принимает invite_check
_allowed = {"111"}                      # как ALLOWED_USERS в .env
_live = _bot.invite_new(_idb, 111, [50712138])
assert _bot.invite_check(_idb, 999, _live, _allowed)[0] == "ok", "новый человек проходит"
assert _bot.invite_check(_idb, 111, _live, _allowed)[0] == "own", "своя ссылка"
assert _bot.invite_check(_idb, 111, "мусор", _allowed)[0] == "bad", "чужой токен"
# действующий пользователь ссылку НЕ тратит — она ждёт незарегистрированного
assert _bot.invite_check(_idb, "111", _live, _allowed)[0] in ("own", "known")
_allowed.add("444")
assert _bot.invite_check(_idb, 444, _live, _allowed)[0] == "known", "из .env — уже свой"
_partner.kv_set(_idb, "guest:555", "1")
assert _bot.invite_check(_idb, 555, _live, _allowed)[0] == "known", "гость — уже свой"
assert _bot.invite_get(_idb, _live) is not None, "ссылка цела после своих"
# ушедший регистрируется заново, даже если остался в .env
_partner.kv_set(_idb, "left:444", "1")
assert _bot.invite_check(_idb, 444, _live, _allowed)[0] == "ok", "ушедший входит заново"
_partner.kv_del(_idb, "left:444")
# погасшая ссылка: новому — отказ, своему — «уже зарегистрирован»
_burn = _bot.invite_get(_idb, _live)
_burn["revoked"] = True
_bot.invite_save(_idb, _live, _burn)
assert _bot.invite_check(_idb, 999, _live, _allowed)[0] == "burned", "второму не войти"
assert _bot.invite_check(_idb, 444, _live, _allowed)[0] == "known", "свой видит своё"

# отозванная ссылка перестаёт существовать для входа, но видна владельцу
_inv["revoked"] = True
_bot.invite_save(_idb, _tok, _inv)
assert _bot.invite_get(_idb, _tok) is None, "по отозванной ссылке не войти"
assert _bot.invite_get(_idb, _tok, active_only=False) is not None, "запись сохраняется"
assert [t for t, _ in _bot.invite_list(_idb, 111)] == [_empty], "в списке только живые"
assert _bot.invite_list(_idb, 999) == [], "чужие ссылки не видны"

# основателя отключить нельзя — ни командой, ни кнопкой
_bot.FOUNDER = "111"
assert _bot.is_founder(111) and _bot.is_founder("111"), "основатель узнаётся по id"
assert not _bot.is_founder(222), "остальные — не основатели"
_bot.FOUNDER = ""
assert not _bot.is_founder(111), "без настройки основателя нет"

# Отключение стирает всё своё и ничего чужого, вход закрывается флагом left
_accpath = os.path.join(tempfile.mkdtemp(), "accounts.json")
_was_path, accmod.PATH = accmod.PATH, _accpath
accmod.save([{"owner": 111, "name": "A", "login": 1, "password": "x", "server": "S"},
               {"owner": 222, "name": "B", "login": 2, "password": "x", "server": "S"},
               {"owner": 222, "name": "C", "login": 3, "password": "x", "server": "S"}])
_partner.kv_set(_idb, "guest:222", "1")
_partner.kv_set(_idb, "mt5_last_ticket:222:3", "999")
_partner.kv_set(_idb, "mt5_last_ticket:111:1", "555")
_mine = _bot.invite_new(_idb, 222, [777])

_gone = _bot.wipe_user(_idb, 222)
assert _gone == {"accounts": 2, "invites": 1}, _gone
assert accmod.load(222) == [], "свои счета удалены"
assert [a["name"] for a in accmod.load(111)] == ["A"], "чужие счета не тронуты"
assert _partner.kv_get(_idb, "mt5_last_ticket:222:3") is None, "следы стёрты"
assert _partner.kv_get(_idb, "mt5_last_ticket:111:1") == "555", "чужие ключи целы"
assert _partner.kv_get(_idb, "guest:222") is None, "гостевой доступ снят"
assert _partner.kv_get(_idb, "left:222") == "1", "вход закрыт"
assert _bot.invite_get(_idb, _mine) is None, "его ссылки никого не впустят"
assert _bot.wipe_user(_idb, 222) == {"accounts": 0, "invites": 0}, "повтор безопасен"
accmod.PATH = _was_path

# Переименование меняет стратегию, а владельца в имени сохраняет: имя счёта —
# это «владелец · стратегия», и запись текста целиком стирала бы владельца.
import accounts as _acc                                      # noqa: E402
_acc.PATH = os.path.join(tempfile.mkdtemp(), "accounts.json")
_acc.save([
    {"owner": 1, "name": "ALA", "login": 1, "password": "x", "server": "s",
     "holder": "ALA", "strategy": "SONIC 1"},                       # счёт один
    {"owner": 1, "name": "DZM · NEO.FX", "login": 2, "password": "x", "server": "s",
     "holder": "DZM", "strategy": "NEO.FX"},                        # счетов несколько
    {"owner": 1, "name": "Лёня", "login": 3, "password": "x", "server": "s",
     "holder": "", "strategy": "NEO"},                              # владельца нет
])
assert _acc.rename("ALA", 1, "SONIC 2") == "ALA", "имя-владелец не меняется"
assert _acc.by_name("ALA", 1)["strategy"] == "SONIC 2", "стратегия обновилась"
assert _acc.rename("DZM · NEO.FX", 1, "NEO 2") == "DZM · NEO 2", "владелец сохранён"
assert _acc.by_name("DZM · NEO 2", 1)["strategy"] == "NEO 2"
assert _acc.rename("Лёня", 1, "NEO 3") == "NEO 3", "без владельца имя = стратегия"
try:
    _acc.rename("NEO 3", 1, "")
    raise SystemExit("пустое название должно отвергаться")
except ValueError:
    pass

# В карточке гостя видны его собственные счета — но только названия: трогать
# чужие счета нельзя, поэтому кнопок к ним быть не должно
_gdb = _partner.open_db(":memory:")
_acc.save(_acc.load() + [
    {"owner": 99, "name": "чужой", "login": 4242, "password": "x", "server": "s",
     "holder": "IVAN", "strategy": "GOLD"}])
_partner.kv_set(_gdb, "guest:99", "1")
_partner.kv_set(_gdb, "guest_by:99", "1")
_gt, _gkb = _bot.guest_view(_gdb, 1, "99")
assert "GOLD" in _gt, "название чужого счёта видно"
assert not any("4242" in b.callback_data for r in _gkb.inline_keyboard for b in r), \
    "кнопок к чужому счёту быть не должно"
_acc.remove_login(4242, 99)

# Забрать счёт у гостя: удаляем по номеру, потому что копию он мог переименовать
_taken = _acc.share([1], 1, 555)                    # поделились счётом с гостем
assert _taken, "счёт скопирован гостю"
_acc.rename(_taken[0], 555, "ГОСТЬ ПЕРЕИМЕНОВАЛ")   # гость дал своё название
assert _acc.remove_login(1, 555), "по номеру находим даже переименованную копию"
assert not _acc.load(555), "у гостя счёта не осталось"
assert _acc.by_name("ALA", 1), "у владельца оригинал на месте"
assert not _acc.remove_login(1, 555), "повторный возврат ничего не ломает"

# Стратегии тёзки разрешены у разных владельцев и запрещены у одного:
# внутри владельца две одинаковых неразличимы.
_acc.save(_acc.load() + [
    {"owner": 1, "name": "DZM · SONIC 1", "login": 4, "password": "x", "server": "s",
     "holder": "DZM", "strategy": "SONIC 1"}])
assert _acc.strategy_taken(1, "DZM", "SONIC 1"), "у этого владельца стратегия занята"
assert not _acc.strategy_taken(1, "ALA", "SONIC 1"), "у другого владельца — можно"
assert _acc.strategy_taken(1, "DZM", "sonic 1"), "регистр не должен обманывать"
try:
    _acc.rename("DZM · NEO 2", 1, "SONIC 1")     # тёзка внутри того же владельца
    raise SystemExit("повтор стратегии у одного владельца должен отвергаться")
except ValueError:
    pass
# у другого владельца то же название проходит
assert _acc.rename("ALA", 1, "SONIC 1") == "ALA", "тёзка у другого владельца разрешён"

print("OK")
