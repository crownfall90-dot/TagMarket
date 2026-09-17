"""Deploy a reviewed source archive to the existing VPS, with code rollback.

Run with the VPS virtualenv: python deploy_miniapp.py /tmp/tagmarkets-miniapp.tgz
No account data or secrets may be present in the source archive.
"""
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from urllib.request import urlopen
from urllib.error import HTTPError
from dotenv import dotenv_values, set_key

ROOT = Path("/opt/tagmarkets")
FILES = {"accounts.py", "account_lock.py", "agent.py", "bot.py", "coordination.py",
         "ibportal.py", "miniapp.py", "partner.py", "store.py", "trades.py", "webhook_server.py",
         "requirements.txt", "README.md", "MINIAPP.md", "todo.md", "web/index.html",
         "web/app.js", "web/style.css", "web/brand.svg", "web/preview.json", "tools/selfcheck.py",
         "tools/test_miniapp.py", "tools/deploy_miniapp.py"}
SERVICES = ["tagmarkets-bot", "tagmarkets-webhook"]


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def main():
    if os.name != "posix" or not ROOT.is_dir() or not (ROOT / ".env").is_file():
        raise SystemExit("Only run on the existing /opt/tagmarkets Linux server")
    archive = Path(sys.argv[1]).resolve()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stage = ROOT / "releases" / stamp
    backup = ROOT / "backup" / (stamp + "-miniapp")
    stage.mkdir(parents=True)
    backup.mkdir(parents=True, mode=0o700)
    with tarfile.open(archive, "r:gz") as bundle:
        names = set()
        for member in bundle.getmembers():
            if not member.isfile() or member.name not in FILES:
                raise SystemExit("Archive contains unexpected files")
            names.add(member.name)
        if names != FILES:
            raise SystemExit("Archive is incomplete")
        bundle.extractall(stage, filter="data")
    python = str(ROOT / "venv/bin/python")
    run(python, "-m", "compileall", "-q", str(stage))
    for test in ("tools/selfcheck.py", "tools/test_miniapp.py"):
        result = run(python, str(stage / test), cwd=stage, capture_output=True)
        (stage / (Path(test).stem + ".log")).write_text(result.stdout + result.stderr)
        print(test, "PASS", flush=True)
    for name in FILES | {".env"}:
        src = ROOT / name
        if src.is_file():
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    settings = dotenv_values(ROOT / ".env")
    stopped = False
    migrated_accounts = False
    try:
        run("systemctl", "stop", *SERVICES)
        stopped = True
        for key, default in (("STATE_DB", "data/state.db"), ("TRADES_DB", "data/trades.db")):
            path = Path(settings.get(key) or default)
            if not path.is_absolute():
                path = ROOT / path
            if path.is_file():
                source = sqlite3.connect(path)
                destination = sqlite3.connect(backup / (key.lower() + ".db"))
                source.backup(destination)
                destination.close()
                source.close()
        acc_path = Path(settings.get("ACCOUNTS_FILE") or "data/accounts.json")
        if not acc_path.is_absolute():
            acc_path = ROOT / acc_path
        if acc_path.is_file():
            shutil.copy2(acc_path, backup / "accounts-before.json")
        for name in FILES:
            target = ROOT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / name, target)
        migrated_accounts = True
        run(python, "-c", "from dotenv import load_dotenv; load_dotenv('.env'); import accounts; accounts.migrate_passwords()", cwd=ROOT)
        set_key(str(ROOT / ".env"), "MINI_APP_URL", "https://crownfail.shop/tagmarkets/app/")
        run("systemctl", "start", "tagmarkets-webhook", "tagmarkets-bot")
        port = int(settings.get("WEBHOOK_PORT") or 8443)
        base = f"http://127.0.0.1:{port}"
        for attempt in range(15):
            try:
                with urlopen(base + "/health", timeout=3) as r:
                    if r.status == 200:
                        break
            except OSError:
                if attempt == 14:
                    raise
                time.sleep(2)
        with urlopen(base + "/app/", timeout=5) as r:
            if r.status != 200:
                raise RuntimeError("frontend unavailable")
        try:
            urlopen(base + "/api/bootstrap", timeout=5)
        except HTTPError as exc:
            if exc.code != 401:
                raise
        else:
            raise RuntimeError("API unexpectedly allows unsigned access")
        run("systemctl", "is-active", *SERVICES)
    except Exception:
        if stopped:
            for source in backup.rglob("*"):
                if source.is_file() and source.relative_to(backup).as_posix() in FILES | {".env"}:
                    shutil.copy2(source, ROOT / source.relative_to(backup))
            if migrated_accounts and (backup / "accounts-before.json").is_file():
                shutil.copy2(backup / "accounts-before.json", acc_path)
            run("systemctl", "restart", *SERVICES)
            print("Deployment rolled back; user databases were preserved", flush=True)
        raise
    try:
        run(python, "-c", "from dotenv import load_dotenv; load_dotenv('.env'); import accounts; from pathlib import Path; [accounts.encrypt_snapshot(str(p)) for p in Path('backup').glob('*/accounts-before.json')]", cwd=ROOT, capture_output=True)
    except subprocess.CalledProcessError:
        print("Warning: historical account backups still need credential migration", flush=True)
    print("Deployed. Backup:", backup)
    print("URL: https://crownfail.shop/tagmarkets/app/")


if __name__ == "__main__":
    main()
