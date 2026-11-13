"""Экономия памяти процесса: aiogram без заранее собранных схем и мало арен malloc.

aiogram при импорте вызывает model_rebuild() для всех ~600 типов Telegram и
сразу строит их pydantic-схемы (~100 МБ), хотя типы объявлены с defer_build и
умеют собираться сами при первом использовании. Здесь на время импорта
aiogram.types этот вызов пропускается, а пространство имён, которое он
передавал (имена типов для ссылок вперёд), кладётся в модули aiogram — так
ленивая сборка находит те же имена. Схема строится только для типов, которые
реально встречаются (Update, Message, кнопки…): ~100 МБ вместо ~150.

Импортировать до первого `import aiogram`. Если aiogram уже загружен — ничего
не делает. Любая неожиданность — откат к обычному импорту.
"""
import sys


def _lazy_aiogram() -> None:
    if "aiogram" in sys.modules:
        return
    try:
        from pydantic import BaseModel
    except ImportError:
        return
    original = BaseModel.__dict__["model_rebuild"]
    namespaces: dict = {}
    skipped = []

    def skip(cls, *args, **kwargs):
        namespaces.update(kwargs.get("_types_namespace") or {})
        skipped.append((cls, args, kwargs))
        return None

    BaseModel.model_rebuild = classmethod(skip)
    try:
        import aiogram  # noqa: F401  — тянет aiogram.types
    finally:
        BaseModel.model_rebuild = original
    if not namespaces:
        # другая версия aiogram устроена иначе — собираем как обычно, ничего не теряя
        for cls, args, kwargs in skipped:
            cls.model_rebuild(*args, **kwargs)
        return
    for name, module in list(sys.modules.items()):
        if (name == "aiogram" or name.startswith("aiogram.")) and module is not None:
            for key, value in namespaces.items():
                module.__dict__.setdefault(key, value)


def _few_malloc_arenas() -> None:
    """glibc заводит до 8×ядер арен памяти — по одной на поток (to_thread, SQLite, MT5);
    каждая держит свои свободные куски, и процесс «распухает». Две арены хватает."""
    if not sys.platform.startswith("linux"):
        return
    import ctypes
    try:
        ctypes.CDLL("libc.so.6").mallopt(-8, 2)   # M_ARENA_MAX
    except (OSError, AttributeError):
        pass


_few_malloc_arenas()
try:
    _lazy_aiogram()
except Exception:   # pragma: no cover — память не повод ронять бота
    for _name in [n for n in sys.modules if n == "aiogram" or n.startswith("aiogram.")]:
        del sys.modules[_name]
