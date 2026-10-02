"""Единый сервис курсов валют: MYFIN -> НБРБ -> последний сохранённый курс.

Наружу отдаётся один снимок курсов одного провайдера целиком (курсы разных
источников не смешиваются). Провайдер переключается автоматически; на каждом
обновлении сначала снова пробуется основной MYFIN.
"""
import asyncio
import json
import logging
import math
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import aiohttp

MYFIN_URL = "https://myfin.by/bank/kursy_valjut_nbrb"
NBRB_URL = "https://api.nbrb.by/exrates/rates?periodicity=0"
REQUIRED = ("USD", "RUB")
PROVIDER_TIMEOUT = 4        # сек на один онлайн-источник: не задерживаем Mini App
FRESH_TTL = 3600            # курс основного источника держим час
FALLBACK_TTL = 300          # резервный/устаревший — быстро возвращаемся на MYFIN
FAILURE_TTL = 60            # оба источника лежат — не долбим их при каждом запросе
RATE_DATE_PAST = timedelta(days=7)     # выходные и праздники НБРБ
RATE_DATE_FUTURE = timedelta(days=3)   # НБРБ публикует курс на следующий день
STORE_KEY = "fx:last_good"
LABELS = {"myfin": "MYFIN · НБРБ", "nbrb": "НБРБ", "cache": "Последний сохранённый курс"}


class FxUnavailable(Exception):
    """Нет ни онлайн-курса, ни сохранённого."""


class _MyfinRateTable(HTMLParser):
    """Read current BYN-per-unit quotes from MYFIN's NBRB table."""
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row = []
        elif tag == "td" and self.row is not None: self.cell = []

    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.row.append(" ".join(filter(None, self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_myfin_nbrb_rates(markup):
    parser = _MyfinRateTable()
    parser.feed(markup)
    rates = {"BYN": 1.0}
    for row in parser.rows:
        if len(row) < 5 or not re.fullmatch(r"[A-Z]{3}", row[-2]):
            continue
        try:
            quote = float(row[1].replace(",", "."))
            units = float(row[-1].replace(",", "."))
        except ValueError:
            continue
        if quote > 0 and units > 0:
            rates[row[-2]] = quote / units
    return validate_rates(rates)


def parse_nbrb_json(payload):
    """Официальный API НБРБ: список {Cur_Abbreviation, Cur_Scale, Cur_OfficialRate, Date}."""
    if not isinstance(payload, list):
        raise ValueError("NBRB: list expected")
    rates, dates = {"BYN": 1.0}, []
    for item in payload:
        try:
            code = item["Cur_Abbreviation"]
            rate, scale = float(item["Cur_OfficialRate"]), float(item["Cur_Scale"])
        except (KeyError, TypeError, ValueError):
            continue
        if code in REQUIRED and math.isfinite(rate) and math.isfinite(scale) and rate > 0 and scale > 0:
            rates[code] = rate / scale
            try: dates.append(datetime.fromisoformat(str(item["Date"])[:10]).date())
            except (KeyError, ValueError): pass
    return validate_rates(rates, min(dates, default=None))


def validate_rates(rates, rate_date=None, now=None):
    """Курс годен, только если есть все валюты, значения конечны и > 0, дата разумна."""
    if not isinstance(rates, dict):
        raise ValueError("rates: dict expected")
    clean = {"BYN": 1.0}
    for code in REQUIRED:
        value = rates.get(code)
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or value <= 0:
            raise ValueError(f"rates: invalid or missing {code}")
        clean[code] = float(value)
    if rate_date is not None:
        today = (now or datetime.now(timezone.utc)).date()
        if not today - RATE_DATE_PAST <= rate_date <= today + RATE_DATE_FUTURE:
            raise ValueError("rates: implausible date")
    return clean


async def fetch_myfin(session):
    async with session.get(MYFIN_URL) as response:
        response.raise_for_status()
        return parse_myfin_nbrb_rates(await response.text()), None


async def fetch_nbrb(session):
    async with session.get(NBRB_URL) as response:
        response.raise_for_status()
        payload = await response.json(content_type=None)
    rates = parse_nbrb_json(payload)
    dates = [str(i.get("Date", ""))[:10] for i in payload if isinstance(i, dict) and i.get("Cur_Abbreviation") in REQUIRED]
    return rates, (min(dates) or None) if dates else None


class FxService:
    def __init__(self, providers=(("myfin", fetch_myfin), ("nbrb", fetch_nbrb)),
                 timeout=PROVIDER_TIMEOUT, clock=time.monotonic):
        self.providers = providers
        self.timeout = timeout
        self.clock = clock
        self.snapshot = None       # последний успешный снимок (в памяти)
        self.valid_until = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def _stored(db):
        if db is None: return None
        try:
            from partner import kv_get
            data = json.loads(kv_get(db, STORE_KEY) or "null")
            rates = validate_rates(data["rates"])
            datetime.fromisoformat(data["updated_at"])
            return {"rates": rates, "provider": data.get("provider", "cache"),
                    "updated_at": data["updated_at"], "rate_date": data.get("rate_date")}
        except (TypeError, KeyError, ValueError):
            return None

    @staticmethod
    def _save(db, snap):
        if db is None: return
        try:
            from partner import kv_set
            kv_set(db, STORE_KEY, json.dumps({k: snap[k] for k in ("rates", "provider", "updated_at", "rate_date")}))
        except Exception as exc:
            logging.warning("FX last-good not saved: %s", type(exc).__name__)

    async def _try(self, session, name, fetch):
        try:
            rates, rate_date = await asyncio.wait_for(fetch(session), self.timeout + 1)
            return validate_rates(rates, datetime.fromisoformat(rate_date).date() if rate_date else None), rate_date
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, KeyError) as exc:
            logging.warning("FX provider %s unavailable: %s", name, type(exc).__name__)
            return None

    async def get(self, db=None):
        """Единый снимок: {rates, provider, updated_at, rate_date, stale}."""
        async with self._lock:
            now = self.clock()
            if self.snapshot and now < self.valid_until:
                return dict(self.snapshot)
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for index, (name, fetch) in enumerate(self.providers):
                    got = await self._try(session, name, fetch)
                    if got:
                        rates, rate_date = got
                        snap = {"rates": rates, "provider": name, "rate_date": rate_date, "stale": False,
                                "updated_at": datetime.now(timezone.utc).isoformat()}
                        self.snapshot = snap
                        self.valid_until = now + (FRESH_TTL if index == 0 else FALLBACK_TTL)
                        self._save(db, snap)
                        return dict(snap)
            last = self.snapshot or self._stored(db)
            if not last:
                self.valid_until = 0.0
                raise FxUnavailable("no FX rates available")
            self.snapshot = {**last, "stale": True, "provider": "cache"}
            self.valid_until = now + FAILURE_TTL
            return dict(self.snapshot)


service = FxService()
