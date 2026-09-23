"""Offline integration checks. All writes go to temporary databases and accounts."""
import asyncio
import hashlib
import hmac
import inspect
import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_root = tempfile.TemporaryDirectory()
os.environ.update(TRADES_SOURCE="store", TELEGRAM_BOT_TOKEN="test-token",
                  STATE_DB=str(Path(_root.name) / "state.db"),
                  TRADES_DB=str(Path(_root.name) / "trades.db"),
                  ACCOUNTS_FILE=str(Path(_root.name) / "accounts.json"),
                  ALLOWED_USERS="", FOUNDER_ID="1")
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
import accounts
import bot
import coordination
import miniapp
import partner
import store
import trades
import webhook_server


def signed(uid=1, timestamp=None, **extra):
    data = {"auth_date": str(int(time.time() if timestamp is None else timestamp)),
            "user": json.dumps({"id": uid, "first_name": "Тест"}), **extra}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.db = partner.open_db(":memory:")

    def tearDown(self):
        self.db.close()

    def test_recovered_primary_preempts_healthy_standby(self):
        # Primary always takes the lease back, even from a standby whose
        # lease has not expired yet — reserve only fills in while primary is
        # genuinely offline, it never keeps holding once primary is back.
        self.assertTrue(coordination.claim(self.db, "reserve", "r", "standby", 100)["granted"])
        coordination.renew(self.db, "reserve", "r", 250)
        self.assertTrue(coordination.claim(self.db, "main", "m", "primary", 110)["granted"])
        self.assertTrue(coordination.permits(self.db, "main", "m", 110))
        self.assertFalse(coordination.permits(self.db, "reserve", "r", 110))
        # a second primary claim (e.g. retry) is just a renewal, not a fresh preempt
        self.assertTrue(coordination.claim(self.db, "main", "m", "primary", 200)["granted"])

    def test_failover_and_fencing(self):
        coordination.claim(self.db, "main", "m", "primary", 0)
        self.assertFalse(coordination.claim(self.db, "reserve", "r", "standby", 179)["granted"])
        self.assertTrue(coordination.claim(self.db, "reserve", "r", "standby", 181)["granted"])
        self.assertFalse(coordination.permits(self.db, "main", "m", 182))
        self.assertFalse(coordination.permits(self.db, "main", None, 182))
        self.assertTrue(coordination.permits(self.db, "reserve", "r", 182))

    def test_claims_without_data_do_not_keep_dead_terminal_active(self):
        coordination.claim(self.db, "main", "m", "primary", 0)
        self.assertTrue(coordination.claim(self.db, "main", "m", "primary", 170)["granted"])
        self.assertFalse(coordination.claim(self.db, "main", "m", "primary", 181)["granted"])
        self.assertTrue(coordination.claim(self.db, "reserve", "r", "standby", 182)["granted"])

    def test_stale_session_and_wrong_host_cannot_extend_lease(self):
        coordination.claim(self.db, "main", "new", "primary", 0)
        coordination.renew(self.db, "main", "old", 175)
        self.assertEqual(coordination.read(self.db)["expires"], 180)
        self.assertFalse(coordination.claim(self.db, "main", "old", "primary", 179)["granted"])

    def test_legacy_standby_cannot_take_over_while_owner_is_alive(self):
        coordination.claim(self.db, "main", "m", "primary", 0)
        self.assertFalse(coordination.may_poll_anonymously(self.db, 100))
        self.assertFalse(coordination.authorize(self.db, "old-reserve", None, 100))
        self.assertTrue(coordination.permits(self.db, "main", "m", 100))

    def test_legacy_standby_replaces_offline_primary_until_it_returns(self):
        # Production failure: reserve on pre-lease code was fenced forever
        # after the primary went offline, so nobody polled MT5.
        coordination.claim(self.db, "main", "m", "primary", 0)
        self.assertTrue(coordination.may_poll_anonymously(self.db, 181))
        self.assertTrue(coordination.authorize(self.db, "old-reserve", None, 181))
        coordination.renew(self.db, "old-reserve", None, 200)
        self.assertEqual(coordination.read(self.db)["expires"], 380)
        # A recovered new-code primary preempts it right away — legacy reserve
        # only ever filled in for an offline primary, never holds it back.
        self.assertTrue(coordination.claim(self.db, "main", "m2", "primary", 300)["granted"])
        self.assertFalse(coordination.authorize(self.db, "old-reserve", None, 300))
        self.assertTrue(coordination.permits(self.db, "main", "m2", 300))

    def test_retry_after_counts_the_takeover_window_of_own_expired_lease(self):
        coordination.claim(self.db, "main", "m", "primary", 0)
        result = coordination.claim(self.db, "main", "m", "primary", 200)
        self.assertFalse(result["granted"])
        # аренда истекла на 180-й секунде, своё окно перехвата — ещё 180
        self.assertEqual(result["retry_after"], 160)
        self.assertEqual(coordination.claim(self.db, "reserve", "r", "standby", 10)["retry_after"], 170)

    def test_malformed_lease_is_treated_as_absent(self):
        for broken in ('{"host": 1}', "[]", '"lease"', '{"host": "a", "session": "s", "expires": true}'):
            with self.subTest(value=broken):
                partner.kv_set(self.db, coordination.KEY, broken)
                self.assertIsNone(coordination.read(self.db))
                self.assertTrue(coordination.permits(self.db, "main", "m", 0))
                self.assertTrue(coordination.claim(self.db, "main", "m", "primary", 0)["granted"])


class MachineStateTests(unittest.TestCase):
    def test_service_panel_tells_polling_waiting_legacy_and_offline_apart(self):
        from datetime import timezone
        db = partner.open_db(":memory:")
        now = 1_000_000.0
        iso = lambda ago: datetime.fromtimestamp(now - ago, timezone.utc).replace(tzinfo=None).isoformat()
        coordination.claim(db, "main", "m" * 16, "primary", now - 10)
        partner.kv_set(db, "machine_claim:main", iso(3))
        partner.kv_set(db, "machine_role:main", "primary")
        partner.kv_set(db, "machine_commit:main", "abcdef1234")
        partner.kv_set(db, "machine_claim:reserve", iso(5))
        partner.kv_set(db, "machine_role:reserve", "standby")
        # standby on pre-lease code: alive (canary reports) but never claims
        partner.kv_set(db, "canary_latest_seen:old", iso(20))
        partner.kv_set(db, "machine_blocked:old", f"{iso(60)}|dirty tree")
        partner.kv_set(db, "machine_seen:gone", iso(3000))
        got = {m["host"]: m for m in miniapp.machine_states(db, now)}
        self.assertEqual({h: m["state"] for h, m in got.items()},
                         {"main": "polling", "reserve": "waiting", "old": "legacy", "gone": "offline"})
        self.assertEqual(got["main"]["commit"], "abcdef1")
        self.assertEqual(got["old"]["blocked"], "dirty tree")
        self.assertEqual(got["main"]["blocked"], "")
        # блокировку записали 60 с назад, проверка раз в 15 минут — осталось 840 с
        self.assertEqual(got["old"]["next_check"], 840)
        self.assertIsNone(got["main"]["next_check"])
        # вторая половина получасового окна: до следующей проверки не «0 секунд»,
        # а остаток текущего 15-минутного цикла
        partner.kv_set(db, "machine_blocked:old", f"{iso(1000)}|dirty tree")
        later = {m["host"]: m for m in miniapp.machine_states(db, now)}
        self.assertEqual(later["old"]["next_check"], 800)
        # a stale block reason must not stay on screen forever
        partner.kv_set(db, "machine_blocked:old", f"{iso(4000)}|dirty tree")
        stale = {m["host"]: m for m in miniapp.machine_states(db, now)}
        self.assertEqual(stale["old"]["blocked"], "")


