"""Счета пользователей из accounts.json.

Бот многопользовательский: каждый счёт принадлежит одному Telegram ID и виден
только ему. Внутри пользователя счета сгруппированы по кабинету TagMarkets
(Customer Number) — у одного человека может быть несколько кабинетов, и без
группировки счета из разных кабинетов перемешиваются.

Поля записи:
  owner      — Telegram ID владельца
  cabinet    — Customer Number кабинета, напр. CU228816
  holder     — имя и фамилия владельца кабинета (для наглядности)
  name       — как счёт называть в боте
  login      — номер счёта MT5
  password   — пароль (хватит investor: бот только читает)
  server     — торговый сервер, напр. TMFinancials-Server
  terminal   — путь к terminal64.exe (терминал общий на всех)
  multiplier — множитель Amplify (мои деньги = баланс / множитель), 1 если обычный счёт
"""

import json
import os
from cryptography.fernet import Fernet, InvalidToken
from account_lock import transaction

PATH = os.getenv("ACCOUNTS_FILE", os.path.join("data", "accounts.json"))
REQUIRED = ("owner", "name", "login", "password", "server")

# какие уведомления слать по счёту; по умолчанию все включены
NOTIFY_KINDS = {"trades": "Сделки", "deposits": "Пополнения", "withdrawals": "Выводы"}
DEFAULT_NOTIFY = {k: True for k in NOTIFY_KINDS}


def _read() -> list[dict]:
    if not os.path.exists(PATH):
        return []
    with open(PATH, encoding="utf-8") as f:
        data = json.load(f)
    for acc in data:
        password = acc.get("password")
        if isinstance(password, str) and password.startswith("enc:v1:"):
            try:
                acc["password"] = _cipher(create=False).decrypt(password[7:].encode()).decode()
            except (InvalidToken, UnicodeError, ValueError) as exc:
                raise ValueError("Не удалось расшифровать пароль MT5: проверьте ключ accounts.json.key") from exc
    return data


