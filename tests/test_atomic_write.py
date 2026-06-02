"""Test atomic write functionality."""

import os

import pytest

from json_database import atomic
from json_database.atomic import atomic_write
from json_database.errors import StorageError


def test_atomic_write_replaces_file(tmp_path):
    path = tmp_path / "app.jsondb"
    path.write_bytes(b"old")

    atomic_write(path, b"new")

    assert path.read_bytes() == b"new"


def test_atomic_write_creates_missing_file(tmp_path):
    path = tmp_path / "subdir" / "app.jsondb"

    atomic_write(path, b"hello")

    assert path.read_bytes() == b"hello"


def test_crash_before_replace_leaves_original_intact(tmp_path, monkeypatch):
    """Simulate a crash *between* fsync of the temp file and os.replace."""
    path = tmp_path / "app.jsondb"
    path.write_bytes(b"old-complete")

    def boom(src, dst):
        raise OSError("simulated crash before atomic rename")

    monkeypatch.setattr(atomic.os, "replace", boom)
    with pytest.raises(StorageError):
        atomic_write(path, b"new-partial")

    assert path.read_bytes() == b"old-complete"
    leftover = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftover == [], f"temp file not cleaned up: {leftover}"


def test_atomic_write_preserves_posix_mode(tmp_path):
    """`tempfile.mkstemp` creates the temp file with mode 0600. Without
    intervention, `os.replace` would silently downgrade the target's mode on
    every commit. This test pins the preservation."""
    if os.name == "nt":
        import pytest

        pytest.skip("POSIX-only mode bits")

    path = tmp_path / "app.jsondb"
    path.write_bytes(b"old")
    os.chmod(path, 0o644)
    assert (path.stat().st_mode & 0o777) == 0o644

    atomic_write(path, b"new")

    assert (path.stat().st_mode & 0o777) == 0o644


def test_replace_retries_on_transient_permission_error(tmp_path, monkeypatch):
    """The Windows retry shim must transparently absorb a few transient
    `PermissionError`s and still succeed."""
    if os.name != "nt":
        pytest.skip("Windows-only retry path")

    path = tmp_path / "app.jsondb"
    path.write_bytes(b"old")

    real_replace = os.replace
    call_count = 0

    def flaky_replace(src, dst):
        nonlocal call_count
        call_count += 1
        if call_count < 4:
            raise PermissionError("simulated transient sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(atomic.os, "replace", flaky_replace)
    atomic_write(path, b"new")

    assert path.read_bytes() == b"new"
    assert call_count == 4


def test_fsync_happens_before_replace(tmp_path, monkeypatch):
    """The durability claim is `fsync(temp)` BEFORE `os.replace`; on POSIX a
    parent `fsync` follows. Order matters — recording counts alone is not
    enough to verify the contract."""
    path = tmp_path / "app.jsondb"
    operations: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def tracking_fsync(fd):
        operations.append("fsync")
        return real_fsync(fd)

    def tracking_replace(src, dst):
        operations.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(atomic.os, "fsync", tracking_fsync)
    monkeypatch.setattr(atomic.os, "replace", tracking_replace)
    atomic_write(path, b"hello")

    assert operations[0] == "fsync"
    assert operations[1] == "replace"
    if os.name == "nt":
        assert operations == ["fsync", "replace"]
    else:
        assert operations == ["fsync", "replace", "fsync"]
