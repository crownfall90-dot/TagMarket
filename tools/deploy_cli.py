"""Выкладка сервера: код из main → VPS одной командой, с ПК или из GitHub Actions.

Агенты на ПК обновляются из main сами, а сервер (бот, вебхук, Mini App) —
только выкладкой. Архив собирается из git, а не из рабочей папки: ни .env,
ни data/, ни локальные правки в него не попадут. Состав — строго FILES из
tools/deploy_miniapp.py той же ревизии; на сервере архив проверяет и ставит
этот же deploy_miniapp.py — тесты, снимок для отката, автоматический возврат
прежнего кода, если что-то не поднялось.

После выкладки на сервере остаётся метка с коммитом. Если с тех пор файлы
сервера не менялись (правили только документы или код агента), выкладывать
нечего — сервисы зря не перезапускаются.

    python tools/deploy_cli.py            # свежий main, спросит подтверждение
    python tools/deploy_cli.py --yes      # без вопросов
    python tools/deploy_cli.py --force    # даже если код сервера не менялся
    python tools/deploy_cli.py --yes --ref SHA --only-latest   # так зовёт deploy.yml
"""

import argparse
import ast
import io
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = "/opt/tagmarkets/venv/bin/python"
MARKER = "/opt/tagmarkets/.deployed_commit"
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


def server_unchanged(options, host, sha: str) -> bool:
    """Код сервера тот же, что уже выложен: файлы FILES не менялись с метки."""
    found = subprocess.run(["ssh", *options, host, "cat", MARKER],
                           capture_output=True, text=True)
    deployed = found.stdout.strip()
    if found.returncode or not deployed.isalnum():
        return False        # метки нет (первая выкладка, откат) — выкладываем
    try:
        names = release_files(sha)
        return subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", deployed, sha,
                               "--", *names]).returncode == 0
    except subprocess.CalledProcessError:
        return False        # выложенного коммита нет в истории — выкладываем


def main() -> int:
    parser = argparse.ArgumentParser(description="Выкладка сервера из main")
    parser.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    parser.add_argument("--force", action="store_true",
                        help="выложить, даже если код сервера не менялся")
    parser.add_argument("--ref", default="origin/main", help="что выкладывать (коммит)")
    parser.add_argument("--only-latest", action="store_true",
                        help="пропустить, если main уже ушёл дальше этого коммита")
    args = parser.parse_args()
    try:
        git("fetch", "--quiet", "origin", "main")
        sha = git("rev-parse", "--verify", f"{args.ref}^{{commit}}").decode().strip()
        latest = git("rev-parse", "origin/main").decode().strip()
        commit = git("log", "-1", "--format=%h  %s", sha).decode("utf-8", "replace").strip()
    except subprocess.CalledProcessError as exc:
        print("Не получилось взять код с GitHub:", exc.stderr.decode(errors="replace"))
        return 1
    if args.only_latest and sha != latest:
        # два слияния подряд: выложит запуск более нового, этот устарел
        print(f"main уже на {latest[:7]}, {sha[:7]} не выкладываю — выложит свежий запуск")
        return 0

    options, host = target()
    if not args.force and server_unchanged(options, host, sha):
        print(f"Код сервера с прошлой выкладки не менялся — {commit}\nВыкладывать нечего.")
        return 0
    print(f"\nВыкладываю на сервер версию:\n  {commit}\n")
    if not args.yes:
        try:
            if input("Enter — выложить, любой текст — отмена: ").strip():
                return 0
        except EOFError:
            return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive_remote = f"/tmp/tagmarkets-miniapp-{stamp}.tgz"
    script_remote = f"/tmp/tagmarkets-deploy-{stamp}.py"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "tagmarkets-miniapp.tgz"
        script = Path(tmp) / "deploy_miniapp.py"
        names = build(sha, archive)
        script.write_bytes(git("show", f"{sha}:tools/deploy_miniapp.py"))
        print(f"Архив собран: {len(names)} файлов. Отправляю на сервер…")
        try:
            subprocess.run(["scp", "-q", *options, str(archive), f"{host}:{archive_remote}"],
                           check=True)
            subprocess.run(["scp", "-q", *options, str(script), f"{host}:{script_remote}"],
                           check=True)
            print("Сервер проверяет и ставит (тесты, снимок для отката)…\n", flush=True)
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
    subprocess.run(["ssh", *options, host, f"echo {sha} > {MARKER}"], capture_output=True)
    print("\nГотово: сервер на версии", sha[:7])
    return 0


if __name__ == "__main__":
    sys.exit(main())
