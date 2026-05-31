# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] — 2026-05-31

Third documentation and edge-case pass after two implementation audits.

### Changed

- README expanded: query/collection semantics, integrity vs load errors,
  CLI surface and limits, API contract notes, multi-instance guidance,
  Python 3.11+ requirement, Database context-manager contract, ADR index.
- ADR 0008 updated to list `find()` / `where()` routing and exclude
  `check_integrity()` from transaction read-routing.
- Missing checksum reported as `format`, not `corrupt`, in integrity checks.
- CLI maps `QueryError` and `TransactionError` to exit code 2.
- Load-time validation for reserved document fields, collection names, and
  empty document ids.
- Document-id validation on all CRUD paths; lock timeout must be positive
  and finite at API, engine, and CLI layers.
- `FileLock` parameter errors standardized as `ValidationError`.

### Fixed

- Query criteria validated even on empty collections.
- Removed unused `CLIError` from the public API.
- Non-finite lock timeouts (`NaN`, `+inf`) no longer accepted (previously
  could spin forever in the lock loop).

### Tests

- Suite expanded to 137 tests covering API contract edges, CLI exit codes,
  integrity format cases, transaction read-routing, and query semantics.

### Documentation

- Added portfolio/evaluation docs: `docs/ACCEPTANCE.md`, `docs/WHAT_I_LEARNED.md`,
  `docs/adr/README.md`, `scripts/demo.py`, GitHub Actions CI workflow.

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
