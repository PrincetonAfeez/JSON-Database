"""Cross-platform process file locks."""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from types import TracebackType

from .errors import LockError, ValidationError


def validate_lock_timeout(timeout: float) -> None:
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValidationError("lock timeout must be a positive finite number")


def validate_lock_poll_interval(poll_interval: float) -> None:
    if not isinstance(poll_interval, (int, float)) or not math.isfinite(poll_interval) or poll_interval <= 0:
        raise ValidationError("lock poll_interval must be a positive finite number")


if os.name == "nt":
    import msvcrt

    def _platform_lock(fileno: int) -> None:
        msvcrt.locking(fileno, msvcrt.LK_NBLCK, 1)

    def _platform_unlock(fileno: int) -> None:
        msvcrt.locking(fileno, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _platform_lock(fileno: int) -> None:
        fcntl.flock(fileno, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _platform_unlock(fileno: int) -> None:
        fcntl.flock(fileno, fcntl.LOCK_UN)


class FileLock:
    """Exclusive advisory lock backed by a lock file."""

    def __init__(self, path: str | Path, timeout: float = 5.0, poll_interval: float = 0.05):
        validate_lock_timeout(timeout)
        validate_lock_poll_interval(poll_interval)
        self.path = Path(path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._file = None
        self._locked = False

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "a+b")
        try:
            self._ensure_lock_byte()
        except OSError as exc:
            self._file.close()
            self._file = None
            raise LockError(f"could not prepare lock file {self.path}: {exc}") from exc
        deadline = time.monotonic() + self.timeout
        last_error: OSError | None = None

        while True:
            try:
                self._try_lock()
                self._locked = True
                return
            except OSError as exc:
                last_error = exc
                if time.monotonic() >= deadline:
                    self._file.close()
                    self._file = None
                    raise LockError(
                        f"could not acquire database lock {self.path}; "
                        f"waited {self.timeout:g}s (pid {os.getpid()})"
                    ) from last_error
                time.sleep(self.poll_interval)

    def release(self) -> None:
        if self._file is None:
            return
        try:
            if self._locked:
                self._unlock()
        finally:
            self._locked = False
            self._file.close()
            self._file = None
            # Deliberately do NOT unlink the lock file. Unlinking races with
            # concurrent acquirers: a third process can create a new file at
            # the same path, claiming a brand-new inode whose lock is
            # independent of the one a waiter still holds. The OS file lock
            # is released by close above; the empty lock file persists across
            # runs. See ADR 0009.

    def _ensure_lock_byte(self) -> None:
        # `msvcrt.locking` locks a byte range, so the file must contain at
        # least one byte at offset 0 on Windows. `fcntl.flock` locks the
        # whole file regardless of size, so the byte is not needed on POSIX.
        if os.name != "nt":
            return
        assert self._file is not None
        self._file.seek(0, os.SEEK_END)
        if self._file.tell() == 0:
            self._file.write(b"\0")
            self._file.flush()
        self._file.seek(0)

    def _try_lock(self) -> None:
        assert self._file is not None
        self._file.seek(0)
        _platform_lock(self._file.fileno())

    def _unlock(self) -> None:
        assert self._file is not None
        self._file.seek(0)
        _platform_unlock(self._file.fileno())
