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

PATH = os.getenv("ACCOUNTS_FILE", os.path.join("data", "accounts.json"))
REQUIRED = ("owner", "name", "login", "password", "server")

# какие уведомления слать по счёту; по умолчанию все включены
NOTIFY_KINDS = {"trades": "Сделки", "deposits": "Пополнения", "withdrawals": "Выводы"}
DEFAULT_NOTIFY = {k: True for k in NOTIFY_KINDS}


def _read() -> list[dict]:
    if not os.path.exists(PATH):
        return []
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)


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
        acc["notify"] = {**DEFAULT_NOTIFY, **(acc.get("notify") or {})}
    if owner is None:
        return data
    return [a for a in data if str(a["owner"]) == str(owner)]


NO_CABINET = "—"    # для счетов, у которых кабинет ещё не указан


def cabinets(owner) -> dict[str, dict]:
    """Кабинеты пользователя: {customer_no: {holder, accounts:[...]}}."""
    out: dict[str, dict] = {}
    for acc in load(owner):
        key = acc.get("cabinet") or NO_CABINET
        group = out.setdefault(key, {"holder": acc.get("holder", ""), "accounts": []})
        if acc.get("holder") and not group["holder"]:
            group["holder"] = acc["holder"]
        group["accounts"].append(acc)
    return out


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


def save(data: list[dict]) -> None:
    """Пишет счета целиком. Сначала во временный файл, потом переименование.

    Файл переписывается на каждую правку (переименование, выключатель, новый
    счёт). Прямая запись означает, что обрыв посередине оставит обрезанный
    JSON — а в нём пароли и привязки всех счетов, восстанавливать неоткуда.
    Переименование внутри одной папки атомарно: либо старый файл, либо новый.
    """
    tmp = f"{PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())    # иначе при отключении питания останется пустой файл
    os.replace(tmp, PATH)


def add(acc: dict) -> None:
    if by_name(acc["name"], acc["owner"]):
        raise ValueError(f"счёт с именем {acc['name']} у тебя уже есть")
    if acc.get("strategy") and strategy_taken(acc["owner"], acc.get("holder"),
                                              acc["strategy"]):
        raise ValueError(f"у {acc.get('holder') or 'этого владельца'} уже есть "
                         f"стратегия {acc['strategy']}")
    save(_read() + [acc])


def remove(name: str, owner) -> bool:
    data = _read()
    left = [a for a in data
            if not (a["name"] == name and str(a["owner"]) == str(owner))]
    if len(left) == len(data):
        return False
    save(left)
    return True


def remove_login(login, owner) -> str:
    """Удалить счёт по номеру. Возвращает имя удалённого или пустую строку.

    По номеру, а не по имени: у получателя копия могла быть переименована, и
    забрать её обратно по нашему названию не вышло бы.
    """
    data = _read()
    left = [a for a in data
            if not (int(a["login"]) == int(login) and str(a["owner"]) == str(owner))]
    if len(left) == len(data):
        return ""
    gone = next(a["name"] for a in data
                if int(a["login"]) == int(login) and str(a["owner"]) == str(owner))
    save(left)
    return gone


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


def strategy_taken(owner, holder: str, strategy: str, skip_login=None) -> bool:
    """Занята ли такая стратегия у этого владельца.

    У разных людей стратегии могут называться одинаково — они и торгуются
    одинаково. А внутри одного владельца одинаковые названия неразличимы:
    непонятно, о какой из них уведомление и какую выключаешь.
    Сравниваем без учёта регистра: «sonic» и «SONIC» человек читает одинаково.
    """
    want = (strategy or "").strip().casefold()
    return any((a.get("strategy") or "").strip().casefold() == want
               and (a.get("holder") or "") == (holder or "")
               and (skip_login is None or int(a["login"]) != int(skip_login))
               for a in load(owner))


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
    if strategy_taken(owner, holder, strategy, skip_login=acc["login"]):
        raise ValueError(f"у {holder or 'этого владельца'} уже есть стратегия {strategy}")
    if holder and name == holder:
        new_name = name                             # имя — владелец, не трогаем
    elif holder and name.startswith(holder):
        new_name = f"{holder} · {strategy}"         # был суффикс — обновляем его
    else:
        new_name = strategy                         # владельца нет, имя = стратегия

    if new_name != name and by_name(new_name, owner):
        raise ValueError(f"счёт с именем {new_name} у тебя уже есть")
    if not update(name, owner, name=new_name, strategy=strategy):
        raise ValueError("счёт не найден")
    return new_name


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
        copy = dict(src)
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
