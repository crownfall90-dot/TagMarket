"""Offline integration checks. All writes go to temporary databases and accounts."""
import asyncio
import hashlib
import hmac
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

    def test_recovered_primary_cannot_preempt_healthy_standby(self):
        self.assertTrue(coordination.claim(self.db, "reserve", "r", "standby", 100)["granted"])
        coordination.renew(self.db, "reserve", "r", 250)
        for moment in (110, 160, 300, 420):
            self.assertFalse(coordination.claim(self.db, "main", "m", "primary", moment)["granted"])
        self.assertTrue(coordination.permits(self.db, "reserve", "r", 420))

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


class AuthTests(unittest.TestCase):
    def test_authentication_and_tamper(self):
        self.assertEqual(miniapp.validate_init_data(signed(42), "test-token")["id"], 42)
        for raw in ("", signed().replace("hash=", "hash=0"), signed(timestamp=time.time()-90000),
                    signed(timestamp=time.time()+1000), signed()+"&auth_date=10", signed(uid="1")):
            with self.subTest(raw=raw[:20]), self.assertRaises((ValueError, TypeError)):
                miniapp.validate_init_data(raw, "test-token")


class BroadcastFormatTests(unittest.TestCase):
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

    def test_telegram_counts_emoji_as_two_caption_units(self):
        self.assertEqual(miniapp.telegram_length("😀" * 600), 1200)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        accounts.PATH = str(Path(self.tmp.name) / "accounts.json")
        self.db = partner.open_db(str(Path(self.tmp.name) / "state.db"))
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
        self.app.router.add_post("/agent/claim", webhook_server.agent_claim)
        self.app.router.add_post("/agent/role_change", webhook_server.agent_role_change)
        self.app.router.add_get("/agent/accounts", webhook_server.agent_accounts)
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

        with patch.object(miniapp.logic, "AiohttpSession", Session), patch.object(miniapp.logic, "Bot", Sender):
            response = await self.call("POST", "/api/broadcast", data=form("broadcast-test-1"))
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["sent"], 1)
            self.assertEqual(calls[0], ("photo", "2", None, True))
            self.assertEqual(calls[1][0:2], ("message", "2"))
            repeat = await self.call("POST", "/api/broadcast", data=form("broadcast-test-1"))
            self.assertEqual(repeat.status, 409)

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
        with patch.object(miniapp.logic, "AiohttpSession", Session), patch.object(miniapp.logic, "Bot", Sender):
            response = await self.call("POST", "/api/broadcast", data=form)
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(sent, [("2", "<b>Привет</b> с картинкой")])
        inbox = await (await self.call("GET", "/api/notifications", uid=2)).json()
        self.assertEqual(inbox["unread"], 1)
        self.assertEqual(inbox["items"][0]["body"], "Привет с картинкой")

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

    async def test_cross_user_and_privilege_checks(self):
        for method,path,body in [("GET","/api/accounts/123/report",None),
                                  ("PATCH","/api/accounts/123",{"enabled":False}),
                                  ("DELETE","/api/accounts/123",None),
                                  ("GET","/api/admin",None),
                                  ("POST","/api/actions",{"action":"restart","login":123}),
                                  ("POST","/api/invites",{"logins":[123]})]:
            r = await self.call(method,path,uid=2,json=body)
            self.assertIn(r.status,(403,404),await r.text())

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

    async def test_report_and_pagination(self):
        now = datetime.utcnow()
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

    async def test_invites_shared_accounts_and_revoke(self):
        r = await self.call("POST","/api/invites",json={"logins":[123]})
        self.assertEqual(r.status,200)
        token = (await r.json())["url"].split("start=")[1]
        self.assertIsNotNone(miniapp.logic.invite_get(self.db,token))
        r = await self.call("DELETE","/api/invites/"+token,uid=2)
        self.assertEqual(r.status,404)
        await self.call("DELETE","/api/invites/"+token)
        self.assertIsNone(miniapp.logic.invite_get(self.db,token))
        accounts.share([123],1,2)
        accounts.share([123],1,2)
        self.assertEqual(len(accounts.load(2)),1)
        r = await self.call("POST","/api/actions",uid=2,json={"action":"restart","login":123})
        self.assertEqual(r.status,403)

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
        self.assertEqual(response.status, 200)
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

    async def test_fenced_sync_does_not_mutate_data(self):
        coordination.claim(self.db,"main","session-a","primary")
        r = await self.client.post("/agent/sync",headers={"X-Token":"agent-test"},
                                   json={"login":123,"balance":0,"host":"reserve","session":"session-b"})
        self.assertEqual(r.status,409)
        self.assertEqual(store.get_state(self.tdb,123)["balance"],2400)

    async def test_sync_rejects_entire_invalid_packet_without_acking_command(self):
        coordination.claim(self.db, "main", "session-a", "primary")
        store.set_command(self.tdb, 123, "restart_terminal")
        deal = {"ticket": 701, "time": "2026-09-17T09:00:00", "symbol": "XAUUSD",
                "side": "BUY", "volume": .1, "price": 3000, "profit": 12,
                "swap": 0, "commission": 0, "net": 12, "is_balance": False,
                "is_closing": True, "is_opening": False, "comment": ""}
        packet = {"login":123, "balance":2500, "equity":2500, "currency":"USD",
                  "server":"Demo", "capital_hist":100, "deals":[deal],
                  "command_done":True, "host":"main", "session":"session-a"}
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
        coordination.claim(self.db, "main", "session-a", "primary")
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
                  "host":"main","session":"session-a"})
        self.assertEqual(r.status, 500)
        self.assertEqual(store.get_state(self.tdb,123)["balance"], 2400)
        self.assertEqual(store.last_ticket(self.tdb,123), 0)
        self.assertEqual(store.get_command(self.tdb,123), "restart_terminal")

    async def test_legacy_and_non_owner_agents_cannot_read_polling_work(self):
        coordination.claim(self.db,"main","session-a","primary")
        r = await self.client.get("/agent/accounts",headers={"X-Token":"agent-test"})
        self.assertEqual(await r.json(),[])
        r = await self.client.get("/agent/accounts",headers={"X-Token":"agent-test",
            "X-Agent-Host":"main","X-Agent-Session":"session-a"})
        self.assertEqual(len(await r.json()),1)

    async def test_role_change_cannot_override_elected_owner(self):
        coordination.claim(self.db,"main","session-a","primary")
        partner.kv_set(self.db,"active_machine","main")
        for host, session in (("reserve",None),("main","old-session")):
            r = await self.client.post("/agent/role_change",headers={"X-Token":"agent-test"},
                json={"host":host,"session":session,"became":"active"})
            self.assertEqual(r.status,409)
            self.assertEqual(partner.kv_get(self.db,"active_machine"),"main")
        r = await self.client.post("/agent/role_change",headers={"X-Token":"agent-test"},
            json={"host":"main","session":"session-a","became":"active"})
        self.assertEqual(r.status,200)

    async def test_enabled_guest_copy_keeps_physical_account_in_polling_list(self):
        accounts.share([123],1,2)
        accounts.update("SONIC",1,enabled=False)
        r = await self.client.get("/agent/accounts",headers={"X-Token":"agent-test"})
        self.assertEqual(len(await r.json()),1)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
