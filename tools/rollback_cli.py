"""Local interactive launcher for the VPS release history."""

import json
import subprocess
import sys

HOST = "tagvps"
REMOTE = "/opt/tagmarkets/tools/rollback_miniapp.py"
PYTHON = "/opt/tagmarkets/venv/bin/python"


def remote(*args, capture=False):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, PYTHON, REMOTE, *args],
                          text=True, encoding="utf-8", errors="replace",
                          capture_output=capture, check=True)


def main() -> int:
    try:
        versions = json.loads(remote("list", capture=True).stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print("Не удалось получить список резервных версий с сервера.")
        print(str(exc))
        return 1
    print("\nПоследние совместимые резервные версии:\n")
    if not versions:
        print("Пока нет снимков, пригодных для отката после включения шифрования MT5.")
        return 0
    for index, version in enumerate(versions, start=1):
        print(f"  {index:2}. {version[:4]}-{version[4:6]}-{version[6:8]} "
              f"{version[9:11]}:{version[11:13]}:{version[13:15]} UTC  ({version})")
    print("\nОткат заменяет код и интерфейс. Счета, базы, ключ и настройки сохраняются.")
    try:
        answer = input("Введите номер версии для отката или Enter для выхода: ").strip()
    except EOFError:
        return 0
    if not answer:
        return 0
    if not answer.isdecimal() or not 1 <= int(answer) <= len(versions):
        print("Неверный номер версии.")
        return 2
    chosen = versions[int(answer) - 1]
    try:
        confirmation = input(f"Для отката на {chosen} введите ROLLBACK: ").strip()
    except EOFError:
        confirmation = ""
    if confirmation != "ROLLBACK":
        print("Откат отменён.")
        return 0
    try:
        remote("restore", chosen)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Откат не завершён: {exc}")
        return 1
    print("Готово: https://crownfail.shop/tagmarkets/app/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
