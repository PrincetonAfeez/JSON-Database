# Contributing

This is an academic / portfolio project. The codebase is intentionally
small, stdlib-only, and reviewable end-to-end in one sitting. Contributions
that preserve those properties are welcome.

## Setup

```powershell
git clone <your-fork>
cd "JSON Database"
python -m pip install -e ".[dev]"
python -m pytest
```

No runtime dependencies. `pytest>=8` is the only dev dependency.

## Layering rules

The dependency arrow points one way only:

```
CLI -> Database -> Collection / Query / Transaction -> StorageEngine
                                                         |
                                       JsonSerializer, FileLock, atomic_write
                                                         |
                                                    filesystem
```

Concretely:

- `cli.py` may import from anywhere in the package.
- `database.py` and `transaction.py` must not call `os.replace`, `msvcrt`,
  or `fcntl` directly — they go through `StorageEngine`.
- `storage.py` owns file IO, locking, integrity, and atomic commits.
- `collection.py` may import `JsonSerializer` for dry-run validation but
  must not open files.

## Decision records

Architecturally meaningful choices land in `docs/adr/`. Each ADR is one
short page with three sections: Decision, Rationale, Trade-Off. Number
them in sequence (`0010-...`). Update `README.md` and `CHANGELOG.md`
alongside any change that affects the public API or on-disk shape.

## Tests

The suite is a mix of unit (per-module) and integration (CRUD, CLI,
concurrency). Every public-API change needs at least one test that pins
the new contract. Tests that spawn subprocesses are allowed but should
finish within a few seconds — keep the suite fast.

If you change `lock.py`, `atomic.py`, or `storage.py`, re-run the
multi-process tests in `tests/test_locking.py` and
`tests/test_concurrency.py`; those exercise the durability guarantees.