class FormattingTests(unittest.TestCase):
    def test_russian_plural_forms(self):
        words = ("сделка", "сделки", "сделок")
        for n, want in ((0, "сделок"), (1, "сделка"), (2, "сделки"), (5, "сделок"), (11, "сделок"),
                        (12, "сделок"), (21, "сделка"), (22, "сделки"), (25, "сделок"), (101, "сделка"),
                        (111, "сделок")):
            with self.subTest(n=n):
                self.assertEqual(trades.plural(n, *words), want)

    def test_ticker_is_escaped_for_telegram_html(self):
        self.assertEqual(trades.short("S&P500.cash", 6), "S&amp;P500")
        self.assertEqual(trades.short(None), "")

    def test_reinvest_halves_pair_within_a_few_seconds_only(self):
        moment = datetime(2026, 9, 1, 12, 0, 0)
        self.assertTrue(trades.same_moment(moment, moment + timedelta(seconds=1)))
        self.assertFalse(trades.same_moment(moment, moment + timedelta(minutes=1)))

    def test_withdrawal_formatter_names_the_cabinet(self):
        text = partner.fmt_withdrawal({"customer_no": "CU404", "amount": "5<b>"})
        self.assertIn("Кабинет CU404", text)
        self.assertIn("5&lt;b&gt;", text)

    def test_long_message_is_clipped_without_breaking_markup(self):
        rows = [f"<b>{i:02d}.09</b> · +1.00 · <i>S&amp;P</i>" for i in range(400)]
        text = "📊 <b>Отчёт</b>\n" + trades.quote(rows)
        clipped = miniapp.logic.clip(text, 1000)
        self.assertLessEqual(len(clipped), 1000)
        self.assertTrue(clipped.endswith(miniapp.logic.CLIPPED))
        body = clipped[:-len(miniapp.logic.CLIPPED)]
        for tag in ("b", "i", "blockquote"):
            with self.subTest(tag=tag):
                self.assertEqual(body.count(f"<{tag}>") + body.count(f"<{tag} "), body.count(f"</{tag}>"))
        self.assertEqual(miniapp.logic.clip("короткий <b>текст</b>", 1000), "короткий <b>текст</b>")
        # одна длинная строка: обрывок тега или сущности в конце не остаётся
        one_line = miniapp.logic.clip("<b>" + "x&amp;" * 400 + "</b>", 300)
        self.assertNotRegex(one_line[:-len(miniapp.logic.CLIPPED)], r"&[a-z]*$|<[^>]*$")

    def test_terminal_warning_without_terminal_path_and_with_markup_in_name(self):
        text = miniapp.logic.no_mt5({"name": "SONIC <1>", "login": 42})
        self.assertIn("SONIC &lt;1&gt;", text)
        self.assertIn("42", text)

    def test_cabinet_numbers_are_latin_and_short(self):
        self.assertEqual(accounts.normalize_cabinet(" cu 228816 "), "CU228816")
        for bad in ("СU228816", "CU:1", "", "C" * 25, None, "CU 2&8"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                accounts.normalize_cabinet(bad)

    def test_same_second_site_deposits_are_both_kept(self):
        db = partner.open_db(":memory:")
        with patch.object(trades, "clock", return_value=datetime(2026, 9, 1, 12, 0, 0)):
            partner.site_move_add(db, "CU1", "deposit", 100.0)
            partner.site_move_add(db, "CU1", "deposit", 100.0)
        self.assertEqual([m["amount"] for m in partner.site_moves(db, "CU1")], [100.0, 100.0])


class PortalTests(unittest.IsolatedAsyncioTestCase):
    """ibportal против подставного API кабинета — без сети и без настоящих токенов."""

    async def asyncSetUp(self):
        import aiohttp
        import ibportal
        self.portal = ibportal
        self.tmp = tempfile.TemporaryDirectory()
        base = ibportal.BASE
        app = web.Application()

        async def refresh(request):
            # метка срока без зоны — так её отдаёт .NET
            return web.json_response({"accessToken": "a1", "refreshToken": "r2",
                                      "expiresAt": "2099-01-01T00:00:00"})

        async def notifications(request):
            if request.headers.get("Authorization") != "Bearer a1":
                return web.json_response({"message": "unauthorized"}, status=401)
            return web.json_response({"items": [{"id": 1, "title": "t"}]})

        async def gateway_error(request):
            return web.Response(text="<html>502 Bad Gateway</html>", status=502, content_type="text/html")

        app.router.add_post(f"{base}/Auth/refresh", refresh)
        app.router.add_get(f"{base}/Notifications", notifications)
        app.router.add_get(f"{base}/Distributor/Status", gateway_error)
        self.server = TestServer(app)
        await self.server.start_server()
        self.session = aiohttp.ClientSession()
        self.token_file = str(Path(self.tmp.name) / "ib_token")
        self.patches = [patch.object(ibportal, "API", str(self.server.make_url("")).rstrip("/")),
                        patch.object(ibportal, "TOKEN_FILE", self.token_file),
                        patch.object(ibportal, "_token", ""), patch.object(ibportal, "_refresh", ""),
                        patch.dict(os.environ, {"IB_REFRESH_TOKEN": "r1"})]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        await self.session.close()
        await self.server.close()
        self.tmp.cleanup()

    async def test_token_without_timezone_does_not_break_the_next_request(self):
        self.assertEqual(await self.portal.notifications(self.session), [{"id": 1, "title": "t"}])
        # второй запрос сравнивает «сейчас» со сроком токена — раньше TypeError
        self.assertEqual(len(await self.portal.notifications(self.session)), 1)

    async def test_refresh_token_is_saved_atomically_and_privately(self):
        await self.portal.notifications(self.session)
        with open(self.token_file, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "r2")
        self.assertFalse(os.path.exists(self.token_file + ".tmp"))
        if os.name == "posix":
            self.assertEqual(os.stat(self.token_file).st_mode & 0o777, 0o600)

    async def test_html_error_page_becomes_portal_error(self):
        with self.assertRaises(self.portal.PortalError) as caught:
            await self.portal.status(self.session)
        self.assertIn("502", str(caught.exception))


class OneEventOneMessageTests(unittest.IsolatedAsyncioTestCase):
    """Одно событие видно из двух источников — в чат приходит одно сообщение.

    Вывод со стратегии на баланс Tag Markets (и заведение с баланса на
    стратегию) сообщают и вебхук портала, и история MT5; реинвест приходит
    двумя строками. Кто узнал первым, тот и пишет, а текст — всегда как у MT5.
    """

    async def asyncSetUp(self):
        import bot
        self.bot = bot
        self.tmp = tempfile.TemporaryDirectory()
        self.saved_path, accounts.PATH = accounts.PATH, str(Path(self.tmp.name) / "accounts.json")
        self.db = partner.open_db(str(Path(self.tmp.name) / "state.db"))
        self.tdb = store.open_db(str(Path(self.tmp.name) / "trades.db"))
        trades._db = self.tdb
        self.patches = [patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "1"}),
                        patch.object(webhook_server, "TOKEN", "hook-test"),
                        patch.object(webhook_server, "notify", self.hook_send),
                        patch.object(webhook_server, "edit_notification", self.hook_edit)]
        for p in self.patches:
            p.start()
        self.acc = {"owner": "1", "name": "SONIC", "strategy": "SONIC", "login": 123,
                    "password": "x", "server": "Demo", "multiplier": 24,
                    "cabinet": "CU1", "holder": "DZMITRY"}
        accounts.add(self.acc)
        store.save_state(self.tdb, 123, 60000, 60000, "USD", "Demo")
        partner.kv_set(self.db, "mt5_last_ticket:1:123", 1)
        partner.kv_set(self.db, "mt5_last_ticket:2:123", 1)
        partner.unseen(self.db, "deposit", [{"tx_id": "old"}])     # не первый запуск
        self.app = web.Application()
        self.app["db"] = self.db
        self.app.router.add_route("*", "/hook/deposit", webhook_server.on_deposit)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.chat = []          # [кому, текст] — индекс + 1 и есть id сообщения
        self.edits = 0
        test = self

        class Bot:
            async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
                test.chat.append([str(chat_id), text])
                return type("Msg", (), {"message_id": len(test.chat)})()

            async def edit_message_text(self, text, chat_id=None, message_id=None, **kwargs):
                await test.hook_edit(None, chat_id, message_id, text)

        self.fake_bot = Bot()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        await self.client.close()
        trades._db = None
        accounts.PATH = self.saved_path
        self.db.close()
        self.tdb.close()
        self.tmp.cleanup()

    async def hook_send(self, _app, text, markup=None):
        self.chat.append(["1", text])
        return len(self.chat)

    async def hook_edit(self, _app, chat_id, message_id, text):
        self.chat[int(message_id) - 1] = [str(chat_id), text]
        self.edits += 1
        return True

    def deal(self, ticket, net, comment, moment=None):
        store.save_deals(self.tdb, 123, [{
            "ticket": ticket, "time": moment or trades.clock(), "symbol": "", "side": "",
            "volume": 0, "price": 0, "profit": net, "swap": 0, "commission": 0, "net": net,
            "is_balance": True, "is_closing": False, "is_opening": False, "comment": comment}])

    async def hook(self, amount="12.74", tx="tx1"):
        r = await self.client.get(f"/hook/deposit?token=hook-test&customer_no=CU1"
                                  f"&amount={amount}&currency=USD&tx_id={tx}")
        self.assertEqual(r.status, 200, await r.text())
        await asyncio.gather(*list(webhook_server._background))

    def feed(self, user="1"):
        return partner.notifications_for(self.db, user)["items"]

    async def test_hook_first_then_mt5_edits_the_same_message(self):
        await self.hook()
        self.assertEqual(len(self.chat), 1)
        self.assertIn("Пополнение баланса Tag Markets", self.chat[0][1])
        self.assertIn("+12.74$", self.chat[0][1])
        self.assertIn("🏷 <b>SONIC</b>", self.chat[0][1], "шапка как у уведомлений MT5")

        self.deal(10, -12.74, "Profit Withdrawal")
        await self.bot.poll_mt5(self.fake_bot, self.db)
        self.assertEqual(len(self.chat), 1, "второго сообщения нет")
        self.assertEqual(self.edits, 1)
        self.assertIn("Профит списан со стратегии", self.chat[0][1])
        self.assertIn("-12.74$", self.chat[0][1])
        self.assertIn("DZMITRY · <code>123</code>", self.chat[0][1])
        items = self.feed()
        self.assertEqual(len(items), 1, "и в ленте Mini App одно событие")
        self.assertEqual((items[0]["title"], items[0]["kind"]), ("SONIC · Вывод", "withdrawals"))
        self.assertEqual(partner.kv_get(self.db, "mt5_last_ticket:1:123"), "10")

    async def test_mt5_first_then_hook_stays_silent(self):
        self.deal(10, -12.74, "Profit Withdrawal")
        await self.bot.poll_mt5(self.fake_bot, self.db)
        self.assertEqual(len(self.chat), 1)
        self.assertIn("Профит списан со стратегии", self.chat[0][1])
        await self.hook()
        self.assertEqual(len(self.chat), 1)
        self.assertEqual(self.edits, 0)
        self.assertEqual(len(self.feed()), 1)
        # кошелёк считает приход по-прежнему — меняется только уведомление
        self.assertEqual(partner.kv_get(self.db, "wallet_in:CU1"), "12.74")

    async def test_hook_after_agent_synced_row_sends_exact_mt5_text(self):
        self.deal(10, -12.74, "Profit Withdrawal")     # агент успел, бот ещё нет
        await self.hook()
        self.assertEqual(len(self.chat), 1)
        first = self.chat[0][1]
        self.assertIn("Профит списан со стратегии", first)
        await self.bot.poll_mt5(self.fake_bot, self.db)
        self.assertEqual(self.chat, [["1", first]], "бот не шлёт и не правит")
        self.assertEqual([i["event_key"] for i in self.feed()], ["trade:123:10"])

    async def test_capital_to_strategy_is_the_same_event_as_hook(self):
        await self.hook(amount="100", tx="tx2")
        self.deal(11, 2400.0, "Deposit")       # 2400 ÷ 24 = 100 своих денег
        await self.bot.poll_mt5(self.fake_bot, self.db)
        self.assertEqual(len(self.chat), 1)
        self.assertIn("Заведено на стратегию", self.chat[0][1])

    async def test_different_amounts_are_different_events(self):
        await self.hook()
        self.deal(10, -20.0, "Profit Withdrawal")
        await self.bot.poll_mt5(self.fake_bot, self.db)
        self.assertEqual(len(self.chat), 2)
        self.assertIn("Пополнение баланса Tag Markets", self.chat[0][1])
        self.assertEqual(self.edits, 0)

    async def test_guest_copy_still_gets_its_own_message(self):
        accounts.add({**self.acc, "owner": "2"})
        await self.hook()
        self.deal(10, -12.74, "Profit Withdrawal")
        await self.bot.poll_mt5(self.fake_bot, self.db)
        self.assertEqual([who for who, _ in self.chat], ["1", "2"])
        self.assertIn("Профит списан со стратегии", self.chat[0][1])
        self.assertIn("Профит списан со стратегии", self.chat[1][1])

    async def test_mt5_during_hook_send_is_applied_after_it(self):
        # строка MT5 заявлена, пока вебхук ещё ждёт ответа Telegram
        when = trades.clock()

        async def slow_send(text):
            status = await partner.announce_once(
                self.db, "CU1", 1274, when, "mt5", True, "ТОЧНЫЙ ТЕКСТ",
                ("withdrawals", "trade:123:10", "SONIC · Вывод", "точный"), "1",
                self.fail_send, self.edit_cb, ref="123:10")
            self.assertEqual(status, "merged")
            return await self.hook_send(None, text)

        status = await partner.announce_once(
            self.db, "CU1", 1274, when, "hook", False, "нейтральный",
            ("deposit", "wallet:CU1:tx1", "SONIC · Пополнение", "нейтральный"), "1",
            slow_send, self.edit_cb)
        self.assertEqual(status, "sent")
        self.assertEqual(self.chat, [["1", "ТОЧНЫЙ ТЕКСТ"]])
        self.assertEqual(self.feed()[0]["body"], "точный")

    async def test_failed_mt5_send_is_retried_by_the_same_ticket(self):
        when = trades.clock()
        args = (self.db, "CU1", 1274, when, "mt5", True, "текст",
                ("withdrawals", "trade:123:10", "SONIC · Вывод", "текст"), "1")
        self.assertEqual(await partner.announce_once(*args, self.none_send, self.edit_cb,
                                                     ref="123:10"), "failed")
        self.assertEqual(await partner.announce_once(*args, self.ok_send, self.edit_cb,
                                                     ref="123:10"), "sent")
        self.assertEqual(len(self.chat), 1)

    async def fail_send(self, text):
        raise AssertionError("второе сообщение не должно уходить")

    async def none_send(self, text):
        return None

    async def ok_send(self, text):
        return await self.hook_send(None, text)

    async def edit_cb(self, chat, msg, text):
        return await self.hook_edit(None, chat, msg, text)

    async def test_reinvest_halves_from_different_rounds_become_one_message(self):
        moment = trades.clock()
        self.deal(20, -6.0, "Adjust-6.00", moment)
        await self.bot.poll_mt5(self.fake_bot, self.db)
        self.assertEqual(len(self.chat), 1)
        self.assertIn("сейчас уйдёт в капитал", self.chat[0][1])
        self.deal(21, 144.0, "Upgrade-144.00", moment)
        await self.bot.poll_mt5(self.fake_bot, self.db)
        self.assertEqual(len(self.chat), 1, "вторая половина не пишет отдельно")
        self.assertIn("в тот же момент добавлено в капитал", self.chat[0][1])
        self.assertEqual(len(self.feed()), 1)
        self.assertEqual(partner.kv_get(self.db, "mt5_last_ticket:1:123"), "21")

    async def test_reinvest_with_upgrade_ticket_first_is_one_message(self):
        moment = trades.clock()
        self.deal(30, 144.0, "Upgrade-144.00", moment)
        self.deal(31, -6.0, "Adjust-6.00", moment)
        await self.bot.poll_mt5(self.fake_bot, self.db)
        self.assertEqual(len(self.chat), 1)
        self.assertIn("в тот же момент добавлено в капитал", self.chat[0][1])
        self.assertIn("-6.00$", self.chat[0][1])
        self.assertEqual(partner.kv_get(self.db, "mt5_last_ticket:1:123"), "31")


class AuthTests(unittest.TestCase):
    def test_authentication_and_tamper(self):
        self.assertEqual(miniapp.validate_init_data(signed(42), "test-token")["id"], 42)
        for raw in ("", signed().replace("hash=", "hash=0"), signed(timestamp=time.time()-90000),
                    signed(timestamp=time.time()+1000), signed()+"&auth_date=10", signed(uid="1")):
            with self.subTest(raw=raw[:20]), self.assertRaises((ValueError, TypeError)):
                miniapp.validate_init_data(raw, "test-token")


