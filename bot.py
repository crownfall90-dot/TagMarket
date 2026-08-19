"""Telegram-бот TagMarkets: уведомления о сделках MT5 и партнёрских событиях,
плюс отчёты по истории за любой период.
"""

import asyncio
import hashlib
import html
import json
import logging
import logging.handlers
import os
import secrets
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, CopyTextButton, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from dotenv import load_dotenv

import accounts
import ibportal
import partner
import trades
from partner import (fmt_deposit, fmt_lead,  # noqa: F401 — их зовёт webhook_server
                     kv_del, kv_get, kv_keys, kv_set, open_db, pick, row_id, unseen)

load_dotenv()
# в фоне (pythonw) консоли нет и вывод в поток падает, поэтому пишем в файл
ROOT = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(ROOT, "logs")
os.makedirs(LOGS, exist_ok=True)

_handlers = [logging.handlers.RotatingFileHandler(
    os.path.join(LOGS, "bot.log"),
    maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
if sys.stdout is not None:
    _handlers.append(logging.StreamHandler())
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=_handlers)

def utcnow() -> datetime:
    """UTC без зоны. datetime.utcnow() объявлен устаревшим, а в базе лежат
    наивные значения — с ними и сравниваем, поэтому зону сразу отбрасываем.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

log = logging.getLogger("tagbot")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", 120))      # партнёрский API
MT5_POLL_SECONDS = int(os.getenv("MT5_POLL_SECONDS", 5))
# сколько неудачных кругов подряд терпим, прежде чем сказать о потере связи
MT5_ALERT_AFTER = int(os.getenv("MT5_ALERT_AFTER", 40))
# агент синхронизирует раз в 15 сек; молчит дольше 5 минут — терминал/ПК недоступен
TERMINAL_STALE = int(os.getenv("TERMINAL_STALE", 300))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", 3))
# сколько минут молчания Telegram терпим, прежде чем перезапуститься
TELEGRAM_DEAD_MIN = int(os.getenv("TELEGRAM_DEAD_MIN", 5))
DIGEST_HOUR = int(os.getenv("DIGEST_HOUR", 10))     # час ежедневной сводки
# Основатель: его бот отключить не даст никому, включая его самого. Без явной
# настройки берём первый id из ALLOWED_USERS — он и заводил бота
FOUNDER = (os.getenv("FOUNDER_ID")
           or next(iter([x.strip() for x in os.getenv("ALLOWED_USERS", "").split(",")
                         if x.strip()]), ""))
DB = os.getenv("STATE_DB", os.path.join("data", "state.db"))
TG_LIMIT = 4000


async def send(bot: Bot, chat_id, text: str, markup=None):
    if len(text) > TG_LIMIT:
        text = text[:TG_LIMIT] + "\n<i>…сообщение обрезано</i>"
    try:
        await bot.send_message(chat_id, text, reply_markup=markup)
    except TelegramBadRequest as e:
        # чужой текст (ошибка библиотеки, имя счёта) мог принести ломаную разметку —
        # сообщение важнее оформления
        log.error("Telegram отверг разметку (%s), шлю как есть: %r", e, text[:200])
        await bot.send_message(chat_id, html.escape(text), parse_mode=None, reply_markup=markup)


# ── периоды и клавиатуры ──────────────────────────────────────────────────

PERIODS = [("yesterday", "Вчера"), ("week", "Эта неделя"),
           ("lastweek", "Прошлая неделя"), ("month", "Этот месяц"), ("all", "Всё время")]
# в новой навигации «Сегодня» — такой же period, как остальные
PERIODS_FULL = [("today", "Сегодня")] + PERIODS


def day_bounds(d: date) -> tuple[datetime, datetime]:
    return datetime.combine(d, time.min), datetime.combine(d, time.max)


def period(name: str) -> tuple[str, datetime, datetime, str]:
    """(заголовок, с, по, подзаголовок)"""
    today = trades.clock().date()
    if name == "yesterday":
        d = today - timedelta(days=1)
        return "Вчера", *day_bounds(d), trades.with_weekday(d)
    if name == "week":
        a = today - timedelta(days=today.weekday())      # понедельник текущей недели
        return "Эта неделя", datetime.combine(a, time.min), datetime.combine(today, time.max), \
               f"{a:%d.%m} — {today:%d.%m.%Y}"
    if name == "lastweek":
        a = today - timedelta(days=today.weekday() + 7)  # понедельник прошлой недели
        b = a + timedelta(days=4)                        # по пятницу
        return "Прошлая неделя", datetime.combine(a, time.min), datetime.combine(b, time.max), \
               f"{a:%d.%m} — {b:%d.%m.%Y}"
    if name == "month":
        a = today.replace(day=1)
        return "Этот месяц", datetime.combine(a, time.min), datetime.combine(today, time.max), \
               f"{a:%d.%m} — {today:%d.%m.%Y}"
    if name == "all":
        return "За всё время", datetime(2000, 1, 1), datetime.combine(today, time.max), \
               "вся история счёта"
    return "Сегодня", *day_bounds(today), trades.with_weekday(today)


ALL = "*"      # псевдо-счёт «все вместе»

# Уведомления приходят пачками, и полная клавиатура периодов в каждом только
# засоряет чат: из уведомления нужен один переход — к общей картине.
DASHBOARD_BTN = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📊 Дашборд", callback_data="dash")]])

MONTHS = trades.MONTHS      # словарь один на бот и отчёты


def menu(active: str = "today", who: str = None, owner=None) -> InlineKeyboardMarkup:
    """Клавиатура отчёта: счета текущего кабинета, периоды, действия."""
    def label(key, text, cur):
        return f"◉ {text}" if key == cur else f"○ {text}"

    rows = []
    accs = accounts.load(owner)
    groups = accounts.cabinets(owner)

    # счета показываем в пределах кабинета выбранного счёта — иначе они
    # перемешиваются и непонятно, из какого кабинета какой
    current = next((a for a in accs if a["name"] == who), accs[0] if accs else None)
    same_cabinet = accs
    if current and len(groups) > 1:
        key = current.get("cabinet") or accounts.NO_CABINET
        same_cabinet = [a for a in accs if (a.get("cabinet") or accounts.NO_CABINET) == key]

    if len(same_cabinet) > 1:
        who = who or same_cabinet[0]["name"]
        chips = [InlineKeyboardButton(text=label(a["name"], a["name"], who),
                                      callback_data=f"rep:{active}:{a['name']}")
                 for a in same_cabinet]
        rows += [chips[i:i + 2] for i in range(0, len(chips), 2)]
        rows.append([InlineKeyboardButton(text=label(ALL, "Все счета кабинета", who),
                                          callback_data=f"rep:{active}:{ALL}")])

    suffix = f":{who}" if who else ""
    buttons = [InlineKeyboardButton(text=label(k, t, active), callback_data=f"rep:{k}{suffix}")
               for k, t in PERIODS]
    rows += [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    if active != "today":
        rows.append([InlineKeyboardButton(text="↩︎ Сегодня", callback_data=f"rep:today{suffix}")])

    rows.append([InlineKeyboardButton(text="↩︎ Назад", callback_data="dash"),
                 InlineKeyboardButton(text="⚙︎ Настройки", callback_data="cfg")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def month_growth(login: int, rows: list[dict]) -> float:
    """Доходность месяца перед его свёрткой — сделки после неё удаляются.

    Считаем на месте: восстановить процент по одним суммам уже нельзя, а без
    него история за прошлые месяцы врёт при пополнениях.
    """
    acc = next((a for a in accounts.load() if int(a["login"]) == int(login)), None)
    if not acc:
        return None
    trades.use(acc)
    # из базы время приходит строкой, а расчёт сравнивает даты — приводим тип
    rows = [{**r, "time": datetime.fromisoformat(r["time"])
             if isinstance(r["time"], str) else r["time"]} for r in rows]
    # движения капитала берём из базы целиком: сворачиваемый месяц ещё не удалён
    # и уже входит сюда — складывать его со своими же строками нельзя, переводы
    # посчитались бы дважды и капитал восстановился бы неверно
    flows = trades.fetch(datetime(2000, 1, 1), trades.clock() + timedelta(days=1))
    return trades.growth_pct(rows, flows)


def account_totals(acc: dict) -> dict | None:
    """Сейчас на счёте / заработано / ROI. None, если данных по счёту нет."""
    if not connect(acc):
        return None
    my = trades.capital()       # реальные деньги, не торговый баланс ×плечо
    rows = trades.fetch(datetime(2000, 1, 1), trades.clock())
    # плюс свёрнутые месяцы: их сделки из базы удалены, остались только суммы
    earned = trades.net_of_fee(trades.mine(
        trades.summary(rows)["total"] + trades.archived_before_now()[0]))

    # текущий месяц отдельно — это то, что интереснее всего смотреть каждый день
    month_start = trades.clock().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_rows = [r for r in rows if r["time"] >= month_start]
    m = trades.summary(month_rows)
    month_net = trades.net_of_fee(trades.mine(m["total"]))

    # проценты — той же мерой, что в отчётах: доходность каждой сделки к капиталу
    # на её момент. Простое «профит ÷ капитал» занижало счёт с пополнением до
    # +2.1% там, где соседние счета с той же стратегией дают +7.1%
    by_day: dict = {}
    for r in month_rows:
        if r["is_closing"]:
            by_day.setdefault(r["time"].date(), 0.0)
            by_day[r["time"].date()] += r["net"]

    return {"now": my, "pnl": earned, "kept": trades.retained(),
            "days": [trades.net_of_fee(trades.mine(by_day[d])) for d in sorted(by_day)],
            "month_pct": trades.growth_pct(month_rows, rows),
            "roi": trades.growth_all(),
            "month_net": month_net, "month_trades": m["count"],
            "cur": trades.currency()}


def dashboard(owner) -> tuple[str, InlineKeyboardMarkup]:
    """Стартовый экран: по каждому кабинету — вложено, PnL и ROI."""
    groups = accounts.cabinets(owner)
    if not groups:
        return NO_ACCOUNTS, InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="＋ Добавить счёт", callback_data="add")]])

    blocks, rows = [], []
    grand_now = grand_pnl = grand_month = 0.0
    grand_weighted = grand_weighted_roi = grand_kept = 0.0
    cur = "USD"
    for cab, info in sorted(groups.items()):
        now = pnl = month = 0.0
        month_trades = dead = 0
        weighted = weighted_roi = 0.0   # проценты кабинета — средние по счетам
        kept = 0.0                      # профит, не выведенный со стратегии
        days: list = []
        for acc in info["accounts"]:
            t = account_totals(acc)
            if not t:
                dead += 1
                continue
            now += t["now"]
            kept += t["kept"]
            pnl += t["pnl"]
            month += t["month_net"]
            month_trades += t["month_trades"]
            weighted += t["month_pct"] * t["now"]
            weighted_roi += t["roi"] * t["now"]
            # дни складываем поштучно: у счетов кабинета сделки в одни и те же дни
            for i, v in enumerate(t["days"]):
                if i < len(days):
                    days[i] += v
                else:
                    days.append(v)
            cur = t["cur"] or cur
        grand_now += now
        grand_pnl += pnl
        grand_month += month
        grand_kept += kept
        grand_weighted += weighted
        grand_weighted_roi += weighted_roi
        roi = weighted_roi / now if now else 0.0
        # складывать профит и делить на общий капитал нельзя: у счетов разный
        # размер, и крупный счёт заглушал бы процент мелкого. Берём средний по
        # счетам процент, взвешенный их капиталом
        month_pct = weighted / now if now else 0.0

        who = info["holder"] or (cab if cab != accounts.NO_CABINET else "Без кабинета")
        n = len(info["accounts"])
        note = f"\n<i>{dead} из {n} без связи с терминалом</i>" if dead else ""
        # не <pre>: моноширинный шрифт телефона кириллицу не держит и числа в
        # таблице разъезжаются. Цитата group'ирует блок полосой слева, оставаясь
        # обычным текстом — ровно на любом экране
        # мини-график месяца: форма видна раньше, чем прочитаны цифры
        shape = trades.spark(days)
        line = f"<code>{shape}</code>  " if shape else ""
        mark = "▲" if month >= 0 else "▼"
        blocks.append(
            f"👤 <b>{html.escape(who)}</b>\n"
            # рядом с капиталом — профит, который лежит нетронутым: без него
            # непонятно, сколько денег на стратегии на самом деле
            f"<blockquote>💎 <b>{trades.amount(now, cur)}</b>"
            f" + <b>{trades.amount(kept)}</b> <i>профит</i>\n"
            f"{mark} {MONTHS[trades.clock().month].lower()} <b>{trades.amount(month, signed=True)}</b>"
            f" · <i>{trades.pct(month_pct)}</i>\n"
            f"◆ всего <b>{trades.amount(pnl, signed=True)}</b> · <i>{trades.pct(roi)}</i>\n"
            f"{line}<i>{n} счёт{'а' if 1 < n < 5 else 'ов' if n != 1 else ''} · "
            f"{month_trades} сделок</i></blockquote>{note}")
        rows.append([InlineKeyboardButton(text=f"👤 {who[:28]}",
                                          callback_data=f"cab:{cab}:today")])

    now_month = MONTHS[trades.clock().month]
    head = f"📊 <b>Мой кабинет</b> · <i>{now_month} {trades.clock():%Y}</i>"
    if len(groups) > 1:
        total_roi = grand_weighted_roi / grand_now if grand_now else 0.0
        month_pct = grand_weighted / grand_now if grand_now else 0.0
        mark = "▲" if grand_month >= 0 else "▼"
        head += (f"\n<blockquote>💎 <b>{trades.amount(grand_now, cur)}</b>"
                 f" + <b>{trades.amount(grand_kept)}</b> <i>профит</i>\n"
                 f"{mark} {now_month.lower()} <b>{trades.amount(grand_month, signed=True)}</b>"
                 f" · <i>{trades.pct(month_pct)}</i>\n"
                 f"◆ всего <b>{trades.amount(grand_pnl, signed=True)}</b>"
                 f" · <i>{trades.pct(total_roi)}</i></blockquote>")

    rows.append([InlineKeyboardButton(text="＋ Счёт", callback_data="add"),
                 InlineKeyboardButton(text="⚙︎ Настройки", callback_data="cfg")])
    text = f"{head}\n{trades.THIN}\n" + "\n\n".join(blocks) + "\n\n<i>Выбери аккаунт ниже.</i>"
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def period_row(prefix: str, active: str) -> list[list[InlineKeyboardButton]]:
    """Ряды кнопок периодов для кабинета или счёта."""
    buttons = [InlineKeyboardButton(text=("◉ " if k == active else "") + t,
                                    callback_data=f"{prefix}:{k}") for k, t in PERIODS_FULL]
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


def cabinet_view(owner, cabinet: str, period_name: str) -> tuple[str, InlineKeyboardMarkup]:
    """Кабинет: сводка по всем его счетам + переход к конкретному."""
    accs = accounts.in_cabinet(owner, cabinet)
    if not accs:
        return dashboard(owner)

    # заголовок владельца печатает build_all — второй раз его не повторяем
    text = build_all(period_name, owner, cabinet)

    rows = [[InlineKeyboardButton(text=f"▸ {short_name(a, cabinet)}",
                                  callback_data=f"acc:{a['login']}:{period_name}")]
            for a in accs]
    rows += period_row(f"cab:{cabinet}", period_name)
    rows.append([InlineKeyboardButton(text="↩︎ Назад", callback_data="dash"),
                 InlineKeyboardButton(text="⚙︎ Настройки", callback_data="cfg")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def account_view(owner, login: int, period_name: str) -> tuple[str, InlineKeyboardMarkup]:
    """Конкретный счёт за выбранный период."""
    acc = next((a for a in accounts.load(owner) if int(a["login"]) == int(login)), None)
    if not acc:
        return dashboard(owner)

    if not connect(acc):
        text = no_mt5(acc)
    else:
        title, since, until, subtitle = period(period_name)
        cur = trades.currency()
        text = (account_head(acc, cur) + "\n\n" +
                trades.fmt_report(title, trades.fetch(since, until), cur, subtitle, since,
                                  with_deals=True, until=until))

    rows = period_row(f"acc:{login}", period_name)
    back = accounts.NO_CABINET if not acc.get("cabinet") else acc["cabinet"]
    rows.append([InlineKeyboardButton(text="↩︎ Назад",
                                      callback_data=f"cab:{back}:{period_name}"),
                 InlineKeyboardButton(text="⚙︎ Настройки", callback_data="cfg")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


# ── настройки ─────────────────────────────────────────────────────────────

def bell(acc: dict) -> str:
    return "🔕" if accounts.silent(acc) else "🔔"


def group_bell(accs: list[dict]) -> str:
    """Колокольчик аккаунта: 🔔 говорят все, 🔕 молчат все, 🔔̶ часть молчит."""
    quiet = sum(accounts.silent(a) for a in accs)
    if not quiet:
        return "🔔"
    return "🔕" if quiet == len(accs) else "🔔🔕"


def link_alerts_on(db, owner) -> bool:
    """Слать ли сообщения о пропаже и возврате связи с терминалом.

    По умолчанию выключено: связь рвётся и ночью (перезагрузка ПК, интернет),
    а сделки после возврата всё равно подтянутся — большинству эти сообщения
    только мешают.
    """
    return kv_get(db, f"link_alerts:{owner}") == "1"


def settings_menu(owner, db=None) -> tuple[str, InlineKeyboardMarkup]:
    accs = accounts.load(owner)
    if not accs:
        return NO_ACCOUNTS, menu("today", owner=owner)
    # показываем аккаунты, а не счета: у одного человека их несколько, и списком
    # вперемешку экран разрастается. Счета — внутри аккаунта
    rows = []
    for cab, info in sorted(accounts.cabinets(owner).items()):
        rows.append([InlineKeyboardButton(
            text=f"{group_bell(info['accounts'])}  {accounts.label(cab, owner)[:26]}",
            callback_data=f"cfg:cab:{cab}")])

    rows.append([InlineKeyboardButton(text="＋ Счёт", callback_data="add"),
                 InlineKeyboardButton(text="📤 Поделиться", callback_data="cfg:share")])
    rows.append([InlineKeyboardButton(text="🔗 Пригласить", callback_data="cfg:inv"),
                 InlineKeyboardButton(text="📋 Мои ссылки", callback_data="cfg:invites")])
    rows.append([InlineKeyboardButton(text="👥 Гости", callback_data="cfg:guests")])
    on = link_alerts_on(db, owner) if db is not None else False
    rows.append([InlineKeyboardButton(
        text=("📡 Связь с MT5: сообщать" if on else "📡 Связь с MT5: молчать"),
        callback_data="cfg:link")])
    rows.append([InlineKeyboardButton(text="↩︎ Назад", callback_data="dash")])
    text = ("⚙︎ <b>Настройки</b>\n" + trades.THIN +
            "\nВыбери аккаунт — внутри его счета.\n"
            "<i>🔔 уведомления идут · 🔕 выключены · 🔔🔕 часть счетов молчит</i>")
    if not is_founder(owner):
        text += "\n\n<i>/stop — отключить бота и стереть свои данные.</i>"
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def cabinet_settings(owner, cabinet: str, db=None) -> tuple[str, InlineKeyboardMarkup]:
    """Счета одного аккаунта: видно, какой молчит, и можно зайти в каждый."""
    accs = accounts.in_cabinet(owner, cabinet)
    if not accs:
        return settings_menu(owner, db)
    rows = [[InlineKeyboardButton(text=f"{bell(a)}  {short_name(a, cabinet)}",
                                  callback_data=f"cfg:acc:{a['name']}")] for a in accs]
    rows.append([InlineKeyboardButton(text="↩︎ Назад", callback_data="cfg")])
    quiet = sum(accounts.silent(a) for a in accs)
    note = (f"Молчат <b>{quiet}</b> из {len(accs)}." if quiet
            else "Уведомления идут по всем счетам.")
    return (f"⚙︎ <b>{html.escape(accounts.label(cabinet, owner))}</b>\n{trades.THIN}\n"
            f"{note}\nВыбери счёт — уведомления, переименование, удаление.",
            InlineKeyboardMarkup(inline_keyboard=rows))


def is_founder(uid) -> bool:
    return bool(FOUNDER) and str(uid) == str(FOUNDER)


def wipe_user(db, uid) -> dict:
    """Стереть все следы пользователя. Возвращает, что удалено.

    Порядок важен: сначала закрываем вход (флаг «ушёл» и отзыв своих ссылок),
    и только потом чистим данные — иначе между удалением и запретом человек
    успел бы зайти снова и остаться с половиной стёртых настроек.
    """
    kv_set(db, f"left:{uid}", "1")          # перекрывает даже список в .env
    kv_del(db, f"guest:{uid}")

    killed = 0
    for token, inv in invite_list(db, uid):
        inv["revoked"] = True               # его ссылки больше никого не впустят
        invite_save(db, token, inv)
        killed += 1

    removed = accounts.purge(uid)
    for pattern in (f"mt5_last_ticket:{uid}:%", f"mt5_fails:{uid}:%",
                    f"term_down:{uid}", f"restart_asked:{uid}",
                    f"guest_name:{uid}", f"guest_by:{uid}", f"guest_since:{uid}"):
        kv_del(db, pattern)
    log.info("пользователь %s отключился: счетов %d, ссылок отозвано %d",
             uid, removed, killed)
    return {"accounts": removed, "invites": killed}


def invite_menu(owner, picked: list[str]) -> tuple[str, InlineKeyboardMarkup]:
    """Выбор счетов, которые получит перешедший по ссылке."""
    rows = [[InlineKeyboardButton(
        text=f"{'☑️' if int(a['login']) in picked else '⬜'} {a['name']}",
        callback_data=f"cfg:invpick:{a['login']}")] for a in accounts.load(owner)]
    rows.append([InlineKeyboardButton(text="🔗 Создать ссылку", callback_data="cfg:invmake")])
    rows.append([InlineKeyboardButton(text="◀️ Отмена", callback_data="cfg")])
    text = ("<b>🔗 Приглашение по ссылке</b>\n" + trades.THIN +
            "\nОдноразовая ссылка на одного человека: кто перейдёт первым, "
            "тот и получит доступ.\n"
            "Отметь счета, которые он увидит, — или создай ссылку без них, "
            "тогда человек просто заведёт свои.\n\n"
            "<i>Счета копируются: у тебя они остаются.</i>")
    text += (f"\n\nВыбрано:\n<b>{html.escape(describe(picked, owner))}</b>" if picked
             else "\n\n<i>Пока без счетов — только доступ к боту.</i>")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def invite_new(db, owner, logins: list, max_uses: int = 1) -> str:
    """Создать приглашение. По умолчанию одноразовое — на одного человека.

    Ссылка сгорает сразу после входа: перешли её дальше или подсмотри в чате —
    второй раз она уже никого не впустит.
    """
    token = secrets.token_urlsafe(9)
    kv_set(db, f"invite:{token}", json.dumps({
        "owner": owner, "logins": [int(x) for x in logins],
        "uses": 0, "max_uses": max_uses,
        "revoked": False, "created": trades.clock().isoformat()}))
    return token


def invite_get(db, token: str, active_only: bool = True) -> dict | None:
    """Приглашение по токену. Отозванное считается несуществующим."""
    if not token or "/" in token or len(token) > 64:    # мусор в кv не ищем
        return None
    raw = kv_get(db, f"invite:{token}")
    try:
        inv = json.loads(raw) if raw else None
    except ValueError:
        log.warning("битое приглашение в базе: %s", token)
        return None
    if inv and active_only and inv.get("revoked"):
        return None
    return inv


def invite_save(db, token: str, inv: dict) -> None:
    kv_set(db, f"invite:{token}", json.dumps(inv))


def invite_check(db, uid, token: str, allowed: set) -> tuple[str, dict | None]:
    """Что делать с переходом по ссылке — решение отдельно от отправки сообщений.

    Возвращает ('bad'|'own'|'known'|'burned'|'ok', запись). Вынесено из
    обработчика, чтобы это можно было проверять тестом: именно здесь решается,
    кого пускать и когда ссылка сгорает.
    """
    inv = invite_get(db, token, active_only=False)
    if not inv:
        return "bad", None
    if str(uid) == str(inv["owner"]):
        return "own", inv
    # ушедший регистрируется заново, поэтому «уже зарегистрирован» — только
    # про действующего пользователя
    if kv_get(db, f"left:{uid}") != "1" and (
            str(uid) in allowed or kv_get(db, f"guest:{uid}") == "1"):
        return "known", inv
    if inv.get("revoked"):
        return "burned", inv
    return "ok", inv


def invite_list(db, owner) -> list[tuple[str, dict]]:
    """Действующие ссылки владельца, новые сверху."""
    out = []
    for key in kv_keys(db, "invite:%"):
        token = key.split(":", 1)[1]
        inv = invite_get(db, token)
        if inv and str(inv["owner"]) == str(owner):
            out.append((token, inv))
    return sorted(out, key=lambda kv: kv[1].get("created", ""), reverse=True)


def invite_link(username: str, token: str) -> str:
    return f"https://t.me/{username}?start={token}"


def by_login(owner, login) -> dict:
    return next((a for a in accounts.load(owner) if int(a["login"]) == int(login)), {})


def invite_logins(inv: dict, owner=None) -> list[int]:
    """Какие счета отдаёт приглашение.

    Храним логины: имя счёта можно переименовать, и выданная раньше ссылка
    указывала бы в пустоту — четыре таких ссылки аудит и нашёл. Старые ссылки
    с именами понимаем на лету, чтобы не ломать уже разосланные.
    """
    if inv.get("logins") is not None:
        return [int(x) for x in inv["logins"]]
    out = []
    for name in inv.get("accounts") or []:
        acc = accounts.by_name(name, owner if owner is not None else inv["owner"])
        if acc:
            out.append(int(acc["login"]))
    return out


def describe(logins: list, owner) -> str:
    """Что отдаёт ссылка: владелец один раз, его стратегии через запятую.

    Счета названы по владельцу, поэтому простой их список повторял бы одно имя
    столько раз, сколько у человека счетов.
    """
    groups: dict[str, list[str]] = {}
    for login in logins:
        acc = by_login(owner, login)
        holder = acc.get("holder") or str(login)
        groups.setdefault(holder, []).append(acc.get("strategy") or str(login))
    return "\n".join(f"{h}: {', '.join(s)}" for h, s in groups.items())


def link_buttons(link: str, inline_ok: bool) -> list[InlineKeyboardButton]:
    """Копировать и переслать. Обе — родные средства Telegram, без ботовской возни.

    Кнопка пересылки работает только при включённом инлайн-режиме (BotFather,
    /setinline). Если он выключен, кнопка молча ничего не сделает — поэтому
    показываем её лишь когда она действительно работает.
    """
    row = [InlineKeyboardButton(text="📋 Копировать", copy_text=CopyTextButton(text=link))]
    if inline_ok:
        row.append(InlineKeyboardButton(text="↗️ Переслать", switch_inline_query=link))
    return row


def guests_view(db, owner) -> tuple[str, InlineKeyboardMarkup]:
    """Кого пустил владелец ссылок: когда зашли и кнопка убрать доступ."""
    rows, lines = [], []
    for key in kv_keys(db, "guest:%"):
        uid = key.split(":", 1)[1]
        if kv_get(db, key) != "1" or str(kv_get(db, f"guest_by:{uid}")) != str(owner):
            continue
        who = kv_get(db, f"guest_name:{uid}") or uid
        since = when_joined(db, uid)
        mine = len(accounts.load(uid))
        lines.append(f"<b>{html.escape(who)}</b> · счетов {mine}"
                     + (f"\n<i>зашёл {since}</i>" if since else ""))
        rows.append([InlineKeyboardButton(text=f"👤 {who[:24]}",
                                          callback_data=f"cfg:guest:{uid}")])
    rows.append([InlineKeyboardButton(text="↩︎ Назад", callback_data="cfg")])
    body = trades.quote(lines) if lines else "<i>По твоим ссылкам пока никто не заходил.</i>"
    return (f"👥 <b>Гости</b>\n{trades.THIN}\n{body}\n\n"
            f"<i>Убрать — закрыть доступ и стереть копии счетов у человека. "
            f"Вернуться он сможет только по новому приглашению.</i>",
            InlineKeyboardMarkup(inline_keyboard=rows))


def when_joined(db, uid) -> str:
    """Когда гость зашёл — с датой и временем: «17.08.2026 в 21:04»."""
    raw = kv_get(db, f"guest_since:{uid}") or ""
    try:
        d = trades.local(datetime.fromisoformat(raw))    # в базе UTC, показываем местное
    except ValueError:
        return raw[:10]
    return f"{d:%d.%m.%Y} в {d:%H:%M}"


def guest_view(db, owner, uid) -> tuple[str, InlineKeyboardMarkup]:
    """Карточка гостя: какие мои счета у него и что с ними можно сделать."""
    who = kv_get(db, f"guest_name:{uid}") or str(uid)
    since = when_joined(db, uid)

    # у гостя копии — сопоставляем по номеру счёта: имя копии он мог сменить
    mine = {int(a["login"]): a for a in accounts.load(owner)}
    his = [a for a in accounts.load(uid) if int(a["login"]) in mine]

    # группируем по владельцу: забрать можно как одну стратегию, так и весь
    # аккаунт человека целиком — по одному счёту это было бы муторно
    by_holder: dict = {}
    for a in his:
        src = mine[int(a["login"])]
        by_holder.setdefault(src.get("holder") or src["name"], []).append(src)

    rows, lines = [], []
    for holder, accs in by_holder.items():
        names = ", ".join(s.get("strategy") or s["name"] for s in accs)
        lines.append(f"👤 <b>{html.escape(holder)}</b>\n<i>{html.escape(names)}</i>")
        for src in accs:
            label = src.get("strategy") or src["name"]
            # владельца в подпись обязательно: стратегии у разных людей
            # называются одинаково, и кнопки «SONIC» были бы неразличимы
            rows.append([InlineKeyboardButton(
                text=f"↩︎ {label[:16]} · {holder.split()[0][:12]}",
                callback_data=f"cfg:take:{uid}:{src['login']}")])
        if len(accs) > 1:       # весь аккаунт разом — когда стратегий несколько
            rows.append([InlineKeyboardButton(
                text=f"↩︎↩︎ Весь {holder[:18]} ({len(accs)})",
                callback_data=f"cfg:takeall:{uid}:{accs[0]['cabinet'] or accounts.NO_CABINET}")])
    body = "\n\n".join(lines) if lines else "<i>Моих счетов у него нет.</i>"

    # его собственные счета — только названия, для понимания картины. Ни цифр,
    # ни кнопок: это чужие деньги, мы к ним отношения не имеем
    his_own = [a for a in accounts.load(uid) if int(a["login"]) not in mine]
    if his_own:
        own = ", ".join(html.escape(a.get("strategy") or a["name"]) for a in his_own)
        body += (f"\n\n<b>Свои счета гостя</b> <i>({len(his_own)})</i>\n"
                 f"<blockquote>{own}\n"
                 f"<i>только названия — доступа к ним нет</i></blockquote>")

    rows.append([InlineKeyboardButton(text="🚪 Убрать доступ совсем",
                                      callback_data=f"cfg:guestkill:{uid}")])
    rows.append([InlineKeyboardButton(text="↩︎ Назад", callback_data="cfg:guests")])
    return (f"👤 <b>{html.escape(str(who))}</b>\n{trades.THIN}\n"
            f"{body}\n"
            + (f"<i>зашёл {since}</i>\n" if since else "")
            + "\n<i>«Забрать» удалит счёт у него, у тебя он останется. "
              "«Убрать доступ» закроет вход и сотрёт все копии.</i>",
            InlineKeyboardMarkup(inline_keyboard=rows))


def invites_view(db, owner, username: str = "", inline_ok: bool = False
                 ) -> tuple[str, InlineKeyboardMarkup]:
    """Список своих ссылок: что отдаёт, копирование, пересылка, отзыв."""
    items = invite_list(db, owner)
    rows, lines = [], []
    for token, inv in items:
        picked = invite_logins(inv, owner)
        what = describe(picked, owner) if picked else "без счетов"
        link = invite_link(username, token)
        lines.append(f"<code>{link}</code>\n<i>{html.escape(what)}</i>")
        rows.append(link_buttons(link, inline_ok) +
                    [InlineKeyboardButton(text="🚫", callback_data=f"cfg:invkill:{token}")])
    rows.append([InlineKeyboardButton(text="🔗 Новая ссылка", callback_data="cfg:inv")])
    rows.append([InlineKeyboardButton(text="↩︎ Назад", callback_data="cfg")])
    body = "\n\n".join(lines) if lines else "<i>Неиспользованных ссылок нет.</i>"
    return (f"🔗 <b>Мои ссылки</b>\n{trades.THIN}\n{body}\n\n"
            f"<i>Каждая ждёт своего человека и сгорает после его входа. "
            f"🚫 закрывает вход заранее; кто уже зашёл — доступ сохраняет.</i>",
            InlineKeyboardMarkup(inline_keyboard=rows))


def my_guests(db, owner) -> list[tuple[str, str]]:
    """Кого владелец уже пустил по своим ссылкам: (id, как зовут)."""
    out = []
    for key in kv_keys(db, "guest:%"):
        uid = key.split(":", 1)[1]
        if kv_get(db, key) == "1" and str(kv_get(db, f"guest_by:{uid}")) == str(owner):
            out.append((uid, kv_get(db, f"guest_name:{uid}") or uid))
    return sorted(out, key=lambda g: g[1].lower())


def share_menu(owner, picked: list, db=None) -> tuple[str, InlineKeyboardMarkup]:
    rows = [[InlineKeyboardButton(
        text=f"{'☑️' if int(a['login']) in picked else '⬜'} {a['name']}",
        callback_data=f"cfg:pick:{a['login']}")] for a in accounts.load(owner)]

    # получателя выбираем из своих гостей: их Telegram ID уже известен, и
    # переспрашивать его у человека незачем
    guests = my_guests(db, owner) if db is not None else []
    if picked and guests:
        rows.append([InlineKeyboardButton(text="— кому отправить —",
                                          callback_data="cfg:share")])
        rows += [[InlineKeyboardButton(text=f"👤 {name[:26]}",
                                       callback_data=f"cfg:shareto:{uid}")]
                 for uid, name in guests]
    rows.append([InlineKeyboardButton(text="◀️ Отмена", callback_data="cfg")])

    text = ("<b>📤 Поделиться счетами</b>\n" + trades.THIN +
            "\nОтметь счета — и выбери, кому отправить.\n\n"
            "<i>Счета копируются: у тебя они остаются. Получатель сможет смотреть "
            "по ним отчёты и получать уведомления.</i>")
    if picked:
        text += f"\n\nВыбрано:\n<b>{html.escape(describe(picked, owner))}</b>"
        if not guests:
            text += ("\n\n<i>Гостей пока нет — пришли Telegram ID сообщением "
                     "или сперва пригласи человека по ссылке.</i>")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def account_menu(name: str, owner) -> tuple[str, InlineKeyboardMarkup]:
    acc = accounts.by_name(name, owner)
    if not acc:
        return "Счёт не найден.", settings_menu(owner)[1]

    notify = acc.get("notify") or {}
    live = acc.get("enabled", True)         # опрашивается ли счёт вообще
    talks = live and notify.get("all", True)

    # выключатели вложены друг в друга: без опроса MT5 не работает ничего, без
    # общего выключателя не работают отдельные типы. Показываем только то, что
    # сейчас действует — иначе половина кнопок ни на что не влияет
    rows = [[InlineKeyboardButton(text=("🔄 Опрос MT5: вкл" if live else "⏸ Опрос MT5: выкл"),
                                  callback_data=f"cfg:tg:{name}:enabled")]]
    if live:
        rows[0].append(InlineKeyboardButton(
            text=("🔔 Уведомления" if notify.get("all", True) else "🔕 Уведомления"),
            callback_data=f"cfg:tg:{name}:all"))
    if talks:       # типы событий — одним рядом, а не тремя
        rows.append([InlineKeyboardButton(
            text=f"{'✅' if notify.get(k, True) else '❌'} {title}",
            callback_data=f"cfg:tg:{name}:{k}") for k, title in accounts.NOTIFY_KINDS.items()])

    base_txt = (f"💰 Invested {acc['base']:.0f}" if acc.get("base") is not None
                else "💰 Указать Invested")
    rows.append([InlineKeyboardButton(text=base_txt, callback_data=f"cfg:base:{name}"),
                 InlineKeyboardButton(text="✏️ Имя", callback_data=f"cfg:ren:{name}"),
                 InlineKeyboardButton(text="🗑", callback_data=f"cfg:del:{name}")])
    # назад — в свой аккаунт, а не в общий список: оттуда сюда и пришли
    back = acc.get("cabinet") or accounts.NO_CABINET
    rows.append([InlineKeyboardButton(text="↩︎ Назад", callback_data=f"cfg:cab:{back}")])

    if not live:
        tail = "<i>Опрос выключен: бот не читает счёт и ничего по нему не шлёт.</i>"
    elif not talks:
        tail = "<i>Данные обновляются, отчёты работают — только сообщения не приходят.</i>"
    else:
        tail = "Что присылать:"
    cab = f" · {acc['cabinet']}" if acc.get("cabinet") else ""
    strat = f" · {html.escape(acc['strategy'])}" if acc.get("strategy") else ""
    text = (f"⚙︎ <b>{html.escape(name)}</b>\n{trades.THIN}\n"
            f"<blockquote>{acc['login']} · ×{acc['multiplier']:g}{cab}{strat}\n"
            f"{html.escape(acc['server'])}</blockquote>\n{tail}")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


NO_ACCOUNTS = ("👋 <b>TagMarkets</b>\n" + trades.THIN +
               "\nПоказываю сделки и заработок по счетам MT5: сколько принесла "
               "каждая сделка, сколько вышло за день, неделю и месяц.\n\n"
               "<b>Начни с кнопки ＋ Счёт</b> — спрошу номер кабинета, "
               "номер счёта и пароль.\n\n"
               "<i>Хватит investor-пароля: бот только читает, торговать не может. "
               "Чужие счета тебе не видны, твои — никому другому.</i>")


def pick_account(who: str = None, owner=None) -> dict | None:
    accs = accounts.load(owner)
    if not accs:
        return None
    return next((a for a in accs if a["name"] == who), accs[0])


def connect(acc: dict) -> bool:
    try:
        trades.use(acc)
        return True
    except Exception as e:
        log.warning("%s", e)
        return False


def no_mt5(acc: dict) -> str:
    return (f"⚠️ <b>{acc['name']}: терминал не отвечает</b>\n{trades.THIN}\n"
            f"Проверь, что MetaTrader 5 по пути <code>{acc['terminal']}</code> запущен "
            f"и счёт {acc['login']} доступен.")


def build_report(name: str, who: str = None, owner=None) -> str:
    """Шапка со счётом + сводка за период + все сделки этого периода."""
    accs = accounts.load(owner)
    if not accs:
        return NO_ACCOUNTS
    if who == ALL and len(accs) > 1:
        # «все» — это все счета текущего кабинета; если кабинет один, то просто все
        groups = accounts.cabinets(owner)
        only = next(iter(groups)) if len(groups) == 1 else None
        return build_all(name, owner, only)

    acc = pick_account(who, owner)
    if not connect(acc):
        return no_mt5(acc)
    title, since, until, subtitle = period(name)
    cur = trades.currency()
    report = trades.fmt_report(title, trades.fetch(since, until), cur, subtitle, since, until=until,
                               with_deals=True)
    return f"{account_head(acc, cur)}\n\n{report}"


def account_head(acc: dict, cur: str) -> str:
    """Шапка счёта: стратегия крупно, владелец и номер — подписью."""
    title = acc.get("strategy") or acc["name"]
    who = acc.get("holder") or acc.get("cabinet") or ""
    sub = " · ".join(x for x in (html.escape(who), f"<code>{acc['login']}</code>") if x)
    return f"🏷 <b>{html.escape(title)}</b>\n<i>{sub}</i>\n{trades.fmt_head(cur)}"


def short_name(acc: dict, cabinet: str = None) -> str:
    """Как назвать счёт внутри кабинета.

    Счета названы по владельцу, а он уже стоит в заголовке кабинета — повторять
    его в каждой строке незачем. Различает счета стратегия, её и показываем.
    """
    if not cabinet:
        return acc["name"]
    holder = acc.get("holder") or ""
    if acc.get("strategy"):
        return acc["strategy"]
    if holder and acc["name"].startswith(holder):
        return acc["name"][len(holder):].lstrip(" ·") or str(acc["login"])
    return acc["name"]


def build_all(name: str, owner=None, cabinet: str = None) -> str:
    """Сводка по счетам: одного кабинета, если он задан, иначе по всем."""
    title, since, until, subtitle = period(name)
    lines, total_my, total_period, total_ever, cur = [], 0.0, 0.0, 0.0, ""
    total_kept = 0.0        # накопленный профит: лежит на стратегии, не выведен
    # профит — величина «на сейчас». Рядом с прошлой неделей или месяцем он
    # читался бы как профит того периода, чем он не является
    now_view = name == "today"
    scope = accounts.in_cabinet(owner, cabinet) if cabinet else accounts.load(owner)
    for acc in scope:
        label = short_name(acc, cabinet)
        if not connect(acc):
            lines.append(f"<b>{html.escape(label)}</b> · <i>нет связи</i>")
            continue
        cur = trades.currency()
        my = trades.capital()       # реальные деньги, не торговый баланс ×плечо
        kept = trades.retained()    # профит чистыми, который ещё не вывели
        per = trades.net_of_fee(trades.mine(trades.summary(trades.fetch(since, until))["total"]))
        # плюс свёрнутые месяцы: их сделки удалены, остались только суммы —
        # без них «за всё время» обрывалось на текущем месяце
        ever = trades.net_of_fee(trades.mine(
            trades.summary(trades.fetch(datetime(2000, 1, 1), trades.clock()))["total"]
            + trades.archived_before_now()[0]))
        if since <= trades.REPORT_FROM:     # период захватывает архив
            per = ever
        total_my += my
        total_kept += kept
        total_period += per
        total_ever += ever
        mark = "▲" if per > 0 else ("▼" if per < 0 else "•")
        on_top = (f" + {trades.amount(abs(kept))} профит"
                  if now_view and abs(kept) >= 0.01 else "")
        lines.append(f"{mark} <b>{html.escape(label)}</b> · {trades.amount(my)}{on_top}\n"
                     f"<i>период {trades.amount(per, signed=True)} · "
                     f"всего {trades.amount(ever, signed=True)}</i>")

    # помесячная история — в отчёте за всё время: в карточке счёта она есть,
    # а в сводке кабинета обрывалась, хотя данные те же
    months = ""
    if name == "all":
        by_month: dict = {}
        for acc in scope:
            if not connect(acc):
                continue
            for m in trades.monthly(limit=1000):
                got = by_month.setdefault(m["month"], {"net": 0.0, "trades": 0})
                got["net"] += trades.net_of_fee(trades.mine(
                    (m["gross"] or 0.0) + (m["platform"] or 0.0)))
                got["trades"] += m["trades"] or 0
        if len(by_month) > 1:
            now_key = trades.clock().strftime("%Y-%m")
            rows_m = []
            for key in sorted(by_month):
                got = by_month[key]
                # своё имя переменной: title занят заголовком периода, и
                # перезапись превращала «За всё время» в «Август»
                month_name = trades.MONTHS.get(int(key[5:7]), key)
                mark = " <i>(идёт)</i>" if key == now_key else ""
                rows_m.append(f"<b>{trades.amount(got['net'], signed=True)}</b> · "
                              f"{got['trades']} сд · <i>{month_name}</i>{mark}")
            months = "\n\n📦 <b>По месяцам</b>\n" + trades.quote(rows_m)

    where = accounts.label(cabinet, owner) if cabinet else "Все счета"
    # капитал и накопленный профит порознь: профит лежит на стратегии, пока его
    # не вывели, и одной суммой непонятно, сколько из этого заработано
    split = (f"\n<i>капитал {trades.amount(total_my)} · "
             f"профит {trades.amount(total_kept, signed=True)}</i>"
             if now_view and abs(total_kept) >= 0.01 else "")
    on_strategy = total_my + (total_kept if now_view else 0.0)
    head = (f"👤 <b>{html.escape(where)}</b>\n"
            f"💎 <b>{trades.amount(on_strategy, cur)}</b> на стратегии{split}\n"
            f"◆ <i>всего заработано {trades.amount(total_ever, signed=True)}</i>")
    table = trades.quote(lines)
    # пустая суббота — не поломка: рынок закрыт, и «+0.00» без пояснения пугает
    if (not total_period and since.date() == until.date()
            and trades.is_weekend(since)):
        total = trades.WEEKEND
    else:
        total = (f"{'▲' if total_period >= 0 else '▼'} "
                 f"<b>{trades.amount(total_period, cur, signed=True)}</b>")
    return (f"{head}\n\n<b>{title}</b>  <i>{subtitle}</i>\n{trades.THIN}\n"
            f"{total}\n\n{table}{months}")


def parse_date(s: str) -> date:
    for f in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    raise ValueError(s)


# ── партнёрский кабинет ───────────────────────────────────────────────────

async def poll_portal(session, bot: Bot, db, chat_id: str) -> int:
    """Лента событий кабинета IB Portal → Telegram.

    Прежний Syntellicore отключён вместе со старым порталом, и опрашивать лиды
    с депозитами больше негде. Новый кабинет отдаёт готовые события сам, так
    что своя логика не нужна — только пересылка и защита от повторов.
    """
    rows = await ibportal.notifications(session, limit=30)
    fresh, first_run = unseen(db, "portal", rows)
    if first_run:
        log.info("кабинет: запомнил %d событий, слать буду с новых", len(fresh))
        return 0

    sent, income, trades_n = 0, 0.0, 0
    for row in fresh:
        if row.get("eventType") == partner.PORTAL_INCOME:
            # доход с сети капает по копейке — копим на сводку, а не спамим
            income += partner.portal_amount(row)
            trades_n += 1
            continue
        await send(bot, chat_id, partner.fmt_portal(row), DASHBOARD_BTN)
        sent += 1
        await asyncio.sleep(0.05)

    if income:
        day = str(trades.clock().date())
        kv_set(db, f"net_income:{day}",
               f"{float(kv_get(db, f'net_income:{day}', 0) or 0) + income:.6f}")
        kv_set(db, f"net_trades:{day}",
               str(int(kv_get(db, f"net_trades:{day}", 0) or 0) + trades_n))
        log.info("доход с сети: +%.4f за %d сделок сети", income, trades_n)
    return sent


# ── опрос MT5 ─────────────────────────────────────────────────────────────

async def poll_mt5(bot: Bot, db) -> int:
    """Обходит счета всех пользователей: каждому уходят только его сделки."""
    sent = 0
    for acc in accounts.load():
        owner = acc["owner"]
        if not acc.get("enabled", True):
            continue

        # молчащий бот выглядит как «сделок нет» — предупреждаем, если терминал
        # не отвечает долго, но пишем об этом один раз, а не каждый круг
        # ключи по логину, а не по имени: имя счёта можно переименовать, и тогда
        # бот забыл бы, до какой сделки дошёл, и начал отсчёт заново
        fail_key = f"mt5_fails:{owner}:{acc['login']}"
        if not connect(acc):
            fails = int(kv_get(db, fail_key, 0)) + 1
            kv_set(db, fail_key, fails)
            if fails == MT5_ALERT_AFTER:
                try:
                    await send(bot, owner, no_mt5(acc))
                except Exception as e:
                    log.warning("не доставил предупреждение %s: %s", owner, e)
            continue
        if int(kv_get(db, fail_key, 0)) >= MT5_ALERT_AFTER:
            try:
                await send(bot, owner, f"✅ <b>{acc['name']}</b>: связь с терминалом восстановлена.")
            except Exception:
                pass
        kv_set(db, fail_key, 0)

        key = f"mt5_last_ticket:{owner}:{acc['login']}"
        last = int(kv_get(db, key, 0))
        if not last:  # первый запуск — историю не пересылаем
            kv_set(db, key, trades.last_ticket())
            log.info("%s/%s: запомнил историю, уведомления пойдут с новых сделок",
                     owner, acc["name"])
            continue

        cur = trades.currency()
        for row in trades.since_ticket(last):
            # курсор двигаем всегда: выключенный тип уведомлений не должен
            # копиться и вывалиться пачкой, когда его снова включат
            kind = ("deposits" if row["net"] >= 0 else "withdrawals") \
                if row["is_balance"] else "trades"
            if not accounts.notifies(acc, kind):
                kv_set(db, key, row["ticket"])
                continue

            if row["is_opening"]:   # про вход не пишем — интересен результат
                kv_set(db, key, row["ticket"])
                continue

            day_net = day_count = total_net = None
            if row["is_closing"]:
                today = trades.summary(trades.fetch(*day_bounds(trades.clock().date())))
                day_net, day_count = today["total"], today["count"]
                total_net = trades.mine(trades.summary(
                    trades.fetch(datetime(2000, 1, 1), trades.clock()))["total"])

            # шапка: какая стратегия и чей это кабинет — счета у разных
            # владельцев могут называться одинаково, и без этого их не различить
            tag = f"🏷 <b>{html.escape(acc['name'])}</b>"
            who = acc.get("holder") or acc.get("cabinet") or ""
            if who:
                tag += f"\n<i>{html.escape(who)}</i>"
            body = trades.fmt_notification(row, cur, day_net, day_count, total_net)
            if not body:            # форматтер решил, что писать не о чем
                kv_set(db, key, row["ticket"])
                continue
            text = f"{tag}\n{trades.THIN}\n{body}"
            try:
                await send(bot, owner, text, DASHBOARD_BTN)
            except Exception as e:
                log.warning("не доставил уведомление %s: %s", owner, e)
                break
            kv_set(db, key, row["ticket"])
            sent += 1
            await asyncio.sleep(0.05)
    return sent


# ── добавление счёта прямо из чата ────────────────────────────────────────

DEFAULT_SERVER = os.getenv("DEFAULT_SERVER", "TMFinancials-Server")
DEFAULT_MULTIPLIER = float(os.getenv("AMPLIFY_MULTIPLIER", 24))


class SetBase(StatesGroup):
    amount = State()


class AddAcc(StatesGroup):
    cabinet = State()
    holder = State()
    name = State()
    login = State()
    password = State()
    server = State()


class Rename(StatesGroup):
    name = State()


class Share(StatesGroup):
    target = State()


class Invite(StatesGroup):
    pick = State()


CANCEL = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Отмена", callback_data="cancel")]])

SERVER_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=DEFAULT_SERVER, callback_data="server:default")],
    [InlineKeyboardButton(text="Отмена", callback_data="cancel")]])


async def finish_add(bot: Bot, chat_id, owner, data: dict) -> str:
    """Сохраняет счёт и проверяет, что в него удаётся войти."""
    acc = {"owner": owner, "cabinet": data.get("cabinet", ""), "holder": data.get("holder", ""),
           "name": data["name"], "login": int(data["login"]),
           "password": data["password"], "server": data["server"],
           "terminal": trades.TERMINAL, "multiplier": DEFAULT_MULTIPLIER}
    try:
        accounts.add(acc)
    except ValueError as e:
        return f"❌ {html.escape(str(e))}"

    await bot.send_message(chat_id, "🔑 Проверяю вход в счёт…")
    ok = await asyncio.to_thread(connect, acc)
    if not ok:
        accounts.remove(acc["name"], owner)
        return ("❌ Войти не удалось — счёт удалён из настроек.\n"
                "Проверь номер счёта, пароль и имя сервера и попробуй снова.")

    a = trades.account()
    if not acc["holder"] and getattr(a, "name", ""):
        # имя владельца берём из профиля MT5-счёта — спрашивать не нужно
        accounts.update(acc["name"], owner, holder=a.name)
    my = trades.capital()       # реальные деньги, не торговый баланс ×плечо
    return (f"✅ <b>Счёт {acc['name']} добавлен</b>\n{trades.THIN}\n"
            f"Номер <b>{a.login}</b>\n"
            f"Мои деньги <b>{my:.2f} {a.currency}</b>\n"
            f"<i>{a.server}</i>\n\nУведомления по нему пойдут с ближайшей сделки.")


# ── запуск ────────────────────────────────────────────────────────────────

WELCOME = (
    "<b>👋 Бот TagMarkets</b>\n" + trades.THIN + "\n"
    "Присылаю каждую сделку по счёту MT5 и события партнёрского кабинета, "
    "и показываю отчёты за любой период.\n\n"
    "<b>Отчёты — кнопками ниже</b>, либо командами:\n"
    "/today · /yesterday · /week · /month · /all\n\n"
    "<b>Другое:</b>\n"
    "/status — мои вложения и открытые позиции\n"
    "/day 05.08.2026 — за конкретный день\n"
    "/since 22.07.2026 — с даты по сегодня\n"
    "/period 01.08.2026 11.08.2026 — свой диапазон\n"
    "/check — проверить партнёрский API сейчас\n\n"
    "<i>Главная цифра в отчёте — заработок только за счёт сделок, "
    "с учётом свопов, комиссий и платы платформы. Пополнения в неё не входят — "
    "они показаны отдельно в блоке «Баланс счёта».</i>"
)


def hide(proxy: str) -> str:
    """Прокси без логина и пароля — такое не стыдно писать в лог."""
    return proxy.split("@")[-1] if proxy else "напрямую"


async def works(token: str, proxy: str) -> bool:
    """Отвечает ли Telegram через этот прокси."""
    probe = Bot(token, session=AiohttpSession(proxy=proxy) if proxy else None)
    try:
        await probe.me()
        return True
    except Exception as e:
        log.warning("прокси %s не годится: %s", hide(proxy), e)
        return False
    finally:
        await probe.session.close()


async def pick_proxy(token: str, setting: str) -> str | None:
    """Первый прокси из списка, через который Telegram отвечает.

    Прокси отваливаются молча — служба остаётся «активной», а бот при этом
    глухой. Поэтому проверяем связь до запуска и берём рабочий.
    """
    options = [p.strip() for p in setting.split(",") if p.strip()] or [""]
    for proxy in options:
        if await works(token, proxy):
            log.info("Telegram через %s", hide(proxy))
            return proxy or None
    log.error("ни один прокси не отвечает (%d шт.) — работаю вслепую, "
              "перезапущусь, когда появится связь", len(options))
    return options[0] or None


async def main():
    token, chat_id = os.environ["TELEGRAM_BOT_TOKEN"], os.getenv("TELEGRAM_CHAT_ID", "")

    # Telegram недоступен из некоторых сетей (например, с серверов в России) —
    # тогда весь его трафик пускаем через прокси: TELEGRAM_PROXY в .env,
    # вида socks5://user:pass@host:port. Можно перечислить несколько через
    # запятую: прокси умирают молча, и один запасной спасает бота от простоя
    proxy = await pick_proxy(token, os.getenv("TELEGRAM_PROXY", ""))
    session = AiohttpSession(proxy=proxy) if proxy else None
    bot = Bot(token, session=session,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    db = open_db()

    # доступ открыт всем: у каждого свои счета, чужих он не видит.
    # ALLOWED_USERS в .env оставляет бота личным, если однажды понадобится.
    allowed = {x.strip() for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()}

    def invite_token(event) -> str:
        """Токен из ссылки t.me/бот?start=ТОКЕН, если это она."""
        msg = getattr(event, "message", None)
        text = getattr(msg, "text", "") or ""
        parts = text.split(maxsplit=1)
        return parts[1].strip() if len(parts) == 2 and parts[0] in ("/start", "/help") else ""

    @dp.update.outer_middleware()
    async def only_allowed(handler, event, data):
        user = data.get("event_from_user")
        uid = str(getattr(user, "id", ""))
        token = invite_token(event)
        # ушедший заходит только по новому приглашению — флаг «left» сильнее
        # списка в .env, иначе команда отключения не работала бы для своих
        if kv_get(db, f"left:{uid}") == "1" and not (token and invite_get(db, token)):
            return
        # гость по ссылке проходит наравне со списком в .env: сам переход по
        # приглашению и есть выдача доступа, иначе первое же /start отбилось бы
        ok = (not allowed or uid in allowed or kv_get(db, f"guest:{uid}") == "1"
              or (token and invite_get(db, token)))
        if not ok:
            log.warning("отклонён запрос: id=%s (%s)",
                        getattr(user, "id", "?"), getattr(user, "username", ""))
            return
        return await handler(event, data)

    async def swap(cb: CallbackQuery, text: str, markup):
        """Меняем сообщение на месте, чтобы чат не засорялся."""
        try:
            await cb.message.edit_text(text[:TG_LIMIT], reply_markup=markup)
        except TelegramBadRequest:
            pass  # текст не изменился — Telegram ругается, это нормально

    @dp.message(Command("start", "help"))
    async def start(msg: Message, command: CommandObject = None):
        token = (command.args or "").strip() if command else ""
        if token:
            await accept_invite(msg, token)
        text, kb = dashboard(msg.from_user.id)
        await send(bot, msg.chat.id, text, kb)

    async def accept_invite(msg: Message, token: str) -> None:
        """Принять приглашение: открыть доступ и скопировать счета из ссылки."""
        uid = msg.from_user.id
        verdict, inv = invite_check(db, uid, token, allowed)
        if verdict == "own":
            return                          # это своя же ссылка — просто открыть бота
        if verdict == "bad":
            await send(bot, msg.chat.id, "🔗 Ссылка недействительна.")
            return
        if verdict == "known":
            # ссылку не тратим: она ждёт незарегистрированного человека
            mine = len(accounts.load(uid))
            await send(bot, msg.chat.id,
                       "👌 <b>Ты уже зарегистрирован</b>\n" + trades.THIN +
                       "\nПовторная регистрация не нужна: доступ у тебя есть, "
                       + (f"счета на месте (их {mine}). " if mine else "") +
                       "Ничего нового по этой ссылке не добавлено.")
            return
        if verdict == "burned":
            await send(bot, msg.chat.id,
                       "🔗 <b>Ссылка уже использована</b>\n" + trades.THIN +
                       "\nПриглашение одноразовое и рассчитано на одного человека. "
                       "Попроси новое.")
            return

        who = msg.from_user.username or msg.from_user.full_name or str(uid)
        kv_set(db, f"guest:{uid}", "1")
        kv_del(db, f"left:{uid}")           # вернулся по приглашению — доступ открыт
        # запоминаем, кто и от кого — иначе в «Гостях» будут одни номера
        kv_set(db, f"guest_name:{uid}", who)
        kv_set(db, f"guest_by:{uid}", inv["owner"])
        kv_set(db, f"guest_since:{uid}", trades.clock().isoformat())
        inv["uses"] = inv.get("uses", 0) + 1
        if inv["uses"] >= inv.get("max_uses", 1):
            inv["revoked"] = True           # одноразовая: сгорает сразу после входа
        invite_save(db, token, inv)

        wanted = invite_logins(inv)
        added = accounts.share(wanted, inv["owner"], uid) if wanted else []

        what = ("Доступны счета: <b>" + html.escape(", ".join(added)) + "</b>" if added
                else "Счета пока не добавлены — заведи свой в настройках.")
        await send(bot, msg.chat.id, f"✅ <b>Приглашение принято</b>\n{trades.THIN}\n{what}")

        # ссылка сгорела — сразу выпускаем следующую с теми же счетами, чтобы
        # приглашать дальше можно было не заходя в настройки
        nxt = invite_new(db, inv["owner"], wanted)
        link = f"https://t.me/{(await bot.me()).username}?start={nxt}"

        try:    # хозяин ссылки должен знать, кто ею воспользовался
            await send(bot, inv["owner"],
                       f"🔗 <b>По твоей ссылке зашёл</b> {html.escape(str(who))}\n"
                       + (f"Получил счета:\n{html.escape(describe(added, uid))}" if added
                          else "Без счетов — только доступ к боту.")
                       + f"\n{trades.THIN}\nСсылка использована. Новая готова:\n"
                         f"<code>{link}</code>")
        except Exception as e:
            log.warning("не уведомил владельца ссылки: %s", e)

    @dp.callback_query(F.data.startswith("restart:"))
    async def restart_terminal(cb: CallbackQuery):
        login = int(cb.data.split(":", 1)[1])
        acc = next((a for a in accounts.load(cb.from_user.id)
                    if int(a["login"]) == login), None)
        if not acc:
            await cb.answer("Счёт не найден", show_alert=True)
            return
        await cb.answer("Отправляю команду…")
        # проверяем, выходил ли агент на связь недавно — иначе команду принять некому
        import store as _store
        st = _store.get_state(_store.open_db(), login)
        fresh = st and st.get("synced") and \
            (utcnow() - datetime.fromisoformat(st["synced"])).total_seconds() < TERMINAL_STALE
        _store.set_command(_store.open_db(), login, "restart_terminal")
        # флаг по владельцу: вотчдог следит за кабинетом целиком, а не за счётом
        kv_set(db, f"restart_asked:{acc['owner']}", "1")
        if fresh:
            msg = ("🔄 Команда отправлена. Агент на связи — терминал перезапустится "
                   "в течение ~20 секунд, после чего придёт «Связь восстановлена».")
        else:
            msg = ("🔄 Команда поставлена в очередь.\n\n<b>Но агент сейчас не на связи</b> — "
                   "значит выключен ПК или остановлен сам агент, и принять команду некому.\n"
                   "• Если ПК <b>выключен</b> — включи его, всё поднимется само.\n"
                   "• Если ПК <b>включён</b> — агент перезапустится сторожем в течение "
                   "2–3 минут, либо запусти его в пульте <code>TagMarkets.bat</code>.")
        await cb.message.answer(msg)

    @dp.callback_query(F.data == "dash")
    async def dash_cb(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        await state.clear()
        text, kb = dashboard(cb.from_user.id)
        await swap(cb, text, kb)

    @dp.callback_query(F.data.startswith("cab:") & ~F.data.regexp(r"^cab:[^:]+$"))
    async def cabinet_cb(cb: CallbackQuery):
        await cb.answer()
        _, cabinet, per = cb.data.split(":", 2)
        text, kb = cabinet_view(cb.from_user.id, cabinet, per)
        await swap(cb, text, kb)

    @dp.callback_query(F.data.startswith("acc:"))
    async def account_cb(cb: CallbackQuery):
        await cb.answer()
        _, login, per = cb.data.split(":", 2)
        text, kb = account_view(cb.from_user.id, int(login), per)
        await swap(cb, text, kb)

    @dp.message(Command("today", "yesterday", "week", "lastweek", "month", "all"))
    async def report_cmd(msg: Message, command: CommandObject):
        me = msg.from_user.id
        who = (command.args or "").strip() or None
        await send(bot, msg.chat.id, build_report(command.command, who, me),
                   menu(command.command, who, me))

    @dp.callback_query(F.data.startswith("rep:"))
    async def report_button(cb: CallbackQuery):
        await cb.answer()
        me = cb.from_user.id
        parts = cb.data.split(":")
        name = parts[1]
        who = parts[2] if len(parts) > 2 else None
        await swap(cb, build_report(name, who, me), menu(name, who, me))

    def ranged(title: str, a: datetime, b: datetime, subtitle: str,
               who: str = None, owner=None) -> str:
        """Отчёт за произвольный отрезок для выбранного счёта."""
        acc = pick_account(who, owner)
        if not acc:
            return NO_ACCOUNTS
        if not connect(acc):
            return no_mt5(acc)
        report = trades.fmt_report(title, trades.fetch(a, b), trades.currency(), subtitle, a, until=b,
                                   with_deals=True)
        return f"🏷 <b>{acc['name']}</b>\n{trades.fmt_head(trades.currency())}\n\n{report}"

    @dp.callback_query(F.data == "cfg")
    async def cfg_root(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        await state.clear()
        text, kb = settings_menu(cb.from_user.id, db)
        await swap(cb, text, kb)

    @dp.callback_query(F.data.startswith("cfg:cab:"))
    async def cfg_cabinet(cb: CallbackQuery):
        await cb.answer()
        await swap(cb, *cabinet_settings(cb.from_user.id, cb.data.split(":", 2)[2], db))

    @dp.callback_query(F.data.startswith("cfg:acc:"))
    async def cfg_account(cb: CallbackQuery):
        await cb.answer()
        text, kb = account_menu(cb.data.split(":", 2)[2], cb.from_user.id)
        await swap(cb, text, kb)

    @dp.callback_query(F.data.startswith("cfg:tg:"))
    async def cfg_toggle(cb: CallbackQuery):
        _, _, name, kind = cb.data.split(":", 3)
        try:
            value = accounts.toggle(name, cb.from_user.id, kind)
        except ValueError as e:
            await cb.answer(str(e), show_alert=True)
            return
        await cb.answer("включено" if value else "выключено")
        text, kb = account_menu(name, cb.from_user.id)
        await swap(cb, text, kb)

    @dp.callback_query(F.data.startswith("cfg:del:"))
    async def cfg_delete_ask(cb: CallbackQuery):
        await cb.answer()
        name = cb.data.split(":", 2)[2]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"cfg:delyes:{name}")],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cfg:acc:{name}")]])
        await swap(cb, f"Удалить счёт <b>{html.escape(name)}</b>?\n\n"
                       f"<i>Сам торговый счёт у брокера не пострадает — "
                       f"бот просто перестанет его показывать.</i>", kb)

    @dp.callback_query(F.data.startswith("cfg:delyes:"))
    async def cfg_delete(cb: CallbackQuery):
        name = cb.data.split(":", 2)[2]
        ok = accounts.remove(name, cb.from_user.id)
        await cb.answer("удалён" if ok else "не найден")
        text, kb = settings_menu(cb.from_user.id, db)
        await swap(cb, text, kb)

    @dp.callback_query(F.data.startswith("cfg:base:"))
    async def cfg_base_ask(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        name = cb.data.split(":", 2)[2]
        await state.set_state(SetBase.amount)
        await state.update_data(name=name)
        await cb.message.answer(
            f"💰 <b>{html.escape(name)}</b>\n{trades.THIN}\n"
            f"Впиши <b>Invested</b> с карточки стратегии в портале — "
            f"это твой чистый вложенный капитал. Например <code>2500</code>\n\n"
            f"<i>С ним бот посчитает деньги точно: капитал плюс удержанная прибыль "
            f"(её на плечо не делит). Без него — приблизительно.</i>", reply_markup=CANCEL)

    @dp.message(SetBase.amount)
    async def cfg_base_set(msg: Message, state: FSMContext):
        name = (await state.get_data()).get("name")
        await state.clear()
        try:
            amount = float(msg.text.strip().replace(",", ".").replace("$", "").strip())
        except ValueError:
            await msg.answer("Нужно число, например <code>2470</code>. Попробуй ещё раз.")
            return

        me = msg.from_user.id
        data = accounts._read()
        for a in data:
            if a["name"] == name and str(a["owner"]) == str(me):
                a["base"] = amount
                a["base_at"] = trades.clock().isoformat()
                break
        accounts.save(data)
        acc = accounts.by_name(name, me)
        text, kb = account_menu(name, me)
        await send(bot, msg.chat.id,
                   f"✅ Записал: <b>{amount:.2f}</b> на {trades.clock():%d.%m %H:%M}.\n"
                   f"Дальше буду прибавлять к этой сумме результат сделок.", kb)

    @dp.callback_query(F.data.startswith("cfg:ren:"))
    async def cfg_rename_ask(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        name = cb.data.split(":", 2)[2]
        acc = accounts.by_name(name, cb.from_user.id) or {}
        await state.set_state(Rename.name)
        await state.update_data(old=name)
        now = acc.get("strategy") or name
        await cb.message.answer(
            f"Новое название стратегии <b>{html.escape(now)}</b>?\n"
            f"<i>Владелец счёта останется прежним.</i>", reply_markup=CANCEL)

    @dp.message(Rename.name)
    async def cfg_rename(msg: Message, state: FSMContext):
        old = (await state.get_data()).get("old")
        await state.clear()
        try:
            new_name = accounts.rename(old, msg.from_user.id, msg.text)
        except ValueError as e:
            await msg.answer(f"❌ {html.escape(str(e))}")
            return
        text, kb = settings_menu(msg.from_user.id, db)
        await send(bot, msg.chat.id,
                   f"✅ Стратегия теперь <b>{html.escape(msg.text.strip())}</b>\n"
                   f"<i>Счёт: {html.escape(new_name)}</i>")
        await send(bot, msg.chat.id, text, kb)

    @dp.message(Command("stop", "leave"))
    async def stop_ask(msg: Message):
        uid = msg.from_user.id
        if is_founder(uid):
            await send(bot, msg.chat.id,
                       "🛡 <b>Основателю нельзя отключить бота</b>\n" + trades.THIN +
                       "\nЭто твой бот: на нём держатся счета, приглашения и "
                       "уведомления остальных. Отключение недоступно даже с "
                       "подтверждением.")
            return
        accs = accounts.load(uid)
        links = len(invite_list(db, uid))
        what = [f"счетов: <b>{len(accs)}</b>"] if accs else []
        if links:
            what.append(f"ссылок будет отозвано: <b>{links}</b>")
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗑 Да, отключить и стереть",
                                 callback_data="quit:yes"),
            InlineKeyboardButton(text="Отмена", callback_data="quit:no")]])
        await send(bot, msg.chat.id,
                   "⚠️ <b>Отключить бота на этом аккаунте?</b>\n" + trades.THIN +
                   ("\n" + " · ".join(what) + "\n" if what else "\n") +
                   "\nБудут стёрты все твои счета, настройки уведомлений и "
                   "история отслеживания. Уведомления перестанут приходить.\n\n"
                   "<i>Вернуться можно будет только по новому приглашению.</i>", kb)

    @dp.callback_query(F.data.startswith("quit:"))
    async def stop_confirm(cb: CallbackQuery):
        if cb.data == "quit:no":
            await cb.answer("Отменено")
            await swap(cb, "Отключение отменено — всё осталось как было.", None)
            return
        uid = cb.from_user.id
        if is_founder(uid):     # защита и здесь: кнопка могла остаться в старом чате
            await cb.answer("Основателю нельзя отключить бота", show_alert=True)
            return
        await cb.answer()
        gone = wipe_user(db, uid)
        await swap(cb, "👋 <b>Бот отключён</b>\n" + trades.THIN +
                       f"\nУдалено счетов: <b>{gone['accounts']}</b>. "
                       f"Данные стёрты, уведомления больше не придут.\n\n"
                       f"<i>Чтобы вернуться, попроси новое приглашение.</i>", None)
        if FOUNDER:     # основателю полезно знать, что кто-то ушёл
            who = cb.from_user.username or cb.from_user.full_name or uid
            try:
                await send(bot, int(FOUNDER),
                           f"👋 <b>{html.escape(str(who))}</b> отключил бота у себя "
                           f"(счетов удалено {gone['accounts']}).")
            except Exception as e:
                log.warning("не уведомил основателя об уходе: %s", e)

    @dp.callback_query(F.data == "cfg:link")
    async def cfg_link_alerts(cb: CallbackQuery):
        now_on = not link_alerts_on(db, cb.from_user.id)
        kv_set(db, f"link_alerts:{cb.from_user.id}", "1" if now_on else "0")
        await cb.answer("Буду сообщать о связи" if now_on else "Про связь молчу")
        await swap(cb, *settings_menu(cb.from_user.id, db))

    @dp.callback_query(F.data == "cfg:guests")
    async def cfg_guests(cb: CallbackQuery):
        await cb.answer()
        await swap(cb, *guests_view(db, cb.from_user.id))

    @dp.callback_query(F.data.startswith("cfg:guest:"))
    async def cfg_guest_card(cb: CallbackQuery):
        uid = cb.data.split(":", 2)[2]
        if str(kv_get(db, f"guest_by:{uid}")) != str(cb.from_user.id):
            await cb.answer("Это не твой гость", show_alert=True)
            return
        await cb.answer()
        await swap(cb, *guest_view(db, cb.from_user.id, uid))

    @dp.callback_query(F.data.startswith("cfg:take:"))
    async def cfg_take_back(cb: CallbackQuery):
        _, _, uid, login = cb.data.split(":", 3)
        if str(kv_get(db, f"guest_by:{uid}")) != str(cb.from_user.id):
            await cb.answer("Это не твой гость", show_alert=True)
            return
        # проверяем, что счёт действительно наш — чужой забрать нельзя
        if not any(int(a["login"]) == int(login) for a in accounts.load(cb.from_user.id)):
            await cb.answer("Этот счёт не твой", show_alert=True)
            return
        gone = accounts.remove_login(login, uid)
        await cb.answer(f"Забрал: {gone}" if gone else "У него уже нет этого счёта")
        if gone:
            log.info("владелец %s забрал счёт %s у гостя %s", cb.from_user.id, login, uid)
            try:    # человек не должен гадать, куда делся счёт
                await send(bot, int(uid),
                           f"↩︎ <b>Счёт больше не доступен</b>\n{trades.THIN}\n"
                           f"{html.escape(gone)}\n"
                           f"<i>Владелец забрал его обратно.</i>")
            except Exception as e:
                log.warning("не уведомил гостя %s: %s", uid, e)
        await swap(cb, *guest_view(db, cb.from_user.id, uid))

    @dp.callback_query(F.data.startswith("cfg:takeall:"))
    async def cfg_take_cabinet(cb: CallbackQuery):
        _, _, uid, cabinet = cb.data.split(":", 3)
        if str(kv_get(db, f"guest_by:{uid}")) != str(cb.from_user.id):
            await cb.answer("Это не твой гость", show_alert=True)
            return
        # забираем все счета этого владельца — только те, что мои
        logins = [int(a["login"]) for a in accounts.in_cabinet(cb.from_user.id, cabinet)]
        gone = [name for login in logins if (name := accounts.remove_login(login, uid))]
        await cb.answer(f"Забрано счетов: {len(gone)}" if gone else "Забирать нечего")
        if gone:
            log.info("владелец %s забрал аккаунт %s (%d счетов) у гостя %s",
                     cb.from_user.id, cabinet, len(gone), uid)
            try:
                await send(bot, int(uid),
                           f"↩︎ <b>Счета больше не доступны</b>\n{trades.THIN}\n"
                           f"{html.escape(', '.join(gone))}\n"
                           f"<i>Владелец забрал их обратно.</i>")
            except Exception as e:
                log.warning("не уведомил гостя %s: %s", uid, e)
        await swap(cb, *guest_view(db, cb.from_user.id, uid))

    @dp.callback_query(F.data.startswith("cfg:guestkill:"))
    async def cfg_guest_kill(cb: CallbackQuery):
        uid = cb.data.split(":", 2)[2]
        if str(kv_get(db, f"guest_by:{uid}")) != str(cb.from_user.id):
            await cb.answer("Это не твой гость", show_alert=True)   # чужих не трогаем
            return
        who = kv_get(db, f"guest_name:{uid}") or uid
        gone = wipe_user(db, uid)
        await cb.answer(f"{who}: доступ закрыт")
        try:    # человек должен понимать, почему бот замолчал
            await send(bot, int(uid),
                       "🚪 <b>Доступ к боту закрыт</b>\n" + trades.THIN +
                       "\nВладелец счетов убрал тебя. Данные и копии счетов стёрты.\n"
                       "<i>Вернуться можно по новому приглашению.</i>")
        except Exception as e:
            log.warning("не уведомил гостя %s об отключении: %s", uid, e)
        log.info("гость %s убран владельцем %s (счетов %d)", uid, cb.from_user.id,
                 gone["accounts"])
        await swap(cb, *guests_view(db, cb.from_user.id))

    @dp.callback_query(F.data == "cfg:invites")
    async def cfg_invites(cb: CallbackQuery):
        await cb.answer()
        me = await bot.me()
        await swap(cb, *invites_view(db, cb.from_user.id, me.username,
                                     me.supports_inline_queries))

    @dp.callback_query(F.data.startswith("cfg:invkill:"))
    async def cfg_invite_kill(cb: CallbackQuery):
        token = cb.data.split(":", 2)[2]
        inv = invite_get(db, token)
        if not inv or str(inv["owner"]) != str(cb.from_user.id):
            await cb.answer("Ссылка не найдена", show_alert=True)
            return
        inv["revoked"] = True
        invite_save(db, token, inv)
        await cb.answer("Ссылка отозвана")
        me = await bot.me()
        await swap(cb, *invites_view(db, cb.from_user.id, me.username,
                                     me.supports_inline_queries))

    @dp.callback_query(F.data == "cfg:inv")
    async def cfg_invite_ask(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        await state.set_state(Invite.pick)
        await state.update_data(picked=[])
        await swap(cb, *invite_menu(cb.from_user.id, []))

    @dp.callback_query(F.data.startswith("cfg:invpick:"), Invite.pick)
    async def cfg_invite_pick(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        login = int(cb.data.split(":", 2)[2])
        picked = (await state.get_data()).get("picked", [])
        picked = [p for p in picked if p != login] if login in picked else picked + [login]
        await state.update_data(picked=picked)
        await swap(cb, *invite_menu(cb.from_user.id, picked))

    @dp.callback_query(F.data == "cfg:invmake", Invite.pick)
    async def cfg_invite_make(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        picked = (await state.get_data()).get("picked", [])
        await state.clear()
        token = invite_new(db, cb.from_user.id, picked)
        me = await bot.me()
        link = invite_link(me.username, token)
        what = (f"Со счетами:\n<b>{html.escape(describe(picked, cb.from_user.id))}</b>" if picked
                else "Без счетов — только доступ к боту.")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            link_buttons(link, me.supports_inline_queries),
            [InlineKeyboardButton(text="📋 Мои ссылки", callback_data="cfg:invites"),
             InlineKeyboardButton(text="↩︎ Назад", callback_data="cfg")]])
        await swap(cb, f"🔗 <b>Ссылка готова</b>\n{trades.THIN}\n{what}\n\n"
                       f"<code>{link}</code>\n\n"
                       f"<i>Одноразовая — на одного человека. Как только по ней зайдут, "
                       f"я сообщу и сразу пришлю новую.</i>", kb)

    @dp.callback_query(F.data == "cfg:share")
    async def cfg_share_ask(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        accs = accounts.load(cb.from_user.id)
        if not accs:
            await cb.message.answer("Пока нечем делиться — счетов нет.")
            return
        await state.set_state(Share.target)
        await state.update_data(picked=[])
        text, kb = share_menu(cb.from_user.id, [], db)
        await swap(cb, text, kb)

    @dp.callback_query(F.data.startswith("cfg:pick:"), Share.target)
    async def cfg_share_pick(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        login = int(cb.data.split(":", 2)[2])
        picked = (await state.get_data()).get("picked", [])
        picked = [p for p in picked if p != login] if login in picked else picked + [login]
        await state.update_data(picked=picked)
        text, kb = share_menu(cb.from_user.id, picked, db)
        await swap(cb, text, kb)

    @dp.callback_query(F.data.startswith("cfg:shareto:"), Share.target)
    async def cfg_share_to_guest(cb: CallbackQuery, state: FSMContext):
        uid = cb.data.split(":", 2)[2]
        picked = (await state.get_data()).get("picked", [])
        if not picked:
            await cb.answer("Сначала отметь счета", show_alert=True)
            return
        if str(kv_get(db, f"guest_by:{uid}")) != str(cb.from_user.id):
            await cb.answer("Это не твой гость", show_alert=True)
            return
        await state.clear()
        who = kv_get(db, f"guest_name:{uid}") or uid
        try:
            added = accounts.share(picked, cb.from_user.id, int(uid))
        except ValueError as e:
            await cb.answer(str(e), show_alert=True)
            return
        await cb.answer(f"Отправлено: {len(added)}")
        await swap(cb, f"✅ <b>Отправлено {html.escape(str(who))}</b>\n{trades.THIN}\n"
                       f"{html.escape(describe(picked, cb.from_user.id))}\n\n"
                       f"<i>Счета появятся у него при следующем открытии бота. "
                       f"Твои остались у тебя.</i>", settings_menu(cb.from_user.id, db)[1])
        try:    # человек должен понять, откуда у него новые счета
            await send(bot, int(uid),
                       f"🎁 <b>С тобой поделились счетами</b>\n{trades.THIN}\n"
                       f"{html.escape(describe(picked, int(uid)))}\n\n"
                       f"<i>Открой /start — они уже в списке.</i>")
        except Exception as e:
            log.warning("не уведомил получателя %s: %s", uid, e)

    @dp.message(Share.target)
    async def cfg_share_target(msg: Message, state: FSMContext):
        picked = (await state.get_data()).get("picked", [])
        raw = msg.text.strip()
        if not raw.lstrip("-").isdigit():
            await msg.answer("Нужен числовой Telegram ID получателя, например <code>851274731</code>.\n"
                             "<i>Свой ID он увидит внизу приветствия по /start.</i>")
            return
        if not picked:
            await msg.answer("Сначала отметь галочками, какие счета отправить.")
            return
        await state.clear()
        try:
            added = accounts.share(picked, msg.from_user.id, int(raw))
        except ValueError as e:
            await msg.answer(f"❌ {html.escape(str(e))}")
            return
        await send(bot, msg.chat.id,
                   f"✅ Отправлено счетов: <b>{len(added)}</b> — {html.escape(', '.join(added))}\n"
                   f"<i>Они появятся у получателя при следующем открытии бота. "
                   f"Твои счета остались у тебя.</i>")
        try:    # получателю — уведомление, если он уже писал боту
            await send(bot, int(raw),
                       f"📥 <b>С тобой поделились счетами</b>\n{trades.THIN}\n"
                       f"{html.escape(', '.join(added))}\n\nОткрой /start — они уже в списке.")
        except Exception as e:
            log.info("получатель %s пока недоступен: %s", raw, e)

    @dp.callback_query(F.data == "add")
    async def add_start(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        await state.set_state(AddAcc.cabinet)
        known = [c for c in accounts.cabinets(cb.from_user.id) if c != accounts.NO_CABINET]
        # здесь номер оставляем: спрашиваем именно Customer Number, и по нему
        # человек сверяется с порталом
        rows = [[InlineKeyboardButton(text=f"🗂 {accounts.label(c, cb.from_user.id)} · {c}",
                                      callback_data=f"cab:{c}")] for c in known]
        rows.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
        hint = ("\n\nИли выбери кабинет, который уже добавлен." if known else "")
        await cb.message.answer(
            "＋ <b>Новый счёт</b>\n" + trades.THIN +
            "\nИз какого кабинета этот счёт? Пришли <b>Customer Number</b> — "
            "он в портале внизу слева, например <code>CU228816</code>." + hint,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    @dp.callback_query(F.data.startswith("cab:"), AddAcc.cabinet)
    async def add_cabinet_known(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        cab = cb.data.split(":", 1)[1]
        known = accounts.cabinets(cb.from_user.id).get(cab, {})
        await state.update_data(cabinet=cab, holder=known.get("holder", ""))
        await state.set_state(AddAcc.name)
        await cb.message.answer("Как называть счёт в боте? Например <code>SONIC #1</code>",
                                reply_markup=CANCEL)

    @dp.message(AddAcc.cabinet)
    async def add_cabinet(msg: Message, state: FSMContext):
        cab = msg.text.strip().upper()
        # владельца не спрашиваем — его имя возьмём из профиля счёта в MT5
        # само (accounts_info().name), когда счёт подключится в finish_add
        known = accounts.cabinets(msg.from_user.id).get(cab, {})
        await state.update_data(cabinet=cab, holder=known.get("holder", ""))
        await state.set_state(AddAcc.name)
        await msg.answer("Как называть счёт в боте? Например <code>SONIC #1</code>",
                         reply_markup=CANCEL)


    @dp.callback_query(F.data == "cancel")
    async def add_cancel(cb: CallbackQuery, state: FSMContext):
        await cb.answer("Отменено")
        await state.clear()
        text, kb = dashboard(cb.from_user.id)
        await cb.message.answer(text, reply_markup=kb)

    @dp.message(AddAcc.name)
    async def add_name(msg: Message, state: FSMContext):
        name = msg.text.strip()
        if accounts.by_name(name, msg.from_user.id):
            await msg.answer("Счёт с таким названием у тебя уже есть, придумай другое.")
            return
        await state.update_data(name=name)
        await state.set_state(AddAcc.login)
        await msg.answer("Номер счёта MT5? Например <code>50712049</code>", reply_markup=CANCEL)

    @dp.message(AddAcc.login)
    async def add_login(msg: Message, state: FSMContext):
        if not msg.text.strip().isdigit():
            await msg.answer("Номер счёта — это только цифры. Попробуй ещё раз.")
            return
        await state.update_data(login=msg.text.strip())
        await state.set_state(AddAcc.password)
        await msg.answer("Пароль от счёта.\n\n<i>Хватит investor-пароля — бот только читает. "
                         "Сообщение с паролем я удалю сразу после сохранения.</i>",
                         reply_markup=CANCEL)

    @dp.message(AddAcc.password)
    async def add_password(msg: Message, state: FSMContext):
        await state.update_data(password=msg.text.strip(), pwd_msg=msg.message_id)
        await state.set_state(AddAcc.server)
        await msg.answer("Торговый сервер? Нажми кнопку или впиши другой.",
                         reply_markup=SERVER_KB)

    async def do_add(msg_chat_id, owner, state: FSMContext, server: str):
        data = await state.get_data()
        await state.clear()
        try:    # пароль убираем из истории чата
            await bot.delete_message(msg_chat_id, data["pwd_msg"])
        except Exception:
            pass
        text = await finish_add(bot, msg_chat_id, owner, {**data, "server": server})
        await send(bot, msg_chat_id, text, menu("today", owner=owner))

    @dp.callback_query(F.data == "server:default", AddAcc.server)
    async def add_server_default(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        await do_add(cb.message.chat.id, cb.from_user.id, state, DEFAULT_SERVER)

    @dp.message(AddAcc.server)
    async def add_server(msg: Message, state: FSMContext):
        await do_add(msg.chat.id, msg.from_user.id, state, msg.text.strip())

    @dp.message(Command("accounts"))
    async def accounts_cmd(msg: Message):
        me = msg.from_user.id
        accs = accounts.load(me)
        if not accs:
            await msg.answer(NO_ACCOUNTS, reply_markup=menu("today", owner=me))
            return
        lines = [f"🏷 <b>{a['name']}</b> — счёт {a['login']}, {a['server']}, ×{a['multiplier']:g}"
                 for a in accs]
        await send(bot, msg.chat.id, "<b>Твои счета</b>\n" + trades.THIN + "\n" +
                   "\n".join(lines) + "\n\n<i>удалить: /removeaccount ИМЯ</i>",
                   menu("today", owner=me))

    @dp.message(Command("removeaccount"))
    async def remove_cmd(msg: Message, command: CommandObject):
        name = (command.args or "").strip()
        if accounts.remove(name, msg.from_user.id):
            await msg.answer(f"Счёт {name} удалён.")
        else:
            await msg.answer("Не нашёл такой счёт среди твоих. Список: /accounts")

    @dp.message(Command("status"))
    async def status_cmd(msg: Message):
        me = msg.from_user.id
        accs = accounts.load(me)
        if not accs:
            await msg.answer(NO_ACCOUNTS, reply_markup=menu("today", owner=me))
            return
        blocks = [f"🏷 <b>{a['name']}</b>\n" +
                  (trades.fmt_status(trades.currency()) if connect(a) else no_mt5(a))
                  for a in accs]
        await send(bot, msg.chat.id, "\n\n".join(blocks), menu("today", owner=me))

    @dp.message(Command("day"))
    async def day_cmd(msg: Message, command: CommandObject):
        parts = (command.args or "").split()
        try:
            d = parse_date(parts[0])
        except (ValueError, IndexError):
            await msg.answer("Формат: <code>/day 05.08.2026</code> "
                             "(можно добавить имя счёта: <code>/day 05.08.2026 SONIC</code>)")
            return
        a, b = day_bounds(d)
        await send(bot, msg.chat.id,
                   ranged(f"{d:%d.%m.%Y}", a, b, "", parts[1] if len(parts) > 1 else None,
                          msg.from_user.id))

    @dp.message(Command("since"))
    async def since_cmd(msg: Message, command: CommandObject):
        parts = (command.args or "").split()
        try:
            d = parse_date(parts[0])
        except (ValueError, IndexError):
            await msg.answer("Формат: <code>/since 22.07.2026</code> — заработок с этой даты по сегодня")
            return
        await send(bot, msg.chat.id,
                   ranged("С выбранной даты", datetime.combine(d, time.min), trades.clock(),
                          f"{d:%d.%m.%Y} — сегодня", parts[1] if len(parts) > 1 else None,
                          msg.from_user.id))

    @dp.message(Command("period"))
    async def period_cmd(msg: Message, command: CommandObject):
        parts = (command.args or "").split()
        try:
            a, b = parse_date(parts[0]), parse_date(parts[1])
        except (ValueError, IndexError):
            await msg.answer("Формат: <code>/period 01.08.2026 11.08.2026</code>")
            return
        if a > b:
            a, b = b, a
        await send(bot, msg.chat.id,
                   ranged("Свой период", datetime.combine(a, time.min),
                          datetime.combine(b, time.max), f"{a:%d.%m.%Y} — {b:%d.%m.%Y}",
                          parts[2] if len(parts) > 2 else None, msg.from_user.id))

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        @dp.message(Command("check"))
        async def check(msg: Message):
            if not await poll_portal(session, bot, db, str(msg.chat.id)):
                await msg.answer("Новых событий кабинета нет.")

        async def monthly_rollup():
            """Раз в сутки сворачиваем прошлые месяцы: детали за них не нужны,
            а итоги остаются навсегда."""
            while True:
                try:
                    if not trades.HAS_MT5:      # чистим только серверную базу
                        import store
                        keep = trades.clock().replace(day=1).strftime("%Y-%m-01")
                        removed = store.rollup(store.open_db(), keep, trades.is_transfer,
                                               trades.is_perf_fee, month_growth)
                        if removed:
                            log.info("свернул прошлые месяцы, убрано сделок: %d", removed)
                except Exception:
                    log.exception("свёртка месяцев")
                await asyncio.sleep(24 * 3600)

        async def heartbeat():
            """Отметка «бот жив» в общей базе: по ней пульт управления видит
            состояние даже когда SSH до сервера не отвечает."""
            while True:
                try:
                    kv_set(db, "bot_heartbeat", trades.clock().isoformat())
                except Exception:
                    log.exception("не записал отметку живости")
                await asyncio.sleep(30)

        async def terminal_watchdog():
            """Терминал читает агент на ПК. Если агент давно не выходил на связь —
            терминал/ПК недоступен, новые сделки не придут. Предупреждаем владельца
            один раз при пропаже и один раз при восстановлении."""
            import store
            sdb = store.open_db()
            while True:
                try:
                    now = utcnow()
                    # все счета владельца читает один агент на одном ПК, поэтому
                    # рвётся связь сразу по всем — предупреждаем один раз, а не
                    # отдельным сообщением на каждый счёт
                    watched = defaultdict(list)
                    for acc in accounts.load():
                        if not acc.get("enabled", True):
                            continue
                        st = store.get_state(sdb, acc["login"])
                        if not st or not st.get("synced"):
                            continue
                        gap = (now - datetime.fromisoformat(st["synced"])).total_seconds()
                        watched[acc["owner"]].append((acc, gap))

                    for owner, items in watched.items():
                        # по умолчанию выключено: обрывы связи случаются и
                        # ночью, а большинству эти сообщения не нужны
                        if kv_get(db, f"link_alerts:{owner}") != "1":
                            continue
                        stale = [(a, g) for a, g in items if g > TERMINAL_STALE]
                        key = f"term_down:{owner}"
                        down = kv_get(db, key) == "1"
                        if stale and not down:
                            kv_set(db, key, "1")
                            names = "\n".join(f"🏷 {html.escape(a['name'])}" for a, _ in stale)
                            worst = max(g for _, g in stale)
                            kb = InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(text="🔄 Попробовать запустить",
                                                     callback_data=f"restart:{stale[0][0]['login']}")]])
                            await send(bot, owner,
                                       f"⚠️ <b>Нет связи с MT5</b>\n{trades.THIN}\n"
                                       f"{names}\n"
                                       f"Сделки сейчас <b>не отслеживаются</b>, уведомления о новых "
                                       f"не придут.\nПричина — оборвалась цепочка "
                                       f"<i>терминал → агент → сервер</i>: закрыт терминал, "
                                       f"остановлен агент, выключен ПК или пропал интернет.\n"
                                       f"<i>последние данные {worst / 60:.0f} мин назад</i>", kb)
                        elif not stale and down:
                            kv_set(db, key, "0")
                            asked = kv_get(db, f"restart_asked:{owner}") == "1"
                            kv_set(db, f"restart_asked:{owner}", "0")
                            lead = ("✅ <b>Готово! Терминал запущен из бота</b>" if asked
                                    else "✅ <b>Связь с MT5 восстановлена</b>")
                            await send(bot, owner,
                                       f"{lead}\n{trades.THIN}\n"
                                       f"Сделки снова отслеживаются, уведомления будут приходить.")
                except Exception:
                    log.exception("вотчдог терминала")
                await asyncio.sleep(60)

        async def loop(fn, seconds, name):
            """Опрос с отступлением: пока источник молчит, паузу удваиваем.

            Партнёрский портал может исчезнуть насовсем (сейчас его адрес
            отдаёт 404 на всё). Ходить туда каждые две минуты — это 64 пустых
            запроса в час и лог, в котором не видно настоящих ошибок.
            """
            pause, fails = seconds, 0
            while True:
                try:
                    if chat_id:
                        await fn()
                    if fails:
                        log.info("%s: источник ответил, возвращаюсь к обычному опросу", name)
                    pause, fails = seconds, 0
                except Exception as e:
                    fails += 1
                    pause = min(pause * 2, 3600)    # но не реже раза в час
                    log.warning("%s: молчит (%d подряд), следующая попытка через %d мин — %s",
                                name, fails, pause // 60, e)
                await asyncio.sleep(pause)

        async def mt5_loop():
            while True:
                try:
                    await poll_mt5(bot, db)
                except Exception:
                    log.exception("сбой опроса MT5")
                # каждый счёт в круге — это перелогин терминала, поэтому чем больше
                # счетов у пользователей, тем реже имеет смысл опрашивать
                many = len(accounts.load()) > 1
                await asyncio.sleep(max(MT5_POLL_SECONDS, 15) if many else MT5_POLL_SECONDS)

        async def telegram_watchdog():
            """Следит, что Telegram вообще отвечает.

            Библиотека при мёртвом прокси ретраит бесконечно и наружу не падает:
            служба «активна», а бот глухой — так он и простоял, пока прокси
            отказывал. Выходим с ошибкой, systemd поднимет заново, и на старте
            выберется живой прокси из списка.
            """
            fails = 0
            while True:
                await asyncio.sleep(60)
                try:
                    await bot.me()
                    if fails:
                        log.info("связь с Telegram восстановилась")
                    fails = 0
                except Exception as e:
                    fails += 1
                    log.error("Telegram недоступен (%d мин): %s", fails, e)
                    if fails >= TELEGRAM_DEAD_MIN:
                        log.error("перезапускаюсь ради выбора рабочего прокси")
                        os._exit(1)     # именно так: обычный выход задачу не убьёт

        async def daily_digest():
            """Раз в сутки — сводка о состоянии, если человек её просил.

            Сама по себе строчка «счетов отслеживается 0 из 4» бесполезна:
            утром ноутбук обычно выключен, и это норма, а не новость. Поэтому
            сводка идёт только тем, кто включил уведомления о связи, и только
            когда есть что сказать: доход с сети или счета реально отвалились
            среди рабочего дня.
            """
            import store as _st
            while True:
                await asyncio.sleep(3600)
                now = trades.clock()
                if now.hour != DIGEST_HOUR or kv_get(db, "digest_day") == str(now.date()):
                    continue
                kv_set(db, "digest_day", str(now.date()))
                try:
                    sdb = _st.open_db()
                    gaps, fresh = [], 0
                    for acc in accounts.load():
                        st = _st.get_state(sdb, acc["login"])
                        if st and st.get("synced"):
                            gap = (utcnow()
                                   - datetime.fromisoformat(st["synced"])).total_seconds()
                            gaps.append(gap)
                            fresh += gap < TERMINAL_STALE
                    total = len(gaps)
                    link = "🟢" if fresh == total else ("🟡" if fresh else "🔴")
                    weekend = " · выходной, сделок не ждём" if trades.is_weekend(now) else ""
                    for who in {str(a["owner"]) for a in accounts.load()}:
                        mine = accounts.load(who)
                        ok = sum(1 for a in mine
                                 if (s := _st.get_state(sdb, a["login"])) and s.get("synced")
                                 and (utcnow()
                                      - datetime.fromisoformat(s["synced"])).total_seconds()
                                 < TERMINAL_STALE)
                        # доход с сети за вчера — он копится поштучно и мелко,
                        # одной строкой в сводке читается куда лучше
                        was = str((now - timedelta(days=1)).date())
                        earned = float(kv_get(db, f"net_income:{was}", 0) or 0)
                        n_net = int(kv_get(db, f"net_trades:{was}", 0) or 0)
                        income = (f"\n💸 Доход с сети за вчера: "
                                  f"<b>{trades.amount(earned, 'USD', signed=True)}</b>"
                                  f" <i>({n_net} сделок сети)</i>" if earned else "")
                        await send(bot, who,
                                   f"{link} <b>Бот на связи</b>\n{trades.THIN}\n"
                                   f"Счетов отслеживается: <b>{ok} из {len(mine)}</b>"
                                   f"{weekend}{income if str(who) == str(chat_id) else ''}\n"
                                   f"<i>{now:%d.%m.%Y}, "
                                   f"{trades.WEEKDAYS[now.weekday()]}</i>")
                except Exception:
                    log.exception("не собрал ежедневную сводку")

        asyncio.create_task(daily_digest())
        asyncio.create_task(heartbeat())
        asyncio.create_task(monthly_rollup())
        asyncio.create_task(telegram_watchdog())
        asyncio.create_task(terminal_watchdog())
        asyncio.create_task(mt5_loop())
        asyncio.create_task(loop(lambda: poll_portal(session, bot, db, chat_id),
                                 POLL_SECONDS, "кабинет"))
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
