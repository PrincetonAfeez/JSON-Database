# ADR 0006: OS File Locks

## Decision

The database uses OS-backed advisory file locks through a `FileLock` abstraction.

## Rationale

`threading.Lock` only protects threads inside one Python process. The database
file can be written by separate scripts or CLI invocations, so the lock must work
across processes.

## Trade-Off

Locking has platform-specific APIs. The implementation hides `msvcrt` on Windows
and `fcntl` on POSIX behind the same interface.