class BroadcastFormatTests(unittest.TestCase):
    def test_trade_notification_has_mini_app_then_dashboard(self):
        with patch.dict(os.environ, {"MINI_APP_URL": "https://crownfail.shop/tagmarkets/app/"}):
            buttons = miniapp.logic.trade_notification_buttons().inline_keyboard
        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0][0].web_app.url, "https://crownfail.shop/tagmarkets/app/")
        self.assertEqual(buttons[1][0].callback_data, "dash")

    def test_dashboard_opens_miniapp_first_with_or_without_accounts(self):
        with patch.dict(os.environ, {"MINI_APP_URL": "https://crownfail.shop/tagmarkets/app/"}):
            with patch.object(accounts, "cabinets", return_value={}), \
                    patch.object(miniapp.logic, "demo_button", return_value=None):
                _, markup = miniapp.logic.dashboard(1)
                self.assertEqual(markup.inline_keyboard[0][0].web_app.url,
                                 "https://crownfail.shop/tagmarkets/app/")
            with patch.object(accounts, "cabinets", return_value={"CU1": {
                "holder": "Test", "accounts": [{}]
            }}), patch.object(miniapp.logic, "account_totals", return_value=None), \
                    patch.object(miniapp.logic, "demo_button", return_value=None):
                _, markup = miniapp.logic.dashboard(1)
                self.assertEqual(markup.inline_keyboard[0][0].web_app.url,
                                 "https://crownfail.shop/tagmarkets/app/")

    def test_editor_html_is_canonical_and_untrusted_markup_is_escaped(self):
        self.assertEqual(miniapp.sanitize_broadcast_html(
            '<b>Заголовок <i>текст</b> после</i><script>alert(1)</script>'),
            '<b>Заголовок <i>текст</i></b> послеalert(1)')
        self.assertEqual(miniapp.sanitize_broadcast_html('<a href="https://bad.example">текст</a>'),
                         'текст')
        self.assertEqual(miniapp.sanitize_broadcast_html('<b>открыто'), '<b>открыто</b>')

    def test_previous_month_is_complete_calendar_month(self):
        title, first, last, _ = miniapp.logic.period('lastmonth')
        self.assertEqual(title, 'Прошлый месяц')
        self.assertEqual(first.day, 1)
        self.assertEqual((last + timedelta(microseconds=1)).day, 1)
        self.assertLess(first, last)

    def test_previous_week_includes_weekend(self):
        _, first, last, _ = miniapp.logic.period('lastweek')
        self.assertEqual(first.weekday(), 0)
        self.assertEqual(last.weekday(), 6)

    def test_trade_pairs_like_terminal(self):
        # вход связывается со своим выходом: по номеру позиции, а у старых
        # сделок без него — по порядку, как закрывает MT5
        t = datetime(2026, 9, 1, 10)
        deal = lambda ticket, mins, side, price, opening, pos=None, net=0: {
            "ticket": ticket, "time": t + timedelta(minutes=mins), "side": side, "price": price,
            "is_opening": opening, "is_closing": not opening, "position": pos, "net": net, "volume": .02}
        # по номеру позиции: вторая BUY закрыта раньше первой
        pairs = miniapp.trade_pairs([deal(1, 0, "BUY", 100, True, 7), deal(2, 1, "BUY", 101, True, 8),
                                     deal(3, 2, "SELL", 105, False, 8, 4), deal(4, 3, "SELL", 99, False, 7, -1)])
        self.assertEqual([(p["in_price"], p["out_price"]) for p in pairs], [(101, 105), (100, 99)])
        # без номеров: закрытие забирает самую раннюю открытую BUY
        pairs = miniapp.trade_pairs([deal(1, 0, "BUY", 100, True), deal(2, 1, "SELL", 103, True),
                                     deal(3, 2, "SELL", 102, False, net=2), deal(4, 3, "BUY", 101, False, net=2)])
        self.assertEqual([(p["side"], p["in_price"], p["out_price"]) for p in pairs],
                         [("BUY", 100, 102), ("SELL", 103, 101)])
        # вход до начала периода — выход без пары, направление по закрытию
        lone = miniapp.trade_pairs([deal(5, 0, "SELL", 110, False, 9, 3)])
        self.assertEqual((lone[0]["side"], lone[0]["in_price"]), ("BUY", None))

    def test_agent_position_reaches_database(self):
        # номер позиции от агента сохраняется — по нему график связывает
        # вход с выходом; старый агент его не шлёт, мусор отклоняется
        base = {"login": 777, "balance": 1, "equity": 1, "currency": "USD", "server": "S",
                "capital_hist": 1}
        row = {"ticket": 5, "time": "2026-09-01T10:00:00", "symbol": "XAUUSD", "side": "BUY",
               "volume": 0.02, "price": 2400, "profit": 0, "swap": 0, "commission": 0, "net": 0,
               "is_balance": False, "is_closing": False, "is_opening": True, "comment": ""}
        _, _, deals, _ = webhook_server._sync_payload({**base, "deals": [{**row, "position": 42}]})
        self.assertEqual(deals[0]["position"], 42)
        _, _, deals, _ = webhook_server._sync_payload({**base, "deals": [row]})
        self.assertIsNone(deals[0]["position"])
        for bad in (-1, "42", 1.5, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                webhook_server._sync_payload({**base, "deals": [{**row, "position": bad}]})
        db = store.open_db(":memory:")
        store.save_deals(db, 777, [{**row, "position": 42}])
        self.assertEqual(db.execute("SELECT position FROM deals").fetchone()[0], 42)

    def test_telegram_counts_emoji_as_two_caption_units(self):
        self.assertEqual(miniapp.telegram_length("😀" * 600), 1200)

    def test_same_login_on_another_server_is_reported(self):
        """DATA-02: один login на двух серверах — разные физические счета.

        Таблицы ключуются одним login, поэтому такой синк молча затрёт
        баланс и капитал чужого счёта. Пока брокер один, этого не бывает;
        защёлка должна сказать, когда появится второй.
        """
        db = store.open_db(":memory:")
        store.save_state(db, 500, 10.0, 10.0, "USD", "Broker-A")
        with self.assertLogs("store", level="ERROR") as logs:
            store.save_state(db, 500, 20.0, 20.0, "USD", "Broker-B")
        self.assertIn("DATA-02", logs.output[0])
        # тот же сервер — молчим, это обычный синк
        with patch.object(store.log, "error") as quiet:
            store.save_state(db, 500, 30.0, 30.0, "USD", "Broker-B")
            quiet.assert_not_called()

    def test_undelivered_portal_event_comes_back_next_round(self):
        """Сбой Telegram не должен съедать событие кабинета.

        unseen() отмечает событие до отправки (иначе повторный опрос
        продублировал бы сообщение), поэтому упавшая отправка означала
        потерю насовсем: ретраев в poll_portal нет.
        """
        db = partner.open_db(":memory:")
        rows = [{"id": "e1", "eventType": "DEPOSIT", "title": "Пополнение", "body": "+5"},
                {"id": "e2", "eventType": "TRADE_CLOSED", "title": "Сделка",
                 "templateVariables": {"amount": "0.25"}},
                {"id": "e3", "eventType": "DEPOSIT", "title": "Вывод", "body": "-7"}]
        partner.unseen(db, "portal", rows)          # первый запуск — только запоминаем

        async def dead_telegram(*a, **kw):
            raise RuntimeError("Telegram недоступен")

        partner.forget_seen(db, "portal", rows)     # событий никто не видел
        partner.unseen(db, "portal", [{"id": "seed"}])   # снимаем first_run
        asyncio.run(self._poll(db, rows, dead_telegram))

        # падение было на первом же событии: весь хвост вернулся в очередь,
        # доход из него не зачтён — иначе следующий круг прибавил бы его снова
        still = {r[0] for r in db.execute("SELECT id FROM seen WHERE kind='portal'")}
        self.assertEqual(still & {"e1", "e2", "e3"}, set())
        day = str(trades.clock().date())
        self.assertEqual(float(partner.kv_get(db, f"net_income:{day}", 0) or 0), 0.0)

        # а доход, посчитанный ДО падения, назад не возвращается: событие
        # дохода идёт первым, падаем на следующем за ним. Нужна чистая база:
        # _repeat_of_recent помнит отпечатки текстов от прошлого прогона
        db = partner.open_db(":memory:")
        partner.unseen(db, "portal", [{"id": "seed"}])
        asyncio.run(self._poll(db, [rows[1], rows[0]], dead_telegram))
        still = {r[0] for r in db.execute("SELECT id FROM seen WHERE kind='portal'")}
        self.assertIn("e2", still)          # зачтён — второй раз не придёт
        self.assertNotIn("e1", still)       # не доставлен — вернётся
        self.assertEqual(float(partner.kv_get(db, f"net_income:{day}", 0) or 0), 0.25)

    @staticmethod
    async def _poll(db, rows, sender):
        with patch.object(bot.ibportal, "notifications", return_value=rows), \
                patch.object(bot, "send", sender), patch.object(bot, "FOUNDER", "1"):
            return await bot.poll_portal(None, None, db, "1")

    def test_daily_digest_goes_only_to_the_founder(self):
        """Сводка про агентские машины — личное дело основателя.

        Раньше она рассылалась по всем владельцам счетов, и клиент не мог
        её выключить: ручка update_alerts — не его. Функция вложена в
        замыкание с бесконечным циклом, поэтому проверяем её исходник.
        """
        body = inspect.getsource(bot).split("async def daily_digest(")[1]
        body = body.split("\n        async def ")[0].split("\n        asyncio.")[0]
        self.assertIn("update_alerts_on(db)", body)      # уважает ручку
        self.assertIn("send(bot, chat_id,", body)        # шлём основателю
        self.assertNotIn('a["owner"]', body)             # и никому больше
        # знаменатель — все счета: иначе молчащий агент даёт «0 из 0»
        self.assertIn("total = len(all_accs)", body)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        accounts.PATH = str(Path(self.tmp.name) / "accounts.json")
        self.db = partner.open_db(str(Path(self.tmp.name) / "state.db"))
        partner.kv_set(self.db, "partner_link:1", "https://exfusion.ibportal.io/auth/register?e=test-link&a=1")
        self.tdb = store.open_db(str(Path(self.tmp.name) / "trades.db"))
        trades._db = self.tdb
        miniapp.logic.DEMO_ON = False
        miniapp._rates.clear()
        self.acc = {"owner":"1", "name":"SONIC", "strategy":"SONIC", "login":123,
                    "password":"never-in-api", "server":"Demo", "multiplier":24,
                    "cabinet":"CU1", "holder":"Test"}
        accounts.add(self.acc)
        store.save_state(self.tdb, 123, 2400, 2400, "USD", "Demo", 100)
        self.app = web.Application(client_max_size=22 * 1024 * 1024)
        self.app["db"], self.app["trades"] = self.db, self.tdb
        miniapp.setup(self.app)
        self.app.router.add_post("/agent/sync", webhook_server.agent_sync)
        self.app.router.add_post("/agent/candles", webhook_server.agent_candles)
        self.app.router.add_post("/agent/claim", webhook_server.agent_claim)
        self.app.router.add_post("/agent/role_change", webhook_server.agent_role_change)
        self.app.router.add_get("/agent/accounts", webhook_server.agent_accounts)
        self.app.router.add_post("/agent/heartbeat", webhook_server.agent_heartbeat)
        self.app.router.add_post("/agent/update_report", webhook_server.agent_update_report)
        self.app.router.add_get("/agent/update_status", webhook_server.agent_update_status)
        self.app.router.add_post("/agent/update_notify", webhook_server.agent_update_notify)
        self.app.router.add_get("/agent/machines_status", webhook_server.agent_machines_status)
        self.app.router.add_get("/status", webhook_server.status)
        self.app.router.add_route("*", "/hook/deposit", webhook_server.on_deposit)
        webhook_server.TOKEN = "agent-test"
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        trades._db = None
        self.db.close()
        self.tdb.close()
        self.tmp.cleanup()

    async def call(self, method, path, uid=1, **kwargs):
        return await self.client.request(method, path, headers={"X-Telegram-Init-Data":signed(uid)}, **kwargs)

    async def test_formatted_media_broadcast_and_duplicate_request(self):
        partner.kv_set(self.db, "guest:2", "1")
        calls = []

        class Session:
            def __init__(self, **kwargs): pass
            async def close(self): pass

        class Sender:
            def __init__(self, *args, **kwargs): pass
            async def send_photo(self, recipient, media, **kwargs):
                calls.append(("photo", recipient, kwargs.get("caption"), Path(media.path).exists()))
            async def send_message(self, recipient, text, **kwargs):
                calls.append(("message", recipient, text))

        def form(request_id):
            data = FormData()
            data.add_field("target", "2")
            data.add_field("text", "<b>Новости</b> " + "Т" * 1100)
            data.add_field("request_id", request_id)
            data.add_field("media", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 100),
                           filename="news.png", content_type="image/png")
            return data

        with patch.object(miniapp.logic, "AiohttpSession", Session), \
                patch.object(miniapp.logic, "Bot", Sender), \
                patch.object(miniapp.logic, "works", return_value=True):
            response = await self.call("POST", "/api/broadcast", data=form("broadcast-test-1"))
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["sent"], 1)
            self.assertEqual(calls[0], ("photo", "2", None, True))
            self.assertEqual(calls[1][0:2], ("message", "2"))
            repeat = await self.call("POST", "/api/broadcast", data=form("broadcast-test-1"))
            self.assertEqual(repeat.status, 200)
            self.assertEqual((await repeat.json())["sent"], 1)
            self.assertEqual(len(calls), 2)

    async def test_short_photo_caption_is_delivered_and_saved_in_inbox(self):
        partner.kv_set(self.db, "guest:2", "1")
        sent = []

        class Session:
            def __init__(self, **kwargs): pass
            async def close(self): pass

        class Sender:
            def __init__(self, *args, **kwargs): pass
            async def send_photo(self, recipient, media, **kwargs):
                sent.append((recipient, kwargs.get("caption")))

        form = FormData()
        form.add_field("target", "2")
        form.add_field("text", "<b>Привет</b> с картинкой")
        form.add_field("request_id", "broadcast-short-photo")
        form.add_field("media", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 100),
                       filename="news.png", content_type="image/png")
        with patch.object(miniapp.logic, "AiohttpSession", Session), \
                patch.object(miniapp.logic, "Bot", Sender), \
                patch.object(miniapp.logic, "works", return_value=True):
            response = await self.call("POST", "/api/broadcast", data=form)
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(sent, [("2", "<b>Привет</b> с картинкой")])
        inbox = await (await self.call("GET", "/api/notifications", uid=2)).json()
        self.assertEqual(inbox["unread"], 1)
        self.assertEqual(inbox["items"][0]["body"], "Привет с картинкой")

    async def test_broadcast_checks_telegram_before_claiming_request(self):
        partner.kv_set(self.db, "guest:2", "1")
        data = FormData()
        data.add_field("target", "2")
        data.add_field("text", "Проверка")
        data.add_field("request_id", "broadcast-offline")
        with patch.object(miniapp.logic, "works", return_value=False):
            response = await self.call("POST", "/api/broadcast", data=data)
        self.assertEqual(response.status, 503)
        self.assertIsNone(partner.kv_get(self.db, "mini_broadcast:broadcast-offline"))

    async def test_broadcast_retry_skips_delivered_media_and_recipient(self):
        partner.kv_set(self.db, "guest:2", "1")
        partner.kv_set(self.db, "guest:3", "1")
        calls = []
        fail_once = True

        class Session:
            def __init__(self, **kwargs): pass
            async def close(self): pass

        class Sender:
            def __init__(self, *args, **kwargs): pass
            async def send_photo(self, recipient, media, **kwargs):
                calls.append(("photo", recipient))
            async def send_message(self, recipient, body, **kwargs):
                nonlocal fail_once
                calls.append(("message", recipient))
                if recipient == "3" and fail_once:
                    fail_once = False
                    raise RuntimeError("temporary proxy failure")

        def form():
            data = FormData()
            data.add_field("target", "all")
            data.add_field("text", "Т" * 1100)
            data.add_field("request_id", "broadcast-retry")
            # Some mobile WebViews omit Content-Type; the signature is sufficient.
            data.add_field("media", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 100),
                           filename="news.png", content_type="application/octet-stream")
            return data

        with patch.object(miniapp.logic, "AiohttpSession", Session), \
                patch.object(miniapp.logic, "Bot", Sender), \
                patch.object(miniapp.logic, "works", return_value=True):
            first = await self.call("POST", "/api/broadcast", data=form())
            self.assertEqual(await first.json(), {"sent": 1, "failed": 1})
            retry = await self.call("POST", "/api/broadcast", data=form())
        self.assertEqual(await retry.json(), {"sent": 2, "failed": 0})
        self.assertEqual(calls.count(("photo", "2")), 1)
        self.assertEqual(calls.count(("photo", "3")), 1)
        self.assertEqual(calls.count(("message", "2")), 1)
        self.assertEqual(calls.count(("message", "3")), 2)

    async def test_notifications_are_private_deduplicated_and_readable(self):
        self.assertTrue(partner.record_notification(self.db, 1, "trade:123:1", "trades", "SONIC", "+12 $"))
        self.assertFalse(partner.record_notification(self.db, 1, "trade:123:1", "trades", "SONIC", "+12 $"))
        partner.record_notification(self.db, 2, "trade:456:1", "trades", "OTHER", "+99 $")
        own = await (await self.call("GET", "/api/notifications", uid=1)).json()
        self.assertEqual(own["unread"], 1)
        self.assertEqual([i["title"] for i in own["items"]], ["SONIC"])
        foreign = partner.notifications_for(self.db, 2)["items"][0]["id"]
        r = await self.call("POST", "/api/notifications", uid=1,
                            json={"action":"read","ids":[foreign]})
        self.assertEqual((await r.json())["unread"], 1)
        own_id = own["items"][0]["id"]
        r = await self.call("POST", "/api/notifications", uid=1,
                            json={"action":"read","ids":[own_id]})
        self.assertEqual((await r.json())["unread"], 0)
        self.assertEqual(partner.notifications_for(self.db, 2)["unread"], 1)

    async def test_oversize_photo_is_rejected_before_any_send(self):
        partner.kv_set(self.db, "guest:2", "1")
        form = FormData()
        form.add_field("target", "2")
        form.add_field("text", "Картинка")
        form.add_field("request_id", "broadcast-large-photo")
        form.add_field("media", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * (10 * 1024 * 1024)),
                       filename="large.png", content_type="image/png")
        response = await self.call("POST", "/api/broadcast", data=form)
        self.assertEqual(response.status, 400)
        self.assertIn("Фото до 10 МБ", (await response.json())["error"])
        self.assertIsNone(partner.kv_get(self.db, "mini_broadcast:broadcast-large-photo"))

    async def test_approximate_wallet_is_not_exposed_as_balance(self):
        data = await (await self.call("GET", "/api/bootstrap")).json()
        self.assertNotIn("wallets", data)
        response = await self.call("POST", "/api/actions",
                                   json={"action":"wallet_reset","cabinet":"CU1"})
        self.assertEqual(response.status, 403)

    async def test_no_auth_no_demo_backdoor(self):
        for path in ("/api/bootstrap", "/api/bootstrap?preview=1", "/api/accounts/123/report"):
            response = await self.client.get(path)
            self.assertEqual(response.status, 401)

    async def test_bootstrap_excludes_password_and_other_users(self):
        response = await self.call("GET", "/api/bootstrap")
        self.assertEqual(response.status, 200, await response.text())
        data = await response.json()
        self.assertEqual(data["totals"]["USD"]["capital"], 100)
        self.assertNotIn("never-in-api", json.dumps(data))
        self.assertNotIn("password", json.dumps(data))
        other = await self.call("GET", "/api/bootstrap", uid=2)
        self.assertEqual((await other.json())["accounts"], [])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_new_account_submission_is_saved_and_visible_to_owner(self):
        payload = {"name": "NEO", "login": 987654321, "password": "investor-secret",
                   "cabinet": "CU987"}
        response = await asyncio.wait_for(
            self.call("POST", "/api/accounts", uid=2, json=payload), timeout=3)
        self.assertEqual(response.status, 201, await response.text())
        saved = accounts.load(2)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["login"], payload["login"])
        self.assertEqual(saved[0]["password"], payload["password"])
        self.assertEqual(saved[0]["holder"], "")
        self.assertNotIn(payload["password"], Path(accounts.PATH).read_text(encoding="utf-8"))
        own = await (await self.call("GET", "/api/bootstrap", uid=2)).json()
        self.assertEqual([a["login"] for a in own["accounts"]], [payload["login"]])
        other = await (await self.call("GET", "/api/bootstrap")).json()
        self.assertNotIn(payload["login"], [a["login"] for a in other["accounts"]])
        second = await self.call("POST", "/api/accounts", uid=2,
                                 json={"name": "SONIC", "login": 987654322,
                                       "password": "second-secret", "cabinet": "CU987"})
        self.assertEqual(second.status, 201, await second.text())
        self.assertEqual({a["cabinet"] for a in accounts.load(2)}, {"CU987"})
        duplicate_in_same_cabinet = await self.call("POST", "/api/accounts", uid=2,
            json={"name": "NEO", "login": 987654323,
                  "password": "third-secret", "cabinet": "CU987"})
        self.assertEqual(duplicate_in_same_cabinet.status, 400)
        same_name_other_cabinet = await self.call("POST", "/api/accounts", uid=2,
            json={"name": "NEO", "login": 987654324,
                  "password": "fourth-secret", "cabinet": "CU988"})
        self.assertEqual(same_name_other_cabinet.status, 201,
                         await same_name_other_cabinet.text())
        neo_accounts = [a for a in accounts.load(2) if a["strategy"] == "NEO"]
        self.assertEqual(len(neo_accounts), 2)
        self.assertEqual({a["cabinet"] for a in neo_accounts}, {"CU987", "CU988"})
        self.assertEqual(len({a["name"] for a in neo_accounts}), 2)
        rename_other_cabinet = await self.call("PATCH", "/api/accounts/987654324", uid=2,
            json={"name": "SONIC"})
        self.assertEqual(rename_other_cabinet.status, 200, await rename_other_cabinet.text())
        self.assertEqual({(a["login"], a["cabinet"], a["strategy"])
                          for a in accounts.load(2) if a["strategy"] == "SONIC"},
                         {(987654322, "CU987", "SONIC"), (987654324, "CU988", "SONIC")})
        rename_back = await self.call("PATCH", "/api/accounts/987654324", uid=2,
            json={"name": "NEO"})
        self.assertEqual(rename_back.status, 200, await rename_back.text())
        rename_same_cabinet = await self.call("PATCH", "/api/accounts/987654322", uid=2,
            json={"name": "NEO"})
        self.assertEqual(rename_same_cabinet.status, 400)
        self.assertEqual(next(a for a in accounts.load(2) if a["login"] == 987654322)["strategy"], "SONIC")
        removed = await self.call("DELETE", "/api/accounts/987654321", uid=2)
        self.assertEqual(removed.status, 200)
        self.assertEqual([a["login"] for a in accounts.load(2) if a["strategy"] == "NEO"],
                         [987654324])

    async def test_invited_user_onboarding_steps_follow_order(self):
        partner.kv_set(self.db, "guest_by:2", "1")
        initial = await (await self.call("GET", "/api/bootstrap", uid=2)).json()
        self.assertTrue(initial["onboarding"]["needed"])
        self.assertEqual(initial["onboarding"]["registration_url"],
                         partner.kv_get(self.db, "partner_link:1"))
        premature = await self.call("POST", "/api/onboarding", uid=2,
                                    json={"step": "verified", "done": True})
        self.assertEqual(premature.status, 409)
        for step in ("registered", "verified", "broker_account"):
            response = await self.call("POST", "/api/onboarding", uid=2,
                                       json={"step": step, "done": True})
            self.assertEqual(response.status, 200, await response.text())
            self.assertTrue((await response.json())["progress"][step])

    async def test_mt5_password_encrypted_at_rest_and_legacy_migration(self):
        path = Path(accounts.PATH)
        self.assertNotIn("never-in-api", path.read_text(encoding="utf-8"))
        self.assertEqual(accounts.load(1)[0]["password"], "never-in-api")
        path.write_text(json.dumps([self.acc]), encoding="utf-8")
        self.assertTrue(accounts.migrate_passwords())
        self.assertNotIn("never-in-api", path.read_text(encoding="utf-8"))
        self.assertEqual(accounts.load(1)[0]["password"], "never-in-api")

    async def test_cross_user_and_privilege_checks(self):
        for method,path,body in [("GET","/api/accounts/123/report",None),
                                  ("PATCH","/api/accounts/123",{"enabled":False}),
                                  ("DELETE","/api/accounts/123",None),
                                  ("GET","/api/admin",None),
                                  ("POST","/api/actions",{"action":"restart","login":123}),
                                  ("POST","/api/guests/1",{"action":"share","logins":[123]})]:
            r = await self.call(method,path,uid=2,json=body)
            self.assertIn(r.status,(403,404),await r.text())
        # ссылка не несёт счетов: без своей партнёрской ссылки её и не выдают
        r = await self.call("POST","/api/invites",uid=2,json={"logins":[123]})
        self.assertEqual(r.status,428)

    async def test_revoked_user_cannot_reuse_valid_telegram_session(self):
        partner.kv_set(self.db, "left:1", "1")
        r = await self.call("GET", "/api/bootstrap")
        self.assertEqual(r.status, 403)

    async def test_preferences_sync_and_invalid_values(self):
        r = await self.call("PATCH", "/api/accounts/123", json={"enabled":False,"notify":{"trades":False}})
        self.assertEqual(r.status,200)
        self.assertFalse(accounts.load(1)[0]["enabled"])
        self.assertFalse(accounts.notifies(accounts.load(1)[0], "trades"))
        for body in ({"base":"NaN"},{"enabled":"false"},{"owner":"2"},{"notify":{"trades":"false"}}):
            r = await self.call("PATCH", "/api/accounts/123", json=body)
            self.assertEqual(r.status,400)

    async def test_guessing_existing_account_does_not_grant_access(self):
        r = await self.call("POST", "/api/accounts",uid=2,
                            json={"name":"stolen","login":123,"password":"wrong","server":"Demo"})
        self.assertEqual(r.status,409)
        self.assertEqual(accounts.load(2),[])

    async def test_demo_protected_and_excluded_from_money(self):
        accounts.add({**self.acc,"login":456,"name":"Demo","strategy":"Demo","demo":True})
        store.save_state(self.tdb,456,240000,240000,"USD","Demo",10000)
        r = await self.call("GET","/api/bootstrap")
        self.assertEqual((await r.json())["totals"]["USD"]["capital"],100)
        for method,body in (("DELETE",None),("PATCH",{"base":100}),("PATCH",{"name":"x"})):
            r = await self.call(method,"/api/accounts/456",json=body)
            self.assertEqual(r.status,403)

    async def test_demo_login_is_always_a_number_in_api(self):
        # Production data: the shared demo copies keep "login" as a string, and
        # the strict === lookup in the UI made «Настроить» a silent no-op.
        accounts.add({**self.acc, "login": "51164384", "name": "Demo", "strategy": "", "demo": True})
        store.save_state(self.tdb, 51164384, 240000, 240000, "USD", "Demo", 10000)
        boot = await (await self.call("GET", "/api/bootstrap")).json()
        for a in boot["accounts"]:
            self.assertIs(type(a["login"]), int, a)

    async def test_demo_settings_button_saves_for_owner_and_for_guest(self):
        # Exactly what the «Настроить» button sends for the copy-trading account.
        ui = {"enabled": False, "notify": {"all": True, "trades": False,
                                            "deposits": True, "withdrawals": True}}
        accounts.add({**self.acc, "login": 456, "name": "Demo", "strategy": "Demo", "demo": True})
        store.save_state(self.tdb, 456, 240000, 240000, "USD", "Demo", 10000)
        miniapp.logic.DEMO_ON = True
        miniapp.logic.DEMO_LOGIN = 456
        try:
            for uid in (1, 2):      # 1 owns the record, 2 only sees the public copy
                partner.kv_set(self.db, "guest:2", "1")
                r = await self.call("PATCH", "/api/accounts/456", uid=uid, json=ui)
                self.assertEqual(r.status, 200, f"uid={uid}: {await r.text()}")
                boot = await (await self.call("GET", "/api/bootstrap", uid=uid)).json()
                demo = next(a for a in boot["accounts"] if a["demo"])
                self.assertFalse(demo["enabled"], f"uid={uid}")
                self.assertFalse(demo["notify"]["trades"], f"uid={uid}")
        finally:
            miniapp.logic.DEMO_ON = False

    async def test_report_and_pagination(self):
        now = trades.clock()
        deals = [{"ticket":i,"time":now,"symbol":"XAUUSD","side":"buy","net":1,
                  "profit":1,"swap":0,"commission":0,"volume":0.1,"is_closing":True,
                  "is_opening":False,"is_balance":False} for i in range(1,61)]
        store.save_deals(self.tdb,123,deals)
        r = await self.call("GET","/api/accounts/123/report?period=month")
        self.assertEqual(r.status,200,await r.text())
        data = await r.json()
        self.assertEqual(len(data["deals"]),50)
        self.assertTrue(data["has_more"])
        self.assertEqual(data["summary"]["count"],60)
        self.assertAlmostEqual(data["summary"]["net_income"],42)
        self.assertAlmostEqual(data["deals"][0]["pct_capital"], 0.7179)
        r = await self.call("GET","/api/accounts/123/report?period=month&offset=50")
        self.assertEqual(len((await r.json())["deals"]),10)

    async def test_trade_insights_separate_current_and_previous_week(self):
        previous = miniapp.logic.period("lastweek")[1] + timedelta(days=1)
        current = trades.clock()  # часы брокера, как и period() — иначе тест плывёт у границы недели
        deals = [{"ticket": index, "time": moment, "symbol": "XAUUSD", "side": "buy",
                  "net": amount, "profit": amount, "swap": 0, "commission": 0,
                  "volume": .1, "is_closing": True, "is_opening": False,
                  "is_balance": False}
                 for index, moment, amount in ((1, previous, 10), (2, current, 20))]
        store.save_deals(self.tdb, 123, deals)
        response = await self.call("GET", "/api/accounts/123/report?period=all")
        self.assertEqual(response.status, 200, await response.text())
        data = await response.json()
        self.assertEqual(data["insights"]["week"]["count"], 1)
        self.assertEqual(data["insights"]["lastweek"]["count"], 1)
        self.assertEqual(data["insights"]["all"]["count"], 2)
        self.assertEqual(data["day_totals"][current.date().isoformat()]["count"], 1)

    async def test_overview_report_combines_accounts_and_excludes_demo(self):
        accounts.add({**self.acc, "login": 456, "name": "NEO", "strategy": "NEO"})
        accounts.add({**self.acc, "login": 789, "name": "Demo", "strategy": "Demo", "demo": True})
        store.save_state(self.tdb, 456, 4800, 4800, "USD", "Demo", 200)
        store.save_state(self.tdb, 789, 240000, 240000, "USD", "Demo", 10000)
        now = trades.clock()
        for login, amount in ((123, 10), (456, 20), (789, 1000)):
            store.save_deals(self.tdb, login, [{"ticket": login, "time": now,
                "symbol": "XAUUSD", "side": "buy", "net": amount, "profit": amount,
                "swap": 0, "commission": 0, "volume": .1, "is_closing": True,
                "is_opening": False, "is_balance": False}])
        r = await self.call("GET", "/api/overview/report?period=month&currency=USD")
        self.assertEqual(r.status, 200, await r.text())
        data = await r.json()
        self.assertEqual(data["accounts"], 2)
        self.assertEqual(data["summary"]["count"], 2)
        self.assertAlmostEqual(data["summary"]["net_income"], 21)
        self.assertAlmostEqual(sum(point["value"] for point in data["chart"]), 21)
        home = await (await self.call("GET", "/api/bootstrap")).json()
        self.assertAlmostEqual(home["totals"]["USD"]["today"], 21)
        self.assertAlmostEqual(data["summary"]["pct_capital"],
                               round(21 / home["totals"]["USD"]["capital"] * 100, 3))

    async def test_shared_observation_does_not_count_as_guests_capital(self):
        accounts.share([123], 1, 2)
        home = await (await self.call("GET", "/api/bootstrap", uid=2)).json()
        observed = next(a for a in home["accounts"] if a["login"] == 123)
        self.assertTrue(observed["shared"])
        self.assertEqual(home["totals"], {})
        report = await self.call("GET", "/api/overview/report?period=all&currency=USD", uid=2)
        self.assertEqual(report.status, 200, await report.text())
        data = await report.json()
        self.assertEqual(data["accounts"], 0)
        self.assertEqual(data["summary"]["net_income"], 0)

    async def test_week_report_survives_archived_month_at_its_start(self):
        # понедельник этой недели может лежать в уже свёрнутом (архивном) месяце —
        # report_archive не должен ронять весь отчёт 422, а просто не учитывать
        # архивный месяц, если он не укладывается в запрошенный период целиком
        today = trades.clock().date()
        month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        self.tdb.execute("INSERT INTO months (login, month, trades, gross, platform, wins, losses, growth) "
                         "VALUES (123, ?, 3, 30, -9, 2, 1, 1.0)", (month,))
        self.tdb.commit()
        r = await self.call("GET", "/api/accounts/123/report?period=week")
        self.assertEqual(r.status, 200, await r.text())
        r = await self.call("GET", "/api/overview/report?period=week&currency=USD")
        self.assertEqual(r.status, 200, await r.text())

    async def test_price_chart_returns_candles_and_trade_markers(self):
        # полдень сегодняшних суток, а не «сейчас»: период today отрезает всё
        # до полуночи, и получасом после неё свечи «30 минут назад» попадали
        # во вчера — тест падал, а с ним и выкладка с откатом (deploy_miniapp
        # гоняет набор с check=True). Тот же дефект, что findings.md №9
        now = trades.clock().replace(hour=12, minute=0, second=0, microsecond=0)
        store.save_candles(self.tdb, [
            {"time": (now - timedelta(minutes=30)).isoformat(), "open": 2400, "high": 2405, "low": 2398, "close": 2402},
            {"time": (now - timedelta(minutes=15)).isoformat(), "open": 2402, "high": 2410, "low": 2401, "close": 2408},
        ])
        # у брокера тикеры с суффиксом (XAUUSD.f) — сопоставление идёт по
        # базовому имени, иначе маркеры сделок пропадают с графика
        store.save_deals(self.tdb, 123, [
            {"ticket": 801, "time": now - timedelta(minutes=20), "symbol": "XAUUSD.f", "side": "buy",
             "price": 2403.5, "net": 0, "profit": 0, "swap": 0, "commission": 0, "volume": 0.1,
             "is_closing": False, "is_opening": True, "is_balance": False},
            {"ticket": 802, "time": now - timedelta(minutes=5), "symbol": "XAUUSD.f", "side": "buy",
             "price": 2407.2, "net": 12, "profit": 12, "swap": 0, "commission": 0, "volume": 0.1,
             "is_closing": True, "is_opening": False, "is_balance": False},
            {"ticket": 803, "time": now - timedelta(minutes=5), "symbol": "EURUSD.f", "side": "buy",
             "price": 1.1, "net": 3, "profit": 3, "swap": 0, "commission": 0, "volume": 0.1,
             "is_closing": True, "is_opening": False, "is_balance": False},
        ])
        r = await self.call("GET", "/api/accounts/123/candles?period=today")
        self.assertEqual(r.status, 200, await r.text())
        data = await r.json()
        self.assertEqual(data["symbol"], trades.CHART_SYMBOL)
        self.assertEqual(len(data["candles"]), 2)
        self.assertEqual(data["candles"][0]["close"], 2402)
        # только сделки золота и только вход/выход — EURUSD и баланс отсеяны
        self.assertEqual({m["kind"] for m in data["trades"]}, {"in", "out"})
        self.assertEqual(len(data["trades"]), 2)

    async def test_price_chart_hides_candles_older_than_retention(self):
        now = trades.clock()
        store.save_candles(self.tdb, [
            {"time": (now - timedelta(days=store.CANDLE_KEEP_DAYS + 5)).isoformat(),
             "open": 1, "high": 1, "low": 1, "close": 1},
        ])
        r = await self.call("GET", "/api/accounts/123/candles?period=all")
        self.assertEqual(r.status, 200, await r.text())
        self.assertEqual((await r.json())["candles"], [])

    async def test_all_time_report_accepts_nullable_archive_counts(self):
        self.tdb.execute("INSERT INTO months (login, month, trades, gross, platform, wins, losses, growth) "
                         "VALUES (123, '2026-07', 2, 10, NULL, NULL, NULL, 1.0)")
        self.tdb.commit()
        r = await self.call("GET", "/api/accounts/123/report?period=all")
        self.assertEqual(r.status, 200, await r.text())
        data = await r.json()
        self.assertEqual(data["summary"]["count"], 2)
        self.assertEqual(data["summary"]["wins"], 0)
        self.assertAlmostEqual(data["summary"]["net_income"], 7)
        r = await self.call("GET", "/api/overview/report?period=all&currency=USD")
        self.assertEqual(r.status, 200, await r.text())
        self.assertAlmostEqual((await r.json())["summary"]["net_income"], 7)

    async def test_month_percent_uses_capital_of_that_month(self):
        # прибыль заработана на капитале 100, потом капитал вывели почти в ноль:
        # процент месяца должен остаться к капиталу того месяца, а не делиться
        # на сегодняшний остаток и превращаться в тысячи процентов
        # growth NULL — как у старых свёрток на сервере (июнь 2026): процент
        # считается запасным путём, к капиталу на конец месяца. Август хранит
        # свой процент — он и должен показываться, как в ROI карточки
        self.tdb.execute("INSERT INTO months (login, month, trades, gross, platform, wins, losses, growth) "
                         "VALUES (123, '2026-07', 2, 10, 0, 2, 0, NULL)")
        self.tdb.execute("INSERT INTO months (login, month, trades, gross, platform, wins, losses, growth) "
                         "VALUES (123, '2026-08', 1, 5, 0, 1, 0, 4.25)")
        self.tdb.commit()
        store.save_deals(self.tdb, 123, [
            {"ticket": 90, "time": "2026-08-02T10:00:00", "is_balance": True, "is_closing": False,
             "is_opening": False, "net": -2376.0, "volume": 0, "comment": "Withdrawal"}])
        store.save_state(self.tdb, 123, 24, 24, "USD", "Demo", 100)
        data = await (await self.call("GET", "/api/accounts/123/report?period=all")).json()
        july = next(m for m in data["months"] if m["month"] == "2026-07")
        self.assertAlmostEqual(july["net"], 7)
        self.assertAlmostEqual(july["pct_capital"], 7.0, places=3)
        august = next(m for m in data["months"] if m["month"] == "2026-08")
        self.assertAlmostEqual(august["pct_capital"], 4.25, places=3)

    async def test_card_and_dynamics_month_percent_agree(self):
        # пополнение посреди месяца: сделка до него заработана на меньшем
        # капитале. Карточка «Этот месяц» и «Динамика» за месяц раньше считали
        # по-разному (сделка к капиталу её момента против суммы к сегодняшнему)
        now = trades.clock()
        first = now.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
        store.save_deals(self.tdb, 123, [
            {"ticket": 501, "time": first, "symbol": "XAUUSD", "side": "buy", "net": 48,
             "profit": 48, "swap": 0, "commission": 0, "volume": 0.1,
             "is_closing": True, "is_opening": False, "is_balance": False},
            {"ticket": 502, "time": first + timedelta(minutes=5), "is_balance": True,
             "is_closing": False, "is_opening": False, "net": 2400.0, "volume": 0,
             "comment": "Deposit"},
            {"ticket": 503, "time": first + timedelta(minutes=10), "symbol": "XAUUSD", "side": "buy",
             "net": 48, "profit": 48, "swap": 0, "commission": 0, "volume": 0.1,
             "is_closing": True, "is_opening": False, "is_balance": False}])
        store.save_state(self.tdb, 123, 4896, 4896, "USD", "Demo", 200)
        data = await (await self.call("GET", "/api/accounts/123/report?period=month")).json()
        acc = next(a for a in accounts.load(1) if int(a["login"]) == 123)
        card = bot.account_totals(acc)["month_pct"]
        self.assertAlmostEqual(data["summary"]["pct_capital"], card, places=2)
        self.assertAlmostEqual(data["insights"]["month"]["pct_capital"], card, places=2)

    async def test_invites_shared_accounts_and_revoke(self):
        partner.kv_set(self.db, "partner_link:1", "")
        denied = await self.call("POST", "/api/invites", json={"logins": [123]})
        self.assertEqual(denied.status, 428)
        self.assertEqual(miniapp.logic.invite_list(self.db, 1), [])
        partner.kv_set(self.db, "partner_link:1", "https://exfusion.ibportal.io/auth/register?e=test-link&a=1")
        r = await self.call("POST","/api/invites",json={})
        self.assertEqual(r.status,200)
        token = (await r.json())["url"].split("start=")[1]
        self.assertIsNotNone(miniapp.logic.invite_get(self.db,token))
        # ссылка одна и та же, сколько её ни запрашивай
        again = await self.call("POST","/api/invites",json={})
        self.assertEqual((await again.json())["url"].split("start=")[1], token)
        r = await self.call("DELETE","/api/invites/"+token,uid=2)
        self.assertEqual(r.status,404)
        # «обновить»: прежняя гаснет, вместо неё сразу новая
        renewed = await self.call("DELETE","/api/invites/"+token)
        fresh = (await renewed.json())["url"].split("start=")[1]
        self.assertNotEqual(fresh, token)
        self.assertIsNone(miniapp.logic.invite_get(self.db,token))
        self.assertIsNotNone(miniapp.logic.invite_get(self.db,fresh))
        accounts.share([123],1,2)
        accounts.share([123],1,2)
        self.assertEqual(len(accounts.load(2)),1)
        r = await self.call("POST","/api/actions",uid=2,json={"action":"restart","login":123})
        self.assertEqual(r.status,403)

    async def test_personal_link_survives_use_and_stale_cleanup(self):
        token = miniapp.logic.invite_personal(self.db, 1)
        inv = miniapp.logic.invite_get(self.db, token)
        self.assertTrue(inv["personal"])
        self.assertEqual(inv["logins"], [])
        # вошёл человек — ссылка та же и действует для следующего
        inv["uses"] = 5
        miniapp.logic.invite_save(self.db, token, inv)
        self.assertEqual(miniapp.logic.invite_check(self.db, 7, token, set())[0], "ok")
        self.assertEqual(miniapp.logic.invite_personal(self.db, 1), token)

    async def test_owner_can_open_own_accounts_to_a_guest_but_not_shared_or_demo(self):
        partner.kv_set(self.db, "guest:2", "1")
        partner.kv_set(self.db, "guest_by:2", "1")
        r = await self.call("POST", "/api/guests/2", json={"action": "share", "logins": [123]})
        self.assertEqual(r.status, 200, await r.text())
        self.assertEqual([a["login"] for a in accounts.load(2)], [123])
        self.assertEqual(accounts.load(2)[0].get("shared_by"), "1")
        # чужой гость и чужой счёт недоступны
        self.assertEqual((await self.call("POST", "/api/guests/2", uid=3,
                                          json={"action": "share", "logins": [123]})).status, 403)
        accounts.add({**self.acc, "owner": "3", "login": 999, "name": "Other", "strategy": "Other"})
        self.assertIn((await self.call("POST", "/api/guests/2", json={"action": "share", "logins": [999]})).status,
                      (403, 404))

    async def test_moves_hide_fee_rows_pair_reinvest_and_total_the_commission(self):
        store.save_deals(self.tdb, 123, [
            {"ticket": 1, "time": "2026-09-10T10:00:00", "is_balance": True, "is_closing": False,
             "is_opening": False, "net": 4800.0, "volume": 0, "comment": "Deposit"},
            {"ticket": 2, "time": "2026-09-11T00:00:00", "is_balance": True, "is_closing": False,
             "is_opening": False, "net": -15.0, "volume": 0, "comment": "PF Deduction"},
            {"ticket": 3, "time": "2026-09-12T12:00:00", "is_balance": True, "is_closing": False,
             "is_opening": False, "net": -6.0, "volume": 0, "comment": "Adjust-6.00"},
            {"ticket": 4, "time": "2026-09-12T12:00:00", "is_balance": True, "is_closing": False,
             "is_opening": False, "net": 144.0, "volume": 0, "comment": "Upgrade-144.00"},
            {"ticket": 5, "time": "2026-09-14T00:00:00", "is_balance": True, "is_closing": False,
             "is_opening": False, "net": -5.0, "volume": 0, "comment": "PF Deduction"},
        ])
        r = await self.call("GET", "/api/accounts/123/report?period=all&kind=moves")
        self.assertEqual(r.status, 200, await r.text())
        data = await r.json()
        kinds = {d["ticket"]: d["move"] for d in data["deals"]}
        self.assertEqual(kinds, {4: "reinvest", 1: "deposit"})
        self.assertEqual(data["commission_total"], 20.0)
        self.assertEqual(data["commission_count"], 2)
        reinvest = next(d for d in data["deals"] if d["ticket"] == 4)
        self.assertAlmostEqual(reinvest["capital_now"] - reinvest["capital_was"], 6.0)
        self.assertEqual(len(data["capital_series"]), 3)
        self.assertNotIn("PF Deduction", " ".join(str(d.get("comment")) for d in data["deals"]))

    async def test_reinvest_split_by_a_second_is_one_move(self):
        moment = trades.clock() - timedelta(days=1)
        balance = {"is_balance": True, "is_closing": False, "is_opening": False, "volume": 0}
        store.save_deals(self.tdb, 123, [
            {**balance, "ticket": 902, "time": moment.isoformat(), "net": -5.0, "comment": "Adjust-5.00"},
            {**balance, "ticket": 903, "time": (moment + timedelta(seconds=1)).isoformat(),
             "net": 120.0, "comment": "Upgrade-120.00"}])
        r = await self.call("GET", "/api/accounts/123/report?period=all&kind=moves")
        data = await r.json()
        self.assertEqual([(d["ticket"], d["move"]) for d in data["deals"]], [(903, "reinvest")])
        # итоги дня для движений не считаются: интерфейс их не показывает
        self.assertEqual(data["day_totals"], {})

    async def test_capital_steps_reach_every_page_and_match_capital_around(self):
        start = trades.clock() - timedelta(days=3)
        store.save_deals(self.tdb, 123, [
            {"ticket": 1000 + i, "time": (start + timedelta(minutes=i)).isoformat(), "is_balance": True,
             "is_closing": False, "is_opening": False, "volume": 0,
             "net": 240.0 if i % 3 else -48.0, "comment": "Deposit" if i % 3 else "Withdrawal"}
            for i in range(320)])
        r = await self.call("GET", "/api/accounts/123/report?period=all&kind=moves&offset=300")
        data = await r.json()
        self.assertEqual(len(data["deals"]), 20)
        self.assertTrue(all("capital_was" in d for d in data["deals"]), data["deals"][-1])
        self.assertEqual(len(data["capital_series"]), 321)
        trades.use(accounts.load(1)[0])
        moves = miniapp.moves_list(trades.fetch(datetime(2000, 1, 1), trades.clock() + timedelta(days=1)))
        steps = miniapp.capital_steps(moves)
        self.assertEqual(len(steps), 320)
        for row in moves[::41]:
            with self.subTest(ticket=row["ticket"]):
                was, became = trades.capital_around(row)
                self.assertAlmostEqual(steps[row["ticket"]][0], was, places=6)
                self.assertAlmostEqual(steps[row["ticket"]][1], became, places=6)

    async def test_status_command_counts_archived_months_like_the_report_head(self):
        self.tdb.execute("INSERT INTO months (login, month, trades, gross, platform, wins, losses) "
                         "VALUES (123, ?, 5, 100.0, 0, 4, 1)", (trades.REPORT_FROM.strftime("%Y-%m"),))
        self.tdb.commit()
        trades.use(accounts.load(1)[0])
        status = trades.fmt_status("USD")
        self.assertIn("Заработано <b>+70.00$</b>", status)
        self.assertIn("всего <b>+70.00", trades.fmt_head("USD"))

    async def test_broker_comment_cannot_break_notification_markup(self):
        trades.use(accounts.load(1)[0])
        row = {"ticket": 7, "time": trades.clock(), "is_balance": True, "is_closing": False,
               "is_opening": False, "net": -3.0, "comment": "Fee <promo> & co", "symbol": "", "side": ""}
        text = trades.fmt_notification(row, "USD")
        self.assertIn("Fee &lt;promo&gt; &amp; co", text)

    async def test_site_deposits_are_listed_per_cabinet(self):
        partner.site_move_add(self.db, "CU1", "deposit", 250.0, "USD")
        partner.site_move_add(self.db, "CU2", "deposit", 999.0, "USD")
        store.save_deals(self.tdb, 123, [
            {"ticket": 1, "time": "2026-09-10T10:00:00", "is_balance": True, "is_closing": False,
             "is_opening": False, "net": 2400.0, "volume": 0, "comment": "Deposit"}])
        r = await self.call("GET", "/api/accounts/123/report?period=all&kind=moves")
        moves = (await r.json())["site_moves"]
        self.assertEqual([(m["kind"], m["amount"]) for m in moves], [("deposit", 250.0)])

    async def test_pf_deduction_is_not_shown_in_the_event_feed(self):
        partner.record_notification(self.db, 1, "trade:123:1", "withdrawals", "SONIC · Вывод",
                                    "Плата платформы\nPF Deduction")
        partner.record_notification(self.db, 1, "trade:123:2", "trades", "SONIC · Сделка", "+1.00 $")
        feed = partner.notifications_for(self.db, 1)
        self.assertEqual([i["title"] for i in feed["items"]], ["SONIC · Сделка"])
        self.assertEqual(feed["unread"], 1)

    async def test_revoking_guest_preserves_their_personal_accounts(self):
        partner.kv_set(self.db, "guest:2", "1")
        partner.kv_set(self.db, "guest_by:2", "1")
        accounts.share([123], 1, 2)
        accounts.add({**self.acc, "owner":"2", "login":789, "name":"My account",
                      "strategy":"My account"})
        response = await self.call("POST", "/api/guests/2", json={"action":"revoke"})
        self.assertEqual(response.status, 200)
        self.assertEqual([a["login"] for a in accounts.load(2)], [789])
        self.assertIsNone(partner.kv_get(self.db, "guest_by:2"))
        self.assertEqual(partner.kv_get(self.db, "guest:2"), "1")
        self.assertEqual((await self.call("GET", "/api/bootstrap", uid=2)).status, 200)

    async def test_inviter_cannot_take_guest_owned_account_with_same_login(self):
        partner.kv_set(self.db, "guest:2", "1")
        partner.kv_set(self.db, "guest_by:2", "1")
        accounts.add({**self.acc, "owner":"2", "name":"Independently added",
                      "password":"different-investor-password"})
        after_restart = web.Application()
        after_restart["db"] = self.db
        miniapp.setup(after_restart)
        self.assertIsNone(accounts.load(2)[0].get("shared_by"))
        response = await self.call("POST", "/api/guests/2", json={"action":"take", "login":123})
        self.assertEqual(response.status, 403)
        self.assertEqual(accounts.load(2)[0]["name"], "Independently added")

    async def test_ambiguous_legacy_copy_needs_review_before_revoke(self):
        partner.kv_set(self.db, "guest:2", "1")
        partner.kv_set(self.db, "guest_by:2", "1")
        accounts.add({**self.acc, "owner":"2", "name":"Old copy"})
        after_restart = web.Application()
        after_restart["db"] = self.db
        miniapp.setup(after_restart)
        self.assertEqual(accounts.load(2)[0].get("shared_origin"), "inferred")
        response = await self.call("POST", "/api/guests/2", json={"action":"revoke"})
        self.assertEqual(response.status, 409)
        self.assertEqual(len(accounts.load(2)), 1)
        self.assertEqual(partner.kv_get(self.db, "guest_by:2"), "1")

    async def test_orphaned_inferred_copy_does_not_block_revoke(self):
        # Same ambiguous copy as above, but the owner has since deleted their
        # own side of the login — nothing left to confuse it with, so it
        # must not hold a guest with 0 visible accounts hostage forever.
        partner.kv_set(self.db, "guest:2", "1")
        partner.kv_set(self.db, "guest_by:2", "1")
        accounts.add({**self.acc, "owner":"2", "name":"Old copy"})
        after_restart = web.Application()
        after_restart["db"] = self.db
        miniapp.setup(after_restart)
        self.assertEqual(accounts.load(2)[0].get("shared_origin"), "inferred")
        accounts.remove_login(self.acc["login"], 1)
        self.assertEqual(accounts.load(1), [])
        response = await self.call("POST", "/api/guests/2", json={"action":"revoke"})
        self.assertEqual(response.status, 200)
        self.assertEqual(accounts.load(2), [])
        self.assertIsNone(partner.kv_get(self.db, "guest_by:2"))

    async def test_inferred_demo_copy_does_not_block_revoke(self):
        # Боевой случай: у гостя всего одна запись — копия общего демо-счёта,
        # помеченная inferred старым кодом. В интерфейсе он «0 счетов», а
        # отзыв падал с 409: демо есть у каждого гостя и спорить о его
        # происхождении не о чем.
        partner.kv_set(self.db, "guest:2", "1")
        partner.kv_set(self.db, "guest_by:2", "1")
        demo = {**self.acc, "login": 555, "name": "Demo", "strategy": "Demo", "demo": True}
        accounts.add(demo)
        accounts.add({**demo, "owner": "2", "shared_by": "1", "shared_origin": "inferred"})
        response = await self.call("POST", "/api/guests/2", json={"action": "revoke"})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(accounts.load(2), [])
        self.assertIsNone(partner.kv_get(self.db, "guest_by:2"))
        # у пригласившего собственный демо-счёт остался нетронутым
        self.assertEqual([int(a["login"]) for a in accounts.load(1)], [123, 555])

    async def test_fenced_sync_does_not_mutate_data(self):
        coordination.claim(self.db,"main","session-aaaaaaaaaaaaaaaa","primary")
        r = await self.client.post("/agent/sync",headers={"X-Token":"agent-test"},
                                   json={"login":123,"balance":0,"host":"reserve","session":"session-bbbbbbbbbbbbbbbb"})
        self.assertEqual(r.status,409)
        self.assertEqual(store.get_state(self.tdb,123)["balance"],2400)

    async def test_sync_rejects_entire_invalid_packet_without_acking_command(self):
        coordination.claim(self.db, "main", "session-aaaaaaaaaaaaaaaa", "primary")
        store.set_command(self.tdb, 123, "restart_terminal")
        deal = {"ticket": 701, "time": "2026-09-17T09:00:00", "symbol": "XAUUSD",
                "side": "BUY", "volume": .1, "price": 3000, "profit": 12,
                "swap": 0, "commission": 0, "net": 12, "is_balance": False,
                "is_closing": True, "is_opening": False, "comment": ""}
        packet = {"login":123, "balance":2500, "equity":2500, "currency":"USD",
                  "server":"Demo", "capital_hist":100, "deals":[deal],
                  "command_done":True, "host":"main", "session":"session-aaaaaaaaaaaaaaaa"}
        for broken in ({**deal, "ticket":None}, {**deal, "ticket":702, "net":"NaN"},
                       {**deal, "ticket":702, "time":"bad"},
                       {**deal, "ticket":702, "is_closing":True, "is_opening":True}):
            r = await self.client.post("/agent/sync", headers={"X-Token":"agent-test"},
                                       json={**packet, "deals":[deal, broken]})
            self.assertEqual(r.status, 400, await r.text())
            self.assertEqual(store.get_state(self.tdb,123)["balance"], 2400)
            self.assertEqual(store.last_ticket(self.tdb,123), 0)
            self.assertEqual(store.get_command(self.tdb,123), "restart_terminal")

        r = await self.client.post("/agent/sync", headers={"X-Token":"agent-test"}, json=packet)
        self.assertEqual(r.status, 200, await r.text())
        self.assertEqual((await r.json())["new"], 1)
        self.assertEqual(store.get_state(self.tdb,123)["balance"], 2500)
        self.assertEqual(store.last_ticket(self.tdb,123), 701)
        self.assertIsNone(store.get_command(self.tdb,123))

    async def test_sync_rolls_back_state_and_ack_if_database_insert_fails(self):
        coordination.claim(self.db, "main", "session-aaaaaaaaaaaaaaaa", "primary")
        store.set_command(self.tdb, 123, "restart_terminal")
        self.tdb.execute("CREATE TRIGGER reject_sync BEFORE INSERT ON deals "
                         "BEGIN SELECT RAISE(ABORT, 'test insert failure'); END")
        self.tdb.commit()
        deal = {"ticket":702,"time":"2026-09-17T09:00:00","symbol":"XAUUSD",
                "side":"BUY","volume":.1,"price":3000,"profit":12,"swap":0,
                "commission":0,"net":12,"is_balance":False,"is_closing":True,
                "is_opening":False,"comment":""}
        r = await self.client.post("/agent/sync", headers={"X-Token":"agent-test"},
            json={"login":123,"balance":2600,"equity":2600,"currency":"USD",
                  "server":"Demo","deals":[deal],"command_done":True,
                  "host":"main","session":"session-aaaaaaaaaaaaaaaa"})
        self.assertEqual(r.status, 503)
        self.assertEqual(store.get_state(self.tdb,123)["balance"], 2400)
        self.assertEqual(store.last_ticket(self.tdb,123), 0)
        self.assertEqual(store.get_command(self.tdb,123), "restart_terminal")

    async def test_agent_candles_upserts_and_rejects_bad_rows(self):
        now = trades.clock()
        good = {"time": now.isoformat(), "open": 2400, "high": 2405, "low": 2398, "close": 2402}
        r = await self.client.post("/agent/candles", headers={"X-Token": "agent-test"},
                                   json={"candles": [good]})
        self.assertEqual(r.status, 200, await r.text())
        self.assertEqual((await r.json())["new"], 1)
        self.assertEqual(len(store.get_candles(self.tdb, now - timedelta(minutes=1), now + timedelta(minutes=1))), 1)
        # тот же бар с уточнённым close — обновляется на месте, не дублируется
        updated = {**good, "close": 2406}
        r = await self.client.post("/agent/candles", headers={"X-Token": "agent-test"},
                                   json={"candles": [updated]})
        self.assertEqual(r.status, 200, await r.text())
        rows = store.get_candles(self.tdb, now - timedelta(minutes=1), now + timedelta(minutes=1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["close"], 2406)
        for bad in ({"candles": [{"time": "not-a-date", "open": 1, "high": 1, "low": 1, "close": 1}]},
                    {"candles": [{"time": now.isoformat(), "open": -1, "high": 1, "low": 1, "close": 1}]},
                    {"candles": "nope"}, {}):
            r = await self.client.post("/agent/candles", headers={"X-Token": "agent-test"}, json=bad)
            self.assertEqual(r.status, 400, await r.text())

    async def test_legacy_and_non_owner_agents_cannot_read_polling_work(self):
        coordination.claim(self.db,"main","session-aaaaaaaaaaaaaaaa","primary")
        r = await self.client.get("/agent/accounts",headers={"X-Token":"agent-test"})
        self.assertEqual(await r.json(),[])
        r = await self.client.get("/agent/accounts",headers={"X-Token":"agent-test",
            "X-Agent-Host":"main","X-Agent-Session":"session-aaaaaaaaaaaaaaaa"})
        self.assertEqual(len(await r.json()),1)

    async def test_role_change_cannot_override_elected_owner(self):
        coordination.claim(self.db,"main","session-aaaaaaaaaaaaaaaa","primary")
        partner.kv_set(self.db,"active_machine","main")
        for host, session in (("reserve",None),("main","old-session")):
            r = await self.client.post("/agent/role_change",headers={"X-Token":"agent-test"},
                json={"host":host,"session":session,"became":"active"})
            self.assertEqual(r.status,409)
            self.assertEqual(partner.kv_get(self.db,"active_machine"),"main")
        r = await self.client.post("/agent/role_change",headers={"X-Token":"agent-test"},
            json={"host":"main","session":"session-aaaaaaaaaaaaaaaa","became":"active"})
        self.assertEqual(r.status,200)

    async def test_owner_pause_stops_polling_even_with_enabled_guest_copy(self):
        # владелец решает, опрашивать ли физический логин — включённая
        # гостевая копия того же счёта не должна держать опрос вопреки паузе
        accounts.share([123],1,2)
        accounts.update("SONIC",1,enabled=False)
        r = await self.client.get("/agent/accounts",headers={"X-Token":"agent-test"})
        self.assertEqual(len(await r.json()),0)

    async def test_public_demo_is_polled_even_when_owner_hides_it(self):
        # «Показывать общий счёт» у владельца пишет enabled в саму запись —
        # это остановило опрос для всех, и сделки перестали приходить
        accounts.add({**self.acc, "login": 456, "name": "Demo", "strategy": "Demo", "demo": True})
        r = await self.call("PATCH", "/api/accounts/456", json={"enabled": False})
        self.assertEqual(r.status, 200, await r.text())
        r = await self.client.get("/agent/accounts", headers={"X-Token": "agent-test"})
        self.assertIn(456, [int(a["login"]) for a in await r.json()])

    async def test_guest_cannot_toggle_shared_account_polling(self):
        accounts.share([123],1,2)
        r = await self.call("PATCH", "/api/accounts/123", uid=2, json={"enabled": False})
        self.assertEqual(r.status, 403, await r.text())

    async def test_paused_account_stays_in_personal_capital(self):
        before = await (await self.call("GET", "/api/bootstrap")).json()
        accounts.update("SONIC", 1, enabled=False)
        after = await (await self.call("GET", "/api/bootstrap")).json()
        self.assertEqual(after["totals"], before["totals"])
        self.assertFalse(after["accounts"][0]["enabled"])

    async def test_invalid_patch_is_not_partially_applied(self):
        r = await self.call("PATCH","/api/accounts/123",json={"name":"Changed","base":"NaN"})
        self.assertEqual(r.status,400)
        self.assertEqual(accounts.load(1)[0]["name"],"SONIC")

    async def test_invested_override_changes_capital_and_can_be_reset(self):
        response = await self.call("PATCH", "/api/accounts/123", json={"base": 120})
        self.assertEqual(response.status, 200, await response.text())
        data = await (await self.call("GET", "/api/bootstrap")).json()
        self.assertAlmostEqual(data["totals"]["USD"]["capital"], 120)
        response = await self.call("PATCH", "/api/accounts/123", json={"base": None})
        self.assertEqual(response.status, 200, await response.text())
        data = await (await self.call("GET", "/api/bootstrap")).json()
        self.assertAlmostEqual(data["totals"]["USD"]["capital"], 100)

    async def test_bot_cannot_claim_known_history_by_guessing_login(self):
        result = await miniapp.logic.finish_add(None, 2, 2, {"name":"Wrong","login":123,
            "password":"wrong","server":"Demo"})
        self.assertIn("приглашение",result)
        self.assertEqual(accounts.load(2),[])

    async def test_cabinet_report_authorization_and_content(self):
        r = await self.call("GET","/api/cabinets/CU1/report")
        self.assertEqual(r.status,200,await r.text())
        self.assertIn("report",await r.json())
        r = await self.call("GET","/api/cabinets/CU1/report",uid=2)
        self.assertEqual(r.status,404)

    async def test_agent_endpoints_answer_400_on_malformed_bodies(self):
        token = {"X-Token": "agent-test"}
        for path, body in (("/agent/heartbeat", "not json"), ("/agent/heartbeat", "[1, 2]"),
                           ("/agent/role_change", '"active"'), ("/agent/update_notify", "[]"),
                           ("/agent/update_report", "null")):
            with self.subTest(path=path, body=body):
                r = await self.client.post(path, headers={**token, "Content-Type": "application/json"},
                                           data=body)
                self.assertEqual(r.status, 400, await r.text())
        for body in ({"host": "h" * 129}, {"host": {"evil": 1}}):
            r = await self.client.post("/agent/heartbeat", headers=token, json=body)
            self.assertEqual(r.status, 400, await r.text())
        # коммит становится частью шаблона LIKE — «%» и «_» в нём недопустимы
        for commit in ("a%", "a_b", "", 7):
            r = await self.client.post("/agent/update_report", headers=token,
                                       json={"host": "reserve", "commit": commit})
            self.assertEqual(r.status, 400, await r.text())
        r = await self.client.get("/agent/machines_status?stale_after=abc", headers=token)
        self.assertEqual(r.status, 400)

    async def test_tokens_compare_safely_and_empty_setting_matches_nothing(self):
        for headers, query in (({"X-Token": "пароль".encode().decode("latin-1")}, ""),
                               ({}, "?token=%D0%BF%D0%B0%D1%80%D0%BE%D0%BB%D1%8C"), ({}, "")):
            r = await self.client.get("/agent/accounts" + query, headers=headers)
            self.assertEqual(r.status, 403, await r.text())
        r = await self.client.get("/hook/deposit?token=wrong&customer_no=CU9&amount=5")
        self.assertEqual(r.status, 403)
        r = await self.client.get("/hook/deposit?token=agent-test&customer_no=CU9&amount=5")
        self.assertEqual(r.status, 200, await r.text())
        with patch.object(webhook_server, "TOKEN", ""):
            r = await self.client.get("/agent/accounts?token=")
            self.assertEqual(r.status, 403)
            r = await self.client.get("/hook/deposit?customer_no=CU9&amount=5")
            self.assertEqual(r.status, 403)

    async def test_status_needs_token_and_survives_corrupt_heartbeat(self):
        r = await self.client.get("/status")
        self.assertEqual(r.status, 403)
        partner.kv_set(self.db, "bot_heartbeat", "not-a-date")
        r = await self.client.get("/status", headers={"X-Token": "agent-test"})
        self.assertEqual(r.status, 200, await r.text())
        data = await r.json()
        self.assertEqual(data["bot"], "остановлен")
        self.assertIsNone(data["bot_seconds_ago"])
        self.assertEqual(data["accounts"], 1)

    async def test_canary_counts_only_time_actually_lived_on_the_commit(self):
        now = webhook_server.utcnow()
        stamp = lambda ago: (now - timedelta(seconds=ago)).isoformat()
        commit = "abc123"
        # канарейка обновилась 4000 с назад, но замолчала через 100 с
        partner.kv_set(self.db, f"canary:reserve:{commit}", stamp(4000))
        partner.kv_set(self.db, "canary_latest_seen:reserve", stamp(3900))
        partner.kv_set(self.db, "machine_commit:reserve", commit)
        r = await self.client.get(f"/agent/update_status?commit={commit}", headers={"X-Token": "agent-test"})
        self.assertAlmostEqual((await r.json())["canary_age_seconds"], 100, delta=2)
        # живая канарейка — отчитывается до сих пор: засчитывается всё время
        partner.kv_set(self.db, "canary_latest_seen:reserve", stamp(0))
        self.assertAlmostEqual(webhook_server.canary_age(self.db, commit), 4000, delta=2)
        # откатилась на прежний код — больше не свидетель этого коммита
        partner.kv_set(self.db, "machine_commit:reserve", "0ld")
        self.assertIsNone(webhook_server.canary_age(self.db, commit))
        self.assertIsNone(webhook_server.canary_age(self.db, "a%"))
        # отчёт о коммите через API пишет обе отметки, по которым считается возраст
        r = await self.client.post("/agent/update_report", headers={"X-Token": "agent-test"},
                                   json={"host": "fresh", "commit": "fff"})
        self.assertEqual(r.status, 200, await r.text())
        self.assertAlmostEqual(webhook_server.canary_age(self.db, "fff"), 0, delta=2)

    async def test_rollback_report_is_not_announced_as_update(self):
        sent = []

        async def capture(_app, text):
            sent.append(text)

        with patch.object(webhook_server, "notify", capture):
            r = await self.client.post("/agent/update_notify", headers={"X-Token": "agent-test"},
                                       json={"host": "pc<1>", "commit": "a" * 40, "rollback_from": "b" * 40})
            self.assertEqual(r.status, 200, await r.text())
            r = await self.client.post("/agent/update_notify", headers={"X-Token": "agent-test"},
                                       json={"host": "pc", "commit": "c" * 40})
            await asyncio.sleep(0)
        self.assertIn("откатил", sent[0])
        self.assertIn("pc&lt;1&gt;", sent[0])
        self.assertIn("bbbbbbbb", sent[0])
        self.assertIn("подтянул новый код", sent[1])

    async def test_account_logins_must_be_real_integers(self):
        for login in (True, 123.9, "12a", "١٢٣", [1], None, 0, -5, "0", 2**63):
            with self.subTest(login=login):
                r = await self.call("POST", "/api/accounts", json={"login": login, "name": "X",
                                                                    "password": "p", "cabinet": "CU5"})
                self.assertEqual(r.status, 400, await r.text())
        self.assertEqual([int(a["login"]) for a in accounts.load(1)], [123])
        r = await self.call("POST", "/api/accounts", json={"login": "555", "name": "NEO",
                                                            "password": "p", "cabinet": "CU5"})
        self.assertEqual(r.status, 201, await r.text())
        partner.kv_set(self.db, "guest_by:2", "1")
        partner.kv_set(self.db, "guest:2", "1")
        for logins in ("123", [True], [123.0], {"123": 1}):
            r = await self.call("POST", "/api/guests/2", json={"action": "share", "logins": logins})
            self.assertEqual(r.status, 400, await r.text())
        self.assertEqual(accounts.load(2), [])
        r = await self.call("POST", "/api/guests/2", json={"action": "share", "logins": [123, "123"]})
        self.assertEqual(r.status, 200, await r.text())
        self.assertEqual((await r.json())["added"], 1)

    async def test_non_object_json_is_a_client_error(self):
        partner.kv_set(self.db, "guest_by:2", "1")
        for method, path, body in (("PUT", "/api/profile/partner-link", []),
                                   ("POST", "/api/actions", "restart"),
                                   ("POST", "/api/guests/2", ["share"]),
                                   ("PATCH", "/api/accounts/123", ["name"]),
                                   ("POST", "/api/onboarding", ["registered"]),
                                   ("POST", "/api/accounts", [123])):
            with self.subTest(path=path):
                r = await self.call(method, path, json=body)
                self.assertEqual(r.status, 400, await r.text())

    async def test_one_broken_account_record_does_not_break_everyone(self):
        with self.assertRaises(ValueError):
            accounts.add({**self.acc, "login": 777, "name": "   ", "strategy": ""})
        # запись, испорченная вручную или старым кодом, пропускается, а не
        # роняет чтение счетов у всех пользователей
        with open(accounts.PATH, encoding="utf-8") as handle:
            raw = json.load(handle)
        raw.append({"owner": "5", "login": 778, "name": "", "password": "x", "server": "Demo"})
        with open(accounts.PATH, "w", encoding="utf-8") as handle:
            json.dump(raw, handle)
        with self.assertLogs("accounts", "ERROR"):
            self.assertEqual([int(a["login"]) for a in accounts.load()], [123])
        r = await self.call("GET", "/api/bootstrap")
        self.assertEqual(r.status, 200, await r.text())
        # мутации читают файл целиком — испорченную запись они не теряют
        accounts.update("SONIC", 1, enabled=False)
        with open(accounts.PATH, encoding="utf-8") as handle:
            self.assertEqual(len(json.load(handle)), 2)

    async def test_bot_keyboards_fit_telegram_callback_limit_with_long_names(self):
        logic = miniapp.logic
        accounts.add({**self.acc, "login": 1001, "name": "Константин Шаулюков · SONIC 2",
                      "strategy": "SONIC 2", "holder": "Константин Шаулюков", "cabinet": "CU228816"})
        partner.kv_set(self.db, "guest_by:2", "1")
        partner.kv_set(self.db, "guest:2", "1")
        accounts.share([1001], 1, 2)
        acc = next(a for a in accounts.load(1) if int(a["login"]) == 1001)
        self.assertEqual(len(acc["name"].encode()), 48)     # предел, до которого режется имя
        keyboards = {"account_menu": logic.account_menu(acc["name"], 1)[1],
                     "settings": logic.settings_menu(1, self.db)[1],
                     "cabinet_settings": logic.cabinet_settings(1, "CU228816", self.db)[1],
                     "dashboard": logic.dashboard(1)[1],
                     "cabinet_view": logic.cabinet_view(1, "CU228816", "lastweek")[1],
                     "account_view": logic.account_view(1, 1001, "lastmonth")[1],
                     "guest": logic.guest_view(self.db, 1, "2", expand_take=True)[1],
                     "invite": logic.invite_menu(1, [1001])[1]}
        keyboards.update({f"menu:{key}": logic.menu(key, acc["name"], 1) for key, _ in logic.PERIODS_FULL})
        for title, markup in keyboards.items():
            for row in markup.inline_keyboard:
                for button in row:
                    if button.callback_data:
                        with self.subTest(screen=title, data=button.callback_data):
                            self.assertLessEqual(len(button.callback_data.encode()), 64)
        # короткие коды переключателей и прежние полные названия понимаются одинаково
        for kind, code in logic.TOGGLE_CODES.items():
            self.assertEqual(logic.TOGGLE_KINDS.get(code, code), kind)
            self.assertEqual(logic.TOGGLE_KINDS.get(kind, kind), kind)

    async def test_new_cabinet_number_is_validated_like_in_the_bot(self):
        r = await self.call("POST", "/api/accounts", json={"login": 556, "name": "NEO", "password": "p",
                                                            "cabinet": "СU228816"})
        self.assertEqual(r.status, 400, await r.text())
        self.assertIn("латинские", (await r.json())["error"])
        r = await self.call("POST", "/api/accounts", json={"login": 556, "name": "NEO", "password": "p",
                                                            "cabinet": " cu 777 "})
        self.assertEqual(r.status, 201, await r.text())
        self.assertEqual(next(a["cabinet"] for a in accounts.load(1) if int(a["login"]) == 556), "CU777")
        # уже существующий кабинет владельца принимается как есть
        accounts.update("SONIC", 1, cabinet="old cab")
        r = await self.call("POST", "/api/accounts", json={"login": 557, "name": "GOLD", "password": "p",
                                                            "cabinet": "old cab"})
        self.assertEqual(r.status, 201, await r.text())

    async def test_partner_link_rejects_markup_and_spaces(self):
        base = "https://exfusion.ibportal.io/auth/register?e=link"
        for bad in (base + '&x="><img src=x onerror=alert(1)>', base + " x", base + "&x=`",
                    base + "\n&x=1", "https://exfusion.ibportal.io/auth/register",
                    "https://evil.example/auth/register?e=1"):
            with self.subTest(url=bad):
                r = await self.call("PUT", "/api/profile/partner-link", json={"url": bad})
                self.assertEqual(r.status, 400, await r.text())
        r = await self.call("PUT", "/api/profile/partner-link", json={"url": base + "&a=%D0%B1"})
        self.assertEqual(r.status, 200, await r.text())
        # уже сохранённое старым кодом значение с разметкой никуда не отдаётся
        partner.kv_set(self.db, "partner_link:7", base + '&x="><b>')
        self.assertEqual(miniapp.logic.partner_link(self.db, 7), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
