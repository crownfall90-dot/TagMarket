"""Партнёрский кабинет TagMarkets на платформе IB Portal.

Старый Syntellicore (portal.tagmarkets.com/gateway/ib/api.cfc) отключён вместе
с прежним порталом — оттуда 404 приходит даже на корень. Новый кабинет живёт на
exfusion.ibportal.io, а его API — REST с JWT на api.ibportal.io.

Отличия, ради которых это отдельный модуль:
  • вход по паролю закрыт reCAPTCHA, зато продление токена — нет: держимся
    на refresh-токене, взятом один раз из браузера, и обновляем его сами;
  • API определяет кабинет по заголовку Origin — без него отвечает
    «Could not extract subdomain from client origin»;
  • уведомления кабинета отдаются готовым списком, свой опрос лидов и
    депозитов больше не нужен.

Настройки в .env:
    IB_REFRESH_TOKEN=... — токен из браузера, основной способ входа
    IB_EMAIL=...         — логин от кабинета (вход по нему закрыт капчей)
    IB_PASSWORD=...      — пароль (файл только для root, в лог не попадает)
    IB_ORIGIN=https://exfusion.ibportal.io
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import aiohttp
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("ibportal")

API = os.getenv("IB_API", "https://api.ibportal.io").rstrip("/")
ORIGIN = os.getenv("IB_ORIGIN", "https://exfusion.ibportal.io").rstrip("/")
EMAIL = os.getenv("IB_EMAIL", "")
PASSWORD = os.getenv("IB_PASSWORD", "")
BASE = "/api/Backoffice/v1.0"
# Вход по паролю закрыт капчей: кабинет отвечает «missing-input-response», а
# решить reCAPTCHA сервер не может. Зато продление токена капчи не требует —
# поэтому живём на refresh-токене, взятом один раз из браузера.
TOKEN_FILE = os.getenv("IB_TOKEN_FILE", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "ib_token"))

# токен живёт недолго; обновляемся заранее, чтобы не ловить 401 в середине опроса
_token: str = ""
_refresh: str = ""
_expires: datetime = datetime.min


class PortalError(RuntimeError):
    """Кабинет ответил отказом — текст пригоден для показа человеку."""


def _headers(auth: bool = True) -> dict:
    h = {"Origin": ORIGIN, "Content-Type": "application/json"}
    if auth and _token:
        h["Authorization"] = f"Bearer {_token}"
    return h


def _stored_refresh() -> str:
    """Refresh-токен: сначала из файла (он свежее), иначе из .env."""
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            saved = f.read().strip()
            if saved:
                return saved
    except OSError:
        pass
    return os.getenv("IB_REFRESH_TOKEN", "")


def _save_refresh(token: str) -> None:
    """Сохранить продлённый токен: кабинет выдаёт новый на каждое продление,
    и без записи после перезапуска бот пришёл бы со старым, уже недействительным."""
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token)
        os.chmod(TOKEN_FILE, 0o600)     # доступ к кабинету — не для чужих глаз
    except OSError as e:
        log.warning("не сохранил refresh-токен: %s", e)


def _remember(data: dict) -> None:
    """Запомнить выданные токены. Поля именуются по-разному, берём что есть."""
    global _token, _refresh, _expires
    _token = data.get("accessToken") or data.get("token") or data.get("access_token") or ""
    fresh = data.get("refreshToken") or data.get("refresh_token") or ""
    if not _token:
        raise PortalError(f"кабинет не вернул токен: {list(data)[:6]}")
    if fresh and fresh != _refresh:
        _refresh = fresh
        _save_refresh(fresh)

    # Кабинет отдаёт срок как метку времени (expiresAt), а не как «через сколько».
    # Обновляемся за минуту до конца, чтобы не поймать 401 в середине опроса.
    _expires = datetime.now(timezone.utc) + timedelta(seconds=540)
    stamp = data.get("expiresAt") or data.get("expires_at")
    if stamp:
        try:
            when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            _expires = when - timedelta(minutes=1)
        except ValueError:
            log.warning("не разобрал срок токена: %s", stamp)
    elif data.get("expiresIn") or data.get("expires_in"):
        seconds = int(data.get("expiresIn") or data.get("expires_in"))
        _expires = datetime.now(timezone.utc) + timedelta(seconds=max(60, seconds - 60))

    # refresh живёт неделю и на каждом продлении выдаётся новый: пока бот
    # обновляется чаще раза в неделю, доступ не прервётся
    if data.get("refreshTokenExpiresAt"):
        log.info("refresh-токен действует до %s", data["refreshTokenExpiresAt"][:10])


async def login(session: aiohttp.ClientSession) -> None:
    """Войти в кабинет по логину и паролю."""
    if not EMAIL or not PASSWORD:
        raise PortalError("не заданы IB_EMAIL и IB_PASSWORD")
    async with session.post(f"{API}{BASE}/Auth/login", headers=_headers(auth=False),
                            json={"email": EMAIL, "password": PASSWORD}) as r:
        data = await r.json(content_type=None)
        if r.status != 200:
            # пароль в текст ошибки не попадает — сообщение отдаёт сам кабинет
            raise PortalError(f"вход отклонён ({r.status}): {_message(data)}")
        if _needs_mfa(data):
            raise PortalError("кабинет требует подтверждение входа (2FA) — "
                              "выключи его для этого входа или заведи отдельный доступ")
        _remember(data)
        log.info("вход в кабинет выполнен")


def _needs_mfa(data: dict) -> bool:
    flat = " ".join(str(k) + str(v) for k, v in data.items()).lower()
    return "mfa" in flat or "twofactor" in flat or "two_factor" in flat


def _message(data) -> str:
    """Достаём человеческий текст из разных форматов ошибок .NET."""
    if isinstance(data, dict):
        for key in ("message", "errors", "title", "detail"):
            if data.get(key):
                v = data[key]
                return "; ".join(v) if isinstance(v, list) else str(v)
    return str(data)[:200]


async def _renew(session: aiohttp.ClientSession) -> None:
    """Продлить доступ. Основной путь — refresh-токен: вход по паролю закрыт капчей."""
    global _refresh
    _refresh = _refresh or _stored_refresh()
    if _refresh:
        try:
            async with session.post(f"{API}{BASE}/Auth/refresh", headers=_headers(auth=False),
                                    json={"refreshToken": _refresh}) as r:
                data = await r.json(content_type=None)
                if r.status == 200:
                    _remember(data)
                    return
                raise PortalError(
                    f"refresh-токен не принят ({r.status}): {_message(data)}. "
                    f"Возьми новый из браузера — см. IB_REFRESH_TOKEN в .env")
        except aiohttp.ClientError as e:
            raise PortalError(f"кабинет недоступен: {e}") from e
    await login(session)        # капча его отобьёт, но сообщение будет внятным


async def get(session: aiohttp.ClientSession, path: str, **params):
    """GET к кабинету. Токен получаем и продлеваем сами."""
    if not _token or datetime.now(timezone.utc) >= _expires:
        await _renew(session)

    url = f"{API}{BASE}/{path.lstrip('/')}"
    async with session.get(url, headers=_headers(), params=params or None) as r:
        if r.status == 401:     # токен отозвали раньше срока — продлеваем и повторяем
            await _renew(session)
            async with session.get(url, headers=_headers(), params=params or None) as retry:
                if retry.status != 200:
                    raise PortalError(f"{path}: {retry.status} {_message(await retry.json(content_type=None))}")
                return await retry.json(content_type=None)
        if r.status != 200:
            raise PortalError(f"{path}: {r.status} {_message(await r.json(content_type=None))}")
        return await r.json(content_type=None)


async def notifications(session: aiohttp.ClientSession, limit: int = 30) -> list[dict]:
    """Уведомления кабинета — их и пересылаем в Telegram.

    Прежде бот сам опрашивал лиды и депозиты; здесь кабинет отдаёт готовые
    события, и дублировать его логику незачем.
    """
    data = await get(session, "Notifications", pageSize=limit, page=1)
    if isinstance(data, dict):
        for key in ("items", "data", "results", "notifications"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data if isinstance(data, list) else []


async def status(session: aiohttp.ClientSession) -> dict:
    """Состояние партнёра — заодно проверка, что доступ живой."""
    return await get(session, "Distributor/Status")
