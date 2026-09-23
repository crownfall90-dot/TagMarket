"""List and restore the last ten compatible server releases (code only).

Run on the VPS as root: python tools/rollback_miniapp.py list|restore ID.
User databases, MT5 key and .env are intentionally never restored.
"""

import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import urlopen

from dotenv import dotenv_values

ROOT = Path("/opt/tagmarkets")
BACKUPS = ROOT / "backup"
SERVICES = ("tagmarkets-bot", "tagmarkets-webhook")
VERSION = re.compile(r"\d{8}-\d{6}-miniapp\Z")
FILES = (
    "accounts.py", "account_lock.py", "agent.py", "bot.py", "coordination.py",
    "ibportal.py", "miniapp.py", "partner.py", "store.py", "trades.py",
    "webhook_server.py", "requirements.txt", "README.md", "docs/MINIAPP.md",
    "docs/todo.md", "web/index.html", "web/app.js", "web/style.css",
    "web/brand.svg", "web/preview.json", "tests/selfcheck.py",
    "tests/test_miniapp.py", "tools/deploy_miniapp.py",
)
# Копируются, если есть в снимке, но не требуются для совместимости — старые
# бэкапы без них всё ещё годны для отката (в отличие от FILES).
# картинки «Частых вопросов» появились позже: снимки до них должны оставаться
# пригодными для отката, поэтому они необязательны, как и audit.py
OPTIONAL_FILES = ("tools/audit.py", "docs/AUDIT_HOWTO.md",
                  "web/faq-neo-card.jpg", "web/faq-neo-stats.jpg", "web/faq-sonic-card.jpg",
                  "web/faq-sonic-stats.jpg", "web/faq-license.jpg", "web/faq-mt5.jpg", "web/faq-neo-myfxbook.jpg")
# Раскладка до переноса тестов и документов в tests/ и docs/: старые копии остаются пригодными.
OLD_MOVED = {"docs/MINIAPP.md": "MINIAPP.md", "docs/todo.md": "todo.md",
             "tests/selfcheck.py": "tools/selfcheck.py",
             "tests/test_miniapp.py": "tools/test_miniapp.py"}


def layout(path: Path) -> dict[str, str]:
    """Имя файла в текущей раскладке -> где он лежит в этой копии."""
    for names in ({n: n for n in FILES}, {n: OLD_MOVED.get(n, n) for n in FILES}):
        if all((path / old).is_file() and not (path / old).is_symlink() for old in names.values()):
            names = dict(names)
            names.update({n: n for n in OPTIONAL_FILES if (path / n).is_file()})
            return names
    return {}


def compatible(path: Path) -> bool:
    """Older code cannot read encrypted MT5 credentials, so never offer it."""
    if path.is_symlink() or not path.is_dir() or path.parent.resolve() != BACKUPS.resolve():
        return False
    if not layout(path):
        return False
    try:
        accounts = (path / "accounts.py").read_text(encoding="utf-8")
        requirements = (path / "requirements.txt").read_text(encoding="utf-8")
    except OSError:
        return False
    return ("enc:v1:" in accounts and "def migrate_passwords" in accounts
            and "cryptography" in requirements)


def versions() -> list[str]:
    return [p.name for p in sorted(BACKUPS.iterdir(), reverse=True)
            if VERSION.fullmatch(p.name) and compatible(p)][:10]


def run(*argv):
    subprocess.run(argv, check=True, cwd=ROOT)


def copy_code(source: Path, destination: Path) -> None:
    for name, old in layout(source).items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / old, target)


def snapshot_current() -> Path:
    while True:
        stamp = time.strftime("%Y%m%d-%H%M%S") + "-miniapp"
        path = BACKUPS / stamp
        try:
            path.mkdir(mode=0o700)
            break
        except FileExistsError:
            time.sleep(1)
    copy_code(ROOT, path)
    return path


def health() -> None:
    port = int(dotenv_values(ROOT / ".env").get("WEBHOOK_PORT") or 8443)
    base = f"http://127.0.0.1:{port}"
    for attempt in range(15):
        try:
            with urlopen(base + "/health", timeout=3) as response:
                if response.status == 200:
                    break
        except OSError:
            if attempt == 14:
                raise
            time.sleep(2)
    else:
        raise RuntimeError("health check failed")
    with urlopen(base + "/app/", timeout=5) as response:
        if response.status != 200:
            raise RuntimeError("frontend unavailable")
    try:
        urlopen(base + "/api/bootstrap", timeout=5)
    except HTTPError as exc:
        if exc.code != 401:
            raise
    else:
        raise RuntimeError("API unexpectedly allows unsigned access")
    run("systemctl", "is-active", *SERVICES)


def restore(version: str) -> None:
    # Validate again after acquiring the lock; a simultaneous deploy may add a version.
    if version not in versions():
        raise ValueError("Version is unavailable or incompatible with encrypted accounts")
    source = BACKUPS / version
    python = str(ROOT / "venv/bin/python")
    run(python, "-m", "compileall", "-q", str(source))
    for test in ("tests/selfcheck.py", "tests/test_miniapp.py"):
        result = subprocess.run([python, str(source / layout(source)[test])], cwd=source,
                                text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(f"{test} failed: {(result.stdout + result.stderr)[-500:]}")
        print(f"{test} PASS", flush=True)
    previous = snapshot_current()
    print(f"Current code saved: {previous.name}", flush=True)
    try:
        run("systemctl", "stop", *SERVICES)
        copy_code(source, ROOT)
        run("systemctl", "start", *SERVICES)
        health()
    except Exception:
        run("systemctl", "stop", *SERVICES)
        copy_code(previous, ROOT)
        run("systemctl", "start", *SERVICES)
        health()
        print("Restore failed; previous code returned and services are healthy", flush=True)
        raise
    # код больше не тот, что выложен из main: автовыкладка (deploy_cli.py)
    # сравнивает с этой меткой и иначе сочла бы, что выкладывать нечего
    (ROOT / ".deployed_commit").unlink(missing_ok=True)
    print(f"Restored {version}; live data and settings preserved", flush=True)


def main() -> None:
    if os.name != "posix" or not ROOT.is_dir() or not (ROOT / ".env").is_file():
        raise SystemExit("Only run on the existing /opt/tagmarkets Linux server")
    if len(sys.argv) == 2 and sys.argv[1] == "list":
        print(json.dumps(versions()))
        return
    if len(sys.argv) != 3 or sys.argv[1] != "restore":
        raise SystemExit("Usage: rollback_miniapp.py list | restore VERSION")
    with open(ROOT / ".release.lock", "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        restore(sys.argv[2])


if __name__ == "__main__":
    main()
