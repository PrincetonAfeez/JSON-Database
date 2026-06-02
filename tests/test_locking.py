"""Test locking functionality."""

import subprocess
import sys

import pytest

from json_database.errors import LockError, ValidationError
from json_database.lock import FileLock


def test_lock_timeout_in_current_process(tmp_path):
    lock_path = tmp_path / "app.jsondb.lock"

    with FileLock(lock_path, timeout=1):
        try:
            FileLock(lock_path, timeout=0.1, poll_interval=0.01).acquire()
        except LockError as exc:
            message = str(exc)
            assert "waited" in message
            # Error message must identify which lock file and which PID
            # surfaced the contention.
            assert "app.jsondb.lock" in message
            assert "pid" in message
        else:
            raise AssertionError("second lock unexpectedly acquired")


def test_lock_file_persists_after_release(tmp_path):
    """The lock file is deliberately NOT unlinked on release: unlinking races
    with a concurrent acquirer that holds the same inode open but is about
    to retry. See ADR 0009."""
    lock_path = tmp_path / "app.jsondb.lock"

    with FileLock(lock_path, timeout=1):
        assert lock_path.exists()

    assert lock_path.exists(), "lock file must persist; the OS lock is released by close, not unlink"


def test_lock_file_persists_after_subprocess_release(tmp_path):
    lock_path = tmp_path / "app.jsondb.lock"
    code = (
        "from json_database.lock import FileLock\n"
        f"with FileLock(r'{lock_path}', timeout=1):\n"
        "    pass\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert lock_path.exists(), "lock file persists across process exit; OS lock was released"


def test_two_concurrent_writers_serialize_cleanly(tmp_path):
    """Two subprocesses inserting into the same collection must both succeed
    (the second waits for the first) and the file must end up consistent."""
    from json_database import Database

    path = tmp_path / "app.jsondb"
    Database(path).init()

    code = (
        "import sys\n"
        "from json_database import Database\n"
        "db = Database(sys.argv[1], timeout=30)\n"
        "db.collection('items').insert({'name': sys.argv[2]})\n"
    )

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(path), f"item-{i}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for i in range(2)
    ]
    for proc in procs:
        stdout, stderr = proc.communicate(timeout=30)
        assert proc.returncode == 0, stderr

    db = Database(path)
    names = sorted(doc["name"] for doc in db.collection("items").all())
    assert names == ["item-0", "item-1"]
    assert db.check_integrity().ok


def test_four_concurrent_writers_all_commit(tmp_path):
    """A four-way race exercises the lock under more contention than the
    two-process variant. The deliberate lock-file persistence (ADR 0009)
    is what keeps each acquirer pinned to the same inode."""
    from json_database import Database

    path = tmp_path / "app.jsondb"
    Database(path).init()

    code = (
        "import sys\n"
        "from json_database import Database\n"
        "db = Database(sys.argv[1], timeout=60)\n"
        "db.collection('items').insert({'name': sys.argv[2]})\n"
    )

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(path), f"item-{i}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for i in range(4)
    ]
    for proc in procs:
        stdout, stderr = proc.communicate(timeout=60)
        assert proc.returncode == 0, stderr

    db = Database(path)
    names = sorted(doc["name"] for doc in db.collection("items").all())
    assert names == ["item-0", "item-1", "item-2", "item-3"]
    assert db.check_integrity().ok


def test_lock_rejects_non_positive_timeout_and_poll_interval(tmp_path):
    lock_path = tmp_path / "app.jsondb.lock"

    with pytest.raises(ValidationError, match="positive finite"):
        FileLock(lock_path, timeout=0)

    with pytest.raises(ValidationError, match="poll_interval"):
        FileLock(lock_path, poll_interval=0)

    with pytest.raises(ValidationError, match="positive finite"):
        FileLock(lock_path, timeout=float("nan"))

    with pytest.raises(ValidationError, match="positive finite"):
        FileLock(lock_path, timeout=float("inf"))


def test_lock_timeout_across_processes(tmp_path):
    lock_path = tmp_path / "app.jsondb.lock"
    code = (
        "from json_database.lock import FileLock\n"
        "from json_database.errors import LockError\n"
        f"path = r'{lock_path}'\n"
        "try:\n"
        "    FileLock(path, timeout=0.1, poll_interval=0.01).acquire()\n"
        "except LockError:\n"
        "    raise SystemExit(3)\n"
        "raise SystemExit(0)\n"
    )

    with FileLock(lock_path, timeout=1):
        result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True)

    assert result.returncode == 3
