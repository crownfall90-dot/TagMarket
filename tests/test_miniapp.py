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

    def test_legacy_standby_cannot_take_over_while_owner_is_alive(self):
        coordination.claim(self.db, "main", "m", "primary", 0)
        self.assertFalse(coordination.may_poll_anonymously(self.db, 100))
        self.assertFalse(coordination.authorize(self.db, "old-reserve", None, 100))
        self.assertTrue(coordination.permits(self.db, "main", "m", 100))

    def test_legacy_standby_replaces_offline_primary_and_holds_lease(self):
        # Production failure: reserve on pre-lease code was fenced forever
        # after the primary went offline, so nobody polled MT5.
        coordination.claim(self.db, "main", "m", "primary", 0)
        self.assertTrue(coordination.may_poll_anonymously(self.db, 181))
        self.assertTrue(coordination.authorize(self.db, "old-reserve", None, 181))
        coordination.renew(self.db, "old-reserve", None, 200)
        self.assertEqual(coordination.read(self.db)["expires"], 380)
        # A recovered new-code primary must not preempt it.
        self.assertFalse(coordination.claim(self.db, "main", "m2", "primary", 300)["granted"])
        self.assertTrue(coordination.authorize(self.db, "old-reserve", None, 300))
        self.assertFalse(coordination.permits(self.db, "main", "m2", 300))
        # Once the legacy machine stops uploading, the primary gets it back.
        self.assertTrue(coordination.claim(self.db, "main", "m2", "primary", 381)["granted"])


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
        # a stale block reason must not stay on screen forever
        partner.kv_set(db, "machine_blocked:old", f"{iso(4000)}|dirty tree")
        stale = {m["host"]: m for m in miniapp.machine_states(db, now)}
        self.assertEqual(stale["old"]["blocked"], "")


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

    def test_telegram_counts_emoji_as_two_caption_units(self):
        self.assertEqual(miniapp.telegram_length("😀" * 600), 1200)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
