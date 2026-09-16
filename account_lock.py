"""Cross-process lock for accounts.json read/modify/write transactions."""
import functools
import os
import threading
from contextlib import contextmanager

_mutex = threading.RLock()
_local = threading.local()


@contextmanager
def locked(path):
    with _mutex:
        if getattr(_local, "depth", 0):
            _local.depth += 1
            try:
                yield
            finally:
                _local.depth -= 1
            return
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path + ".lock", "a+b") as handle:
            if os.name == "nt":
                import msvcrt
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
            _local.depth = 1
            try:
                yield
            finally:
                _local.depth = 0
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def transaction(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        import accounts
        with locked(accounts.PATH):
            return fn(*args, **kwargs)
    return wrapped
