"""Atomic file replacement helpers."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Callable, TypeVar

from .errors import StorageError


T = TypeVar("T")

# Windows MoveFileEx and CreateFile both surface transient races against a
# concurrent reader/writer as `PermissionError` (ERROR_ACCESS_DENIED = 5 or
# ERROR_SHARING_VIOLATION = 32). A short retry budget rides out the race;
# anything longer is not a transient race and should fail loudly.
#
# 10 attempts with linear backoff (10 ms, 20 ms, ... 90 ms) is roughly a
# 450 ms cumulative wait before the final retry — long enough for any
# realistic reader's open/read/close cycle, short enough not to mask a real
# permission problem.
_WINDOWS_RETRY_ATTEMPTS = 10
_WINDOWS_RETRY_BASE_SECONDS = 0.01


def windows_retry_on_permission_error(op: Callable[[], T]) -> T:
    """Run `op`, retrying on `PermissionError` when on Windows.

    POSIX `rename` and `read` are atomic against concurrent writers, so `op`
    runs once on POSIX. On Windows, the same syscalls can transiently fail
    while another process holds the destination open even for a single
    syscall's worth of time; retrying turns that race into a hiccup.
    """
    if os.name != "nt":
        return op()
    last_exc: PermissionError | None = None
    for attempt in range(_WINDOWS_RETRY_ATTEMPTS):
        try:
            return op()
        except PermissionError as exc:
            last_exc = exc
            if attempt == _WINDOWS_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_WINDOWS_RETRY_BASE_SECONDS * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def atomic_write(path: str | Path, data: bytes) -> None:
    """Write bytes with temp-file, fsync, and atomic replacement.

    On POSIX, `tempfile.mkstemp` creates the temp file with mode 0600. Without
    intervention, `os.replace` would silently downgrade the target's mode to
    0600 on every commit — stripping group/world-readable bits that another
    process or user may have relied on. We snapshot the existing target's mode
    and re-apply it to the temp file before the atomic rename.
    """

    target = Path(path)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    temp_path: str | None = None

    existing_mode = _existing_mode(target)

    try:
        fd, temp_path = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(parent))
        with os.fdopen(fd, "wb") as temp:
            fd = None
            temp.write(data)
            temp.flush()
            os.fsync(temp.fileno())
        if existing_mode is not None:
            try:
                os.chmod(temp_path, existing_mode)
            except OSError:
                # If chmod fails the temp file keeps mkstemp's 0600 mode.
                # The atomic replace still succeeds; permissions may narrow.
                pass
        _replace_with_retry(temp_path, target)
        temp_path = None
        _fsync_parent(parent)
    except OSError as exc:
        raise StorageError(f"atomic write failed for {target}: {exc}") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _existing_mode(target: Path) -> int | None:
    if os.name == "nt":
        return None
    try:
        return target.stat().st_mode & 0o777
    except OSError:
        return None


def _replace_with_retry(src: str, dst: Path) -> None:
    """`os.replace` with the shared Windows retry shim."""
    windows_retry_on_permission_error(lambda: os.replace(src, dst))


def _fsync_parent(parent: Path) -> None:
    if os.name == "nt":
        return
    try:
        dir_fd = os.open(parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)