def _cipher(create=True):
    key_path = os.getenv("ACCOUNTS_KEY_FILE") or PATH + ".key"
    try:
        with open(key_path, "rb") as handle:
            key = handle.read().strip()
    except FileNotFoundError:
        if not create:
            raise ValueError("Отсутствует ключ шифрования MT5")
        key = Fernet.generate_key()
        os.makedirs(os.path.dirname(os.path.abspath(key_path)), exist_ok=True)
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            with open(key_path, "rb") as handle:
                key = handle.read().strip()
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(key + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
    return Fernet(key)


def load(owner=None) -> list[dict]:
    """Счета владельца. Без owner — все, это нужно только фоновому опросу."""
    data = _read()
    for acc in data:
        missing = [k for k in REQUIRED if not acc.get(k)]
        if missing:
            raise ValueError(f"счёт {acc.get('name', '?')}: не заполнено {', '.join(missing)}")
        acc.setdefault("multiplier", 1)
        acc.setdefault("enabled", True)
        acc.setdefault("cabinet", "")     # счета, заведённые до появления кабинетов
        acc.setdefault("holder", "")
        acc.setdefault("strategy", "")    # название стратегии, напр. SONIC 1
        acc.setdefault("base", None)      # мои деньги на дату base_at (из портала)
        acc.setdefault("base_at", None)
        acc.setdefault("demo", False)     # чужой счёт для наблюдения, не в счёт капитала владельца
        acc["notify"] = {**DEFAULT_NOTIFY, **(acc.get("notify") or {})}
    if owner is None:
        return data
    return [a for a in data if str(a["owner"]) == str(owner)]


NO_CABINET = "—"    # для счетов, у которых кабинет ещё не указан


def dedup(accs: list[dict], by_owner: bool = True) -> list[dict]:
    """Один и тот же логин+сервер — один раз, первое вхождение побеждает.

    by_owner=True (по умолчанию) — ключ включает owner: гостевая копия счёта
    (тот же логин, другой владелец — это share(), легитимный сценарий) не
    должна схлопываться с оригиналом при подсчёте денег в дашборде/сводке
    кабинета, где деньги считаются per-owner.

    by_owner=False — для мест, которым владелец не важен вообще: физический
    MT5-логин один и тот же независимо от того, у скольких владельцев на
    него есть запись (agent_accounts — агенту всё равно, кто там владелец,
    а опрашивать/переключать терминал на один логин дважды за круг впустую).

    add() теперь не даёт завести дубликат заново, но старые данные (счёт,
    заведённый дважды до этой проверки) и суммирование в дашборде/сводке
    кабинета всё ещё должны быть защищены — иначе капитал и профит по нему
    задваиваются молча.
    """
    seen: set = set()
    out = []
    for a in accs:
        key = (int(a["login"]), a.get("server") or "")
        if by_owner:
            key = (str(a["owner"]),) + key
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def cabinets(owner) -> dict[str, dict]:
    """Кабинеты пользователя: {customer_no: {holder, accounts:[...]}}.

    Демо-счета (demo=True) сюда не попадают: через эту функцию считаются
    деньги на дашборде и в сводках, а демо — чужой счёт для наблюдения, его
    капитал не должен подмешиваться к капиталу владельца. У демо-счёта свой
    отдельный вход в интерфейсе (см. bot.py: DEMO_CABINET, demo_button()).
    """
    out: dict[str, dict] = {}
    for acc in dedup(load(owner)):
        if acc.get("demo"):
            continue
        key = acc.get("cabinet") or NO_CABINET
        group = out.setdefault(key, {"holder": acc.get("holder", ""), "accounts": []})
        if acc.get("holder") and not group["holder"]:
            group["holder"] = acc["holder"]
        group["accounts"].append(acc)
    return out


def holder_of(cabinet: str) -> str:
    """Имя владельца этого кабинета, если оно уже известно у кого угодно.

    Кабинет — реальный клиент портала, а не привязка к одному Telegram ID:
    его счета может заводить и сам владелец, и другой человек с доступом
    (гость, второй аккаунт). Смотреть только «свои» счета (cabinets(owner))
    не годится — второй человек, заводящий тот же кабинет впервые под своим
    Telegram ID, не увидит уже известное имя и получит вопрос заново, хотя
    holder для этого номера давно есть в системе.

    Если под одним номером в системе уже накопились РАЗНЫЕ имена (опечатка:
    кто-то ввёл чужой номер по ошибке) — не гадаем, чьё имя правильное, а
    отдаём пустоту: пусть бот спросит заново, чем молча подставит новому
    человеку чужое имя.
    """
    if not cabinet:
        return ""
    names = {acc["holder"] for acc in load()
            if str(acc.get("cabinet") or "").strip() == cabinet and acc.get("holder")}
    return names.pop() if len(names) == 1 else ""


def label(cabinet: str, owner) -> str:
    """Как называть кабинет в интерфейсе.

    Номер вида CU261780 ничего не говорит с первого взгляда, поэтому везде
    показываем владельца, а номер оставляем только в карточке счёта. Ключом
    кабинет остаётся прежним — меняется лишь подпись.
    """
    holder = (cabinets(owner).get(cabinet) or {}).get("holder")
    if holder:
        return holder
    return "Без кабинета" if cabinet == NO_CABINET else cabinet


def in_cabinet(owner, cabinet: str) -> list[dict]:
    return [a for a in load(owner) if (a.get("cabinet") or NO_CABINET) == cabinet]


def notifies(acc: dict, kind: str) -> bool:
    """Слать ли уведомление такого типа по этой стратегии.

    Три уровня: обновления счёта вообще, общий выключатель уведомлений
    и отдельный тип события.
    """
    notify = acc.get("notify") or {}
    return (bool(acc.get("enabled", True))
            and bool(notify.get("all", True))
            and bool(notify.get(kind, True)))


def silent(acc: dict) -> bool:
    """Молчит ли счёт: выключен опрос, общий выключатель или все типы событий.

    Три уровня выключателей дают одинаковый для человека итог — уведомлений
    нет. В списке важен именно итог, а не то, каким рычагом его добились.
    """
    return not any(notifies(acc, kind) for kind in NOTIFY_KINDS)


def by_name(name: str, owner) -> dict | None:
    return next((a for a in load(owner) if a["name"] == name), None)


@transaction
def save(data: list[dict]) -> None:
    """Пишет счета целиком. Сначала во временный файл, потом переименование.

    Файл переписывается на каждую правку (переименование, выключатель, новый
    счёт). Прямая запись означает, что обрыв посередине оставит обрезанный
    JSON — а в нём пароли и привязки всех счетов, восстанавливать неоткуда.
    Переименование внутри одной папки атомарно: либо старый файл, либо новый.
    """
    cipher = _cipher() if any(a.get("password") for a in data) else None
    stored = []
    for acc in data:
        row = dict(acc)
        password = row.get("password")
        if password and not password.startswith("enc:v1:"):
            row["password"] = "enc:v1:" + cipher.encrypt(password.encode()).decode()
        stored.append(row)
    tmp = f"{PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stored, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())    # иначе при отключении питания останется пустой файл
    os.replace(tmp, PATH)
    try:
        os.chmod(PATH, 0o600)
    except OSError:
        pass


@transaction
def migrate_passwords() -> bool:
    """Encrypt pre-existing cleartext credentials while services are stopped."""
    if not os.path.exists(PATH):
        return False
    with open(PATH, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not any(a.get("password") and not str(a["password"]).startswith("enc:v1:") for a in raw):
        _read()  # Verify the key is still available before reporting success.
        return False
    save(_read())
    return True


def encrypt_snapshot(path: str) -> bool:
    """Remove plaintext MT5 passwords from an older deployment backup."""
    with open(path, encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list) or not any(
        isinstance(row, dict) and row.get("password") and
        not str(row["password"]).startswith("enc:v1:") for row in rows
    ):
        return False
    cipher = _cipher()
    stored = []
    for row in rows:
        copy = dict(row)
        password = copy.get("password")
        if password and not str(password).startswith("enc:v1:"):
            copy["password"] = "enc:v1:" + cipher.encrypt(str(password).encode()).decode()
        stored.append(copy)
    tmp = path + ".encrypted.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(stored, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return True


@transaction
def add(acc: dict) -> None:
    display = (acc.get("strategy") or acc["name"]).strip()
    cabinet = (acc.get("cabinet") or "").strip()
    if strategy_taken(acc["owner"], cabinet, display):
        raise ValueError(f"в кабинете {cabinet or 'без номера'} уже есть счёт «{display}»")
    # один и тот же логин дважды у одного владельца — задваивает
    # капитал и профит в сводке кабинета и на дашборде (они суммируют счета
    # без дедупликации по логину, в отличие от partner.cabinet_state).
    # У гостя копия того же логина — это нормально, он другой owner, поэтому
    # сравниваем только среди счетов ЭТОГО владельца
    # Mini App and bot actions address an account by its MT5 login. A second
    # record with the same login would make edit/delete routes ambiguous even
    # when the server or cabinet differs.
    dup = next((a for a in load(acc["owner"]) if int(a["login"]) == int(acc["login"])), None)
    if dup:
        raise ValueError(f"этот счёт уже добавлен как «{dup['name']}»")
    if any((a.get("cabinet") or "").strip().casefold() == cabinet.casefold()
           and a["name"].casefold() == acc["name"].casefold()
           for a in load(acc["owner"])):
        raise ValueError(f"в кабинете {cabinet or 'без номера'} уже есть счёт «{acc['name']}»")
    acc.setdefault("strategy", display)
    acc["name"] = unique_storage_name(acc["name"], acc["owner"], cabinet, acc["login"])
    save(_read() + [acc])


@transaction
def remove(name: str, owner) -> bool:
    data = _read()
    target = next((a for a in data
                   if a["name"] == name and str(a["owner"]) == str(owner)), None)
    if target and target.get("demo"):
        return False    # демо-счёт можно только скрыть (enabled), не удалить
    left = [a for a in data
            if not (a["name"] == name and str(a["owner"]) == str(owner))]
    if len(left) == len(data):
        return False
    save(left)
    return True


@transaction
def remove_login(login, owner, shared_by=None) -> str:
    """Удалить счёт по номеру. Возвращает имя удалённого или пустую строку.

    По номеру, а не по имени: у получателя копия могла быть переименована, и
    забрать её обратно по нашему названию не вышло бы.
    """
    data = _read()
    def matches(a):
        return (int(a["login"]) == int(login) and str(a["owner"]) == str(owner)
                and (shared_by is None or (str(a.get("shared_by", "")) == str(shared_by)
                     and a.get("shared_origin") != "inferred")))

    target = next((a for a in data if matches(a)), None)
    if target and target.get("demo"):
        return ""       # демо-счёт можно только скрыть (enabled), не удалить
    left = [a for a in data if not matches(a)]
    if len(left) == len(data):
        return ""
    gone = target["name"]
    save(left)
    return gone


@transaction
def purge(owner) -> int:
    """Удалить все счета владельца. Возвращает, сколько удалено.

    Одной записью файла, а не remove() в цикле: тот перезаписывает файл на
    каждый счёт, и обрыв посередине оставил бы половину удалённой.
    """
    data = _read()
    left = [a for a in data if str(a["owner"]) != str(owner)]
    if len(left) != len(data):
        save(left)
    return len(data) - len(left)


@transaction
def unshare(from_owner, to_owner) -> int:
    """Revoke only copies explicitly shared by from_owner with to_owner."""
    data = _read()
    left = [a for a in data if not (str(a["owner"]) == str(to_owner)
            and str(a.get("shared_by", "")) == str(from_owner)
            and a.get("shared_origin") != "inferred")]
    if len(left) != len(data):
        save(left)
    return len(data) - len(left)


@transaction
def update(target: str, owner, **changes) -> bool:
    """Правит поля своего счёта. Возвращает False, если счёт не найден.

    Первый параметр назван target, а не name: иначе переименование
    update(..., name=...) конфликтует с самим параметром.
    """
    data = _read()
    for acc in data:
        if acc["name"] == target and str(acc["owner"]) == str(owner):
            acc.update(changes)
            save(data)
            return True
    return False


def strategy_taken(owner, cabinet: str, strategy: str, skip_login=None) -> bool:
    """A visible account name is unique only inside one owner's cabinet."""
    want = (strategy or "").strip().casefold()
    scope = (cabinet or "").strip().casefold()
    return any((a.get("strategy") or a["name"]).strip().casefold() == want
               and (a.get("cabinet") or "").strip().casefold() == scope
               and (skip_login is None or int(a["login"]) != int(skip_login))
               for a in load(owner))


def unique_storage_name(desired: str, owner, cabinet: str, login, skip_login=None) -> str:
    """Keep legacy name-based bot callbacks unambiguous across cabinets."""
    # Telegram callback_data is limited to 64 UTF-8 bytes. The longest bot
    # prefix (cfg:delyes:) takes 11, so leave room for future action names.
    def clipped(value: str, limit: int) -> str:
        return value.encode("utf-8")[:limit].decode("utf-8", "ignore").rstrip()

    taken = {a["name"].casefold() for a in load(owner)
             if skip_login is None or int(a["login"]) != int(skip_login)}
    candidate = clipped(desired, 48)
    if candidate.casefold() not in taken:
        return candidate
    suffix = f" · {login}"
    base = clipped(desired, 48 - len(suffix.encode("utf-8"))) + suffix
    candidate, n = base, 2
    while candidate.casefold() in taken:
        tail = f" ({n})"
        candidate = clipped(base, 48 - len(tail.encode("utf-8"))) + tail
        n += 1
    return candidate


@transaction
def rename(name: str, owner, strategy: str) -> str:
    """Переименовать стратегию счёта. Возвращает новое отображаемое имя.

    Меняется именно стратегия, а не имя целиком: имя счёта — это «владелец ·
    стратегия», и записав туда введённый текст как есть, мы бы стёрли владельца.
    Где имя счёта — это только владелец (у него один счёт), оно и остаётся:
    там владелец как раз и нужен, а стратегия видна внутри аккаунта.
    """
    strategy = strategy.strip()
    if not strategy:
        raise ValueError("название не может быть пустым")
    acc = by_name(name, owner)
    if not acc:
        raise ValueError("счёт не найден")

    holder = acc.get("holder") or ""
    cabinet = acc.get("cabinet") or ""
    if strategy_taken(owner, cabinet, strategy, skip_login=acc["login"]):
        raise ValueError(f"в кабинете {cabinet or 'без номера'} уже есть счёт «{strategy}»")
    if holder and name == holder:
        new_name = name                             # имя — владелец, не трогаем
    elif holder and name.startswith(holder):
        new_name = f"{holder} · {strategy}"         # был суффикс — обновляем его
    else:
        new_name = strategy                         # владельца нет, имя = стратегия

    if any((other.get("cabinet") or "").strip().casefold() == cabinet.strip().casefold()
           and other["name"].casefold() == new_name.casefold()
           and int(other["login"]) != int(acc["login"]) for other in load(owner)):
        raise ValueError(f"в кабинете {cabinet or 'без номера'} уже есть счёт «{new_name}»")
    new_name = unique_storage_name(new_name, owner, cabinet, acc["login"], skip_login=acc["login"])
    if not update(name, owner, name=new_name, strategy=strategy):
        raise ValueError("счёт не найден")
    return new_name


@transaction
def toggle(name: str, owner, kind: str) -> bool:
    """Переключает один вид уведомлений (или сам счёт при kind='enabled')."""
    acc = by_name(name, owner)
    if not acc:
        raise ValueError("счёт не найден")
    if kind == "enabled":
        value = not acc.get("enabled", True)
        update(name, owner, enabled=value)
        return value
    notify = {**DEFAULT_NOTIFY, **(acc.get("notify") or {})}
    notify[kind] = not notify.get(kind, True)
    update(name, owner, notify=notify)
    return notify[kind]


@transaction
def share(logins: list, from_owner, to_owner) -> list[str]:
    """Копирует счета другому пользователю. Возвращает имена, под которыми легли.

    Счета выбираются по логину, а не по названию: название можно переименовать,
    и выданная раньше ссылка указывала бы в пустоту.
    Оригинал остаётся у владельца: это «поделиться», а не «передать».
    """
    if str(from_owner) == str(to_owner):
        raise ValueError("это твой же аккаунт")
    data = _read()
    added = []
    for login in logins:
        src = next((a for a in data
                    if int(a["login"]) == int(login) and str(a["owner"]) == str(from_owner)), None)
        if not src:
            continue
        if any(int(a["login"]) == int(login) and str(a["owner"]) == str(to_owner)
               and a["server"] == src["server"] for a in data):
            continue
        copy = dict(src)
        copy["shared_by"] = str(from_owner)
        copy["shared_origin"] = "explicit"
        copy["owner"] = int(to_owner)
        # у получателя может быть свой счёт с таким же названием
        taken = {a["name"] for a in data if str(a["owner"]) == str(to_owner)}
        candidate, n = copy["name"], 2
        while candidate in taken:
            candidate, n = f"{copy['name']} ({n})", n + 1
        copy["name"] = candidate
        data.append(copy)
        added.append(candidate)
    if added:
        save(data)
    return added
