# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-30

Initial public release. Reached through three iterated review passes
(40 + 26 + 15 findings respectively) starting from the build-ready scope
in `docs/scope/scope-build-ready.txt`.

### Added

- `Database`, `Collection`, and `Transaction` public API.
- `insert`, `get`, `update`, `replace`, `delete`, `all`, `find`, `where`,
  `upsert`, `bulk_insert`, `bulk_update` on collections.
- Query operators: `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`,
  `$nin`, `$contains`, `$exists` (exported as `OPERATORS`).
- Atomic whole-file writes via temp file + `fsync` + `os.replace`, with
  POSIX file-mode preservation.
- Cross-process `FileLock` over `fcntl` (POSIX) and `msvcrt` (Windows).
- Single-file SHA-256 integrity checksum.
- `IntegrityReport` with a typed `status` field
  (`ok` / `missing` / `corrupt` / `format` / `storage`).
- `JsonSerializer` round-trip for `datetime`, `date`, `Decimal`, `set`,
  and `bytes`. Non-finite floats and `Decimal` rejected; `frozenset`
  rejected with a specific message.
- `jsondb` CLI: `init`, `insert`, `get`, `update`, `replace`, `delete`,
  `query`, `dump`, `check`, `collections`, plus `--version` and
  `check --json` machine-readable output.
- Transaction read-routing through `Database`: reads on `db` inside an
  active transaction see the in-memory pre-commit state, never a stale
  on-disk snapshot.
- `Database` and `Transaction` are context managers.
- 80+ tests covering CRUD, transactions, atomicity, locking,
  serialization, queries, CLI, and multi-process concurrency.
- ADRs `0001`-`0009` documenting each architectural decision.

### Known limits

- Whole-file rewrite on every commit (no WAL, no append log).
- No indexes, no network server, no encryption, no schema migrations.
- Lock files persist on disk across runs (see ADR 0009 for the race that
  made cleanup unsafe).
