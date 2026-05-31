# ADR 0009: Lock File Persists Across Process Exit

## Decision

`FileLock.release()` releases the OS file lock and closes its file handle
but does NOT unlink the lock file. The empty lock file accumulates on disk
and is reused by subsequent acquirers.

## Rationale

An earlier iteration of this lock attempted to clean up the lock file with
`Path.unlink()` after release. That introduced a race that violated the
process-safety guarantee on which the rest of the database depends.

POSIX trace:

```
A: open(lock_path, "a+b")  -> fd_a, inode I1
A: flock(fd_a, LOCK_EX)    -> success
B: open(lock_path, "a+b")  -> fd_b, inode I1
B: flock(fd_b, LOCK_EX|LOCK_NB) -> fails; sleeps, will retry
A: flock(fd_a, LOCK_UN); close(fd_a); unlink(lock_path)
   - I1 is now orphaned but still held open by B's fd_b
C: open(lock_path, "a+b")  -> NEW file, NEW inode I2 (path was missing)
C: flock(fd_c, LOCK_EX|LOCK_NB) -> success (no one holds I2)
B: flock(fd_b, LOCK_EX|LOCK_NB) -> success (no one holds I1)
   - Two processes now hold "the database lock" on different inodes.
```

Windows reproduces the same shape via `DeleteFile` releasing the path while
another handle is open.

Persisting the lock file pins every acquirer to the same inode for as long
as any process can reach the path. The OS releases the actual lock on
`close()`, which is enough for correctness.

## Trade-Off

The lock file accumulates on disk. For a learning embedded store this is
acceptable; the scope explicitly defers stale-lock metadata (PID, timestamp,
crash recovery) to V2 (see `scope-build-ready.txt` section 10 and
[ADR 0006](0006-os-file-locks.md)). The file is empty after first use and
costs only one inode.

This decision supersedes the unlink behaviour introduced earlier in the
build; the test suite explicitly pins the persistence (`tests/test_locking.py`).
