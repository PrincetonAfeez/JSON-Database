# Contributing

This is an academic / portfolio project. The codebase is intentionally
small, stdlib-only, and reviewable end-to-end in one sitting. Contributions
that preserve those properties are welcome.

## Setup

```powershell
git clone <your-fork>
cd "JSON Database"
python -m pip install -e ".[dev]"
# or: python -m pip install -r requirements-dev.txt
python -m pytest
```

Requires **Python 3.11+**. No runtime dependencies outside the standard library.
Dev dependencies: `pytest>=8.3.5` (see `requirements-dev.txt` or `[dev]` extra).

## Portfolio / evaluation artifacts

- [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) — scope §18 traceability to tests
- [docs/WHAT_I_LEARNED.md](docs/WHAT_I_LEARNED.md) — one-page reflection
- [docs/adr/README.md](docs/adr/README.md) — architecture decision index
- [scripts/demo.py](scripts/demo.py) — durability / integrity demo

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

Verify layering after structural changes:

```powershell
rg "os\.replace|msvcrt|fcntl" json_database --glob "!lock.py" --glob "!atomic.py" --glob "!storage.py"
```

Expected: no matches outside `lock.py`, `atomic.py`, and `storage.py`.

## Decision records

Architecturally meaningful choices land in [docs/adr/](docs/adr/). Each ADR is one
short page with three sections: Decision, Rationale, Trade-Off. Number
them in sequence (`0010-...`). Update `README.md` and `CHANGELOG.md`
alongside any change that affects the public API or on-disk shape.

## Tests

The suite is a mix of unit (per-module) and integration (CRUD, CLI,
concurrency). **137 tests** (1 skipped) as of v0.1.1. Every public-API change
needs at least one test that pins the new contract. Tests that spawn subprocesses
are allowed but should finish within a few seconds — keep the suite fast.

If you change `lock.py`, `atomic.py`, or `storage.py`, re-run the
multi-process tests in `tests/test_locking.py` and
`tests/test_concurrency.py`; those exercise the durability guarantees.

CI (`.github/workflows/ci.yml`) runs `pytest` on Ubuntu and Windows with Python 3.11 and 3.12.
