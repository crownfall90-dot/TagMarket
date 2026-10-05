"""Статическая проверка web/: ловит класс ошибок, которые уже случались.

Запуск: python tests/static_check.py

Что проверяется и какую ошибку это закрывает:
* style.css не обрезан и скобки сбалансированы — однажды при замене блока стилей
  терялся «хвост» файла со всеми более поздними правилами;
* в style.css на месте опорные селекторы каждого раздела — потеря их сразу видна;
* каждое действие data-action / button('…') имеет обработчик — кнопка без
  обработчика молча ничего не делала бы;
* #id, к которым обращается app.js, есть в index.html или в самом app.js — убранное
  из разметки поле ломало код (так упало окно проекта без поля валюты);
* удалённые возможности не оставляют ссылок в коде;
* если app.js или style.css изменились в последнем коммите, версия ?v= в
  index.html обновлена — иначе Telegram показывает старый файл из кэша.
"""
from pathlib import Path
import re
import subprocess
import sys

WEB = Path(__file__).resolve().parents[1] / "web"
APP = (WEB / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "style.css").read_text(encoding="utf-8")
HTML = (WEB / "index.html").read_text(encoding="utf-8")
errors = []


def fail(message):
    errors.append(message)


# ── style.css ─────────────────────────────────────────────────────────────
plain = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
plain = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', plain)
if plain.count("{") != plain.count("}"):
    fail(f"style.css: скобки не сбалансированы ({plain.count('{')} открывающих, {plain.count('}')} закрывающих)")
if not CSS.endswith("\n"):
    fail("style.css: файл не заканчивается переводом строки — возможно, обрезан")

SENTINELS = [
    ".topbar", ".mobile-nav", ".currency-menu", ".feed-day", ".feed-meta", ".forecast-milestones",
    ".forecast-events", ".pa-card", ".pa-grip", ".notification-item", ".nt-filters", ".guest-card",
    ".cmp-bubble", ".cmp-file", ".cmp-bubble-btn", ".bonus-fields", ".cap-switch", ".share-row",
    ".project-dynamics", ".forecast-dates", "#offline-bar", ".cubes-row", ".cube-detail",
]
for selector in SENTINELS:
    if selector not in CSS:
        fail(f"style.css: нет опорного селектора {selector} — часть стилей потеряна?")

# ── действия ──────────────────────────────────────────────────────────────
used = set(re.findall(r'data-action="([a-z0-9-]+)"', APP)) | set(re.findall(r"button\('([a-z0-9-]+)'", APP))
used |= set(re.findall(r'data-action="([a-z0-9-]+)"', HTML))
handled = set(re.findall(r"action===?'([a-z0-9-]+)'", APP)) | set(re.findall(r"""\[data-action=\\?"([a-z0-9-]+)\\?"\]""", APP))
prefixes = set(re.findall(r"action\.startsWith\('([a-z0-9-]+)'\)", APP))
for name in sorted(used):
    if name in handled or any(name.startswith(prefix) for prefix in prefixes):
        continue
    fail(f"app.js: у действия «{name}» нет обработчика")

# ── id ────────────────────────────────────────────────────────────────────
ids_in_html = set(re.findall(r'\bid="([\w-]+)"', HTML))
ids_in_js = set(re.findall(r'\bid="([\w-]+)"', APP)) | set(re.findall(r"\bid='([\w-]+)'", APP))
for ident in sorted(set(re.findall(r"\$\('#([\w-]+)'\)", APP))):
    lookups = len(re.findall(r"\$\('#" + re.escape(ident) + r"'\)", APP))
    if ident not in ids_in_html | ids_in_js and APP.count(ident) <= lookups:
        fail(f"app.js обращается к #{ident}, но такого id нет ни в index.html, ни в разметке app.js")

# ── удалённое не должно возвращаться ──────────────────────────────────────
for token in ("glassOn", "setGlass", "project-form-add", "forecast-calculate", "name=\"multi\"", "project-form-remove"):
    if token in APP:
        fail(f"app.js: осталась ссылка на удалённое «{token}»")

# ── версия файлов в index.html ────────────────────────────────────────────
try:
    changed = subprocess.run(["git", "diff", "--name-only", "HEAD~1", "HEAD"], capture_output=True,
                             text=True, cwd=WEB.parent, check=True).stdout.split()
    previous = subprocess.run(["git", "show", "HEAD~1:web/index.html"], capture_output=True, text=True,
                              cwd=WEB.parent, check=True, encoding="utf-8").stdout
except (OSError, subprocess.CalledProcessError):
    changed, previous = [], ""      # неглубокий клон CI или нет git — пропускаем
for name, pattern in (("web/app.js", r"app\.js\?v=([\w-]+)"), ("web/style.css", r"style\.css\?v=([\w-]+)")):
    if name in changed and previous:
        before = re.search(pattern, previous)
        after = re.search(pattern, HTML)
        if before and after and before.group(1) == after.group(1) and "web/index.html" not in changed:
            fail(f"{name} изменён, а версия ?v= в index.html прежняя ({after.group(1)}) — клиенты получат файл из кэша")

if errors:
    print("Статическая проверка web/ не пройдена:")
    for message in errors:
        print(" -", message)
    sys.exit(1)
print("Статическая проверка web/: ок")
