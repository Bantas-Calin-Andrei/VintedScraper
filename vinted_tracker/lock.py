"""Make sure only one tracker runs at a time (two would share one browser profile and double every check)."""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class AlreadyRunning(RuntimeError):
    """Another tracker holds the lock."""


@contextmanager
def single_instance(path: Path) -> Iterator[None]:
    """Hold an OS-level exclusive lock on `path` for the duration; released automatically if the process dies."""
    handle = open(path, "a+")
    try:
        try:
            _lock(handle)
        except OSError as exc:
            raise AlreadyRunning(f"another tracker is already running (lock: {path})") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()


if os.name == "nt":
    import msvcrt

    def _lock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
