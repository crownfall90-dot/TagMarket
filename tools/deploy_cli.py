"""Выкладка сервера с этого ПК: код из origin/main → VPS одной командой.

Агенты на ПК обновляются из main сами, а сервер (бот, вебхук, Mini App) —
только выкладкой. Архив собирается из git, а не из рабочей папки: ни .env,
ни data/, ни локальные правки в него не попадут. Состав — строго FILES из
tools/deploy_miniapp.py той же ревизии; на сервере архив проверяет и ставит
этот же deploy_miniapp.py — тесты, снимок для отката, автоматический возврат
прежнего кода, если что-то не поднялось.

    python tools/deploy_cli.py          # спросит подтверждение
    python tools/deploy_cli.py --yes    # без вопросов
"""

import ast
import io
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = "origin/main"
PYTHON = "/opt/tagmarkets/venv/bin/python"
# тот же сервер и ключ, что в пульте TagMarkets.bat; адрес tagvps из
# ~/.ssh/config (им пользуется откат) важнее, если он настроен
KEY = Path.home() / ".ssh" / "tagmarkets_vps"
VPS, PORT = "root@89.44.86.228", "2222"


def git(*args) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                          capture_output=True).stdout


def release_files(ref: str) -> list[str]:
    """FILES из deploy_miniapp.py этой ревизии — сервер примет ровно их."""
    source = git("show", f"{ref}:tools/deploy_miniapp.py").decode("utf-8")
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "FILES" for t in node.targets)):
            return sorted(ast.literal_eval(node.value))
    raise SystemExit("В tools/deploy_miniapp.py не найден список FILES")


def build(ref: str, out: Path) -> list[str]:
    """Архив только из файлов: каталоги сервер отвергает как лишнее."""
    names = release_files(ref)
    now = int(time.time())
    with tarfile.open(out, "w:gz") as bundle:
        for name in names:
            data = git("show", f"{ref}:{name}")
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o644, now
            bundle.addfile(info, io.BytesIO(data))
    return names


def target() -> tuple[list[str], str]:
    """Опции ssh/scp и адрес сервера."""
    config = Path.home() / ".ssh" / "config"
    try:
        if "host tagvps" in config.read_text(errors="ignore").lower():
            return ["-o", "BatchMode=yes"], "tagvps"
    except OSError:
        pass
    return ["-o", "BatchMode=yes", "-o", f"Port={PORT}", "-i", str(KEY)], VPS


def main() -> int:
    ask = "--yes" not in sys.argv[1:]
    try:
        git("fetch", "--quiet", "origin", "main")
        commit = git("log", "-1", "--format=%h  %s", REF).decode("utf-8", "replace").strip()
    except subprocess.CalledProcessError as exc:
        print("Не получилось взять свежий main с GitHub:", exc.stderr.decode(errors="replace"))
        return 1
    print(f"\nВыкладываю на сервер версию main:\n  {commit}\n")
    if ask:
        try:
            if input("Enter — выложить, любой текст — отмена: ").strip():
                return 0
        except EOFError:
            return 0

    options, host = target()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive_remote = f"/tmp/tagmarkets-miniapp-{stamp}.tgz"
    script_remote = f"/tmp/tagmarkets-deploy-{stamp}.py"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "tagmarkets-miniapp.tgz"
        script = Path(tmp) / "deploy_miniapp.py"
        names = build(REF, archive)
        script.write_bytes(git("show", f"{REF}:tools/deploy_miniapp.py"))
        print(f"Архив собран: {len(names)} файлов. Отправляю на сервер…")
        try:
            subprocess.run(["scp", "-q", *options, str(archive), f"{host}:{archive_remote}"],
                           check=True)
            subprocess.run(["scp", "-q", *options, str(script), f"{host}:{script_remote}"],
                           check=True)
            print("Сервер проверяет и ставит (тесты, снимок для отката)…\n")
            result = subprocess.run(["ssh", *options, host, PYTHON, script_remote,
                                     archive_remote])
        except (OSError, subprocess.CalledProcessError) as exc:
            print("\nНе удалось связаться с сервером:", exc)
            print("Проверь ключ", KEY, "и что пульт TagMarkets.bat видит сервер.")
            return 1
        finally:
            subprocess.run(["ssh", *options, host, "rm", "-f", archive_remote, script_remote],
                           capture_output=True)
    if result.returncode:
        print("\nВыкладка не прошла — сервер вернул прежнюю версию, данные не тронуты.")
        return result.returncode
    print("\nГотово: сервер на версии", commit.split()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
