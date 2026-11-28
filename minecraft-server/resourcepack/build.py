"""Собирает harpy-express-ru.zip из src/ и печатает SHA-1 для server.properties.

Запуск: python3 build.py
Архив детерминированный (фиксированные даты), поэтому SHA-1 не меняется без правок в src/.
"""
import hashlib
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
OUT = os.path.join(HERE, "harpy-express-ru.zip")

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(SRC):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(root, name)
            arc = os.path.relpath(path, SRC).replace(os.sep, "/")
            info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, open(path, "rb").read())

data = open(OUT, "rb").read()
print("файл:", OUT)
print("размер:", len(data), "байт")
print("sha1:", hashlib.sha1(data).hexdigest())
