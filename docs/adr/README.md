# Architecture Decision Records

Short records of meaningful design choices. Each ADR has **Decision**, **Rationale**, and **Trade-Off**.

| ADR | Title | Summary |
| --- | ----- | ------- |
| [0001](0001-atomic-write-temp-rename.md) | Atomic write via temp file + rename | Commits use temp file, fsync, then `os.replace` so readers never see half-written files. |
| [0002](0002-whole-file-rewrite.md) | Whole-file rewrite on commit | Every commit rewrites the full database file — simple, no WAL. |
| [0003](0003-whole-file-lock.md) | Exclusive whole-file write lock | One OS lock serializes all writers; transactions hold it for their full lifetime. |
| [0004](0004-uuid-primary-keys.md) | UUID primary keys | `insert()` generates UUID strings; callers cannot supply `id`. |
| [0005](0005-single-file-checksum.md) | Single-file SHA-256 checksum | Checksum lives inside the JSON envelope and is null during hash computation. |
| [0006](0006-os-file-locks.md) | OS file locks cross-process | `fcntl` on POSIX, `msvcrt` on Windows, hidden behind `FileLock`. |
| [0007](0007-integrity-report-status.md) | Structured integrity status | `check_integrity()` returns typed `status`: ok, missing, corrupt, format, storage. |
| [0008](0008-transaction-read-routing.md) | Transaction read-routing | Reads through the same `Database` instance see in-memory tx state; `check_integrity()` reads disk only. |
| [0009](0009-lock-file-persists.md) | Lock file persists | The `.lock` file is not unlinked on release to avoid inode races with concurrent acquirers. |

New decisions continue the sequence at `0010-...`. Update [README.md](../../README.md) and [CHANGELOG.md](../../CHANGELOG.md) when a decision changes the public API or on-disk format.
