# JSON Database

A pure Python JSON document database that teaches durable storage by implementing
collections, UUID primary keys, atomic writes, whole-file locks, transactions,
custom serialization, and single-file SHA-256 integrity checks behind a reusable
library and thin CLI.

![CI](https://github.com/PrincetonAfeez/JSON-Database/actions/workflows/ci.yml/badge.svg)

## Quick start (5 minutes)

```powershell
python -m pip install -e ".[dev]"
python -m json_database --db app.jsondb init
python -m json_database --db app.jsondb insert users '{"name": "Ava", "age": 20}'
python -m json_database --db app.jsondb check
python -m pytest -q
```

Optional durability demo: `python scripts/demo.py`

Portfolio docs: [Acceptance traceability](docs/ACCEPTANCE.md) · [What I learned](docs/WHAT_I_LEARNED.md) · [ADR index](docs/adr/README.md)

## Install For Local Development

```powershell
python -m pip install -e ".[dev]"
```

The runtime library has no dependencies outside the Python standard library.
Requires **Python 3.11+**. The `[dev]` extra installs `pytest`.

## Library Usage

```python
from json_database import Database, OPERATORS

with Database("app.jsondb") as db:
    users = db.collection("users")

    user_id = users.insert({"name": "Princeton", "age": 20})
    users.update(user_id, {"age": 21})
    users.where(lambda doc: doc["age"] >= 21)

    db.meta()           # {"format": "json_database", "version": 1, "content_sha256": "..."}
    db.collections()    # ["users"]
    print(sorted(OPERATORS))

    with db.transaction() as tx:
        tx.collection("users").insert({"name": "Ava"})
        tx.collection("logs").insert({"event": "created_user"})
        # `tx.state` is a deep copy of the in-memory pre-commit state.
        snapshot = tx.state
```

## CLI Usage

```powershell
python -m json_database --db app.jsondb init
python -m json_database --db app.jsondb init --force
python -m json_database --db app.jsondb insert users '{"name": "Princeton", "age": 20}'
python -m json_database --db app.jsondb get users <id>
python -m json_database --db app.jsondb update users <id> '{"age": 21}'
python -m json_database --db app.jsondb replace users <id> '{"name": "Mia"}'
python -m json_database --db app.jsondb delete users <id>
python -m json_database --db app.jsondb query users '{"age": {"$gt": 18}}'
python -m json_database --db app.jsondb dump
python -m json_database --db app.jsondb dump users
python -m json_database --db app.jsondb collections
python -m json_database --db app.jsondb check
python -m json_database --db app.jsondb check --json
python -m json_database --db app.jsondb --pretty dump
python -m json_database --db app.jsondb --timeout 10 insert users '{"name": "Ava"}'
python -m json_database --version
```

After editable install, the same commands are available through `jsondb`.

`init` is optional — the first write creates the database file if it does not
exist yet. `init` is still useful when you want an empty on-disk file before
any documents are inserted. Calling `init()` when the file already exists raises
`StorageError` unless `force=True` (or `init --force` on the CLI).

### CLI limits

The CLI covers single-document CRUD, equality/operator queries, dump, and
integrity check. It does **not** expose transactions, `bulk_*` operations,
predicate `where()` queries, or the library-only `upsert()` helper.

### Missing database file behavior

`check` / `check_integrity()` report `status="missing"` when the file does not
exist. Other read paths (`dump`, `meta`, `collections`, `get`, `query`, …)
synthesize an in-memory empty database instead, so they succeed without
creating a file. Only a write (or explicit `init`) creates the file on disk.

### CLI exit codes

| Code | Meaning | Example |
| ---- | ------- | ------- |
| 0 | Success | `get` after insert; `check` on valid file |
| 1 | Not found | `get users missing-id`; missing collection |
| 2 | Invalid input | Bad JSON; user-supplied `id`; invalid query operator; `--timeout 0` |
| 3 | Lock timeout | Another process holds the lock past `--timeout` |
| 4 | Integrity / format / missing file | `check` on tampered file; `insert` on corrupt DB; `check` when file absent |
| 5 | Storage failure | `init` without `--force` on existing file; disk full on write |

See [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) for requirement-to-test traceability.

### Integrity report shape (`check --json`)

```json
{
  "path": "/abs/path/app.jsondb",
  "ok": true,
  "status": "ok",
  "message": "integrity check passed",
  "expected": null,
  "actual": null
}
```

`status` is one of:

| Status     | Meaning                                                             |
| ---------- | ------------------------------------------------------------------- |
| `ok`       | Checksum matches, schema is valid.                                  |
| `missing`  | The database file does not exist at the given path.                 |
| `corrupt`  | Checksum mismatch — file was edited outside the library.            |
| `format`   | The file exists but JSON is unparseable, schema-invalid, or missing a checksum field. |
| `storage`  | The OS refused to read the file (permission denied, IO error, ...).|

`expected` and `actual` are populated only when `status == "corrupt"`.

### Integrity and load errors

Two paths inspect the database file:

| Path | When | On failure |
| ---- | ---- | ---------- |
| `check_integrity()` / `check` | Explicit audit; never mutates | Returns `IntegrityReport` with `status` (`missing`, `format`, `corrupt`, `storage`) |
| `load()` via reads/writes | Every autocommit operation | Raises `IntegrityError` (checksum mismatch) or `DatabaseFormatError` (bad JSON/shape) |

The CLI maps both exception types and a missing file from `check` to exit code **4**.
Mutating commands (`insert`, `update`, …) call `load()` first and therefore raise
on corrupt files instead of returning a report.

`check_integrity()` always reads **disk**, not an open transaction's in-memory
state, and does not acquire the write lock. Under heavy concurrent writes a check
may briefly see a transient read error (`status="storage"`).

## What It Supports

- Collections of JSON-like documents.
- UUID document IDs.
- Insert, get, update, replace, delete, all, upsert, and bulk operations.
- Equality queries plus operators: `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`,
  `$in`, `$nin`, `$contains`, `$exists` (also exported as `OPERATORS`).
- Predicate queries through `Collection.where(lambda doc: ...)`.
- Transaction context manager with all-or-nothing commit.

### Query semantics

- Plain equality `{field: value}` requires the field to **exist** on the
  document. A missing field does not match, even when `value` is `null`.
- `$ne` and `$nin` **do** match documents where the field is absent.
- Comparison operators (`$gt`, `$gte`, `$lt`, `$lte`) and `$contains` return
  no match (not an error) when operand types are incompatible.
- `$contains` on a **dict** tests **key** membership (`expected in actual`), not
  values inside the dict. On a **str** it tests **substring** membership.
- `$exists: true` matches only when the field is present; `$exists: false`
  matches when it is absent.
- Predicate exceptions inside `where()` are wrapped as `QueryError`.
- Multiple criteria keys in one object are ANDed together.

### Collection lookup semantics

- `all()`, `find()`, and `where()` on a **missing collection** return `[]`.
- `get()`, `update()`, `delete()`, and `replace()` on a missing collection
  raise `NotFoundError`.

- Atomic whole-file writes using temp file, fsync, and `os.replace`.
- Exclusive whole-file write lock (POSIX `fcntl` / Windows `msvcrt`).
- Single-file SHA-256 checksum envelope.
- Custom serialization for `datetime`, `date`, `Decimal`, `set`, and `bytes`.

### API contract notes

- Collection names must match `[A-Za-z0-9_-]+`, cannot be empty, cannot start
  with `__`, and cannot contain path separators.
- `insert()` rejects user-supplied `id`. `replace()` requires an existing
  document (`NotFoundError` if missing). `upsert()` creates the collection
  and document when absent. Both `replace()` and `upsert()` accept an `id`
  field in the body only when it equals the target id.
- `update()` is a shallow merge. The `id` field cannot appear in `updates`.
- `get()`, `update()`, `replace()`, `dump()`, and `Transaction.state` return
  **deep copies** safe to mutate without affecting stored state.
- `Database` may be used as a context manager (`with Database(path) as db:`).
  Exiting the block with an unclosed transaction raises `TransactionError` and
  rolls back the transaction so the OS file lock is released.
- Inside a transaction, `meta()` reflects the in-memory pre-commit state but
  `content_sha256` and `updated_at` remain the last **committed** values until
  the transaction commits.
- Tuples encode as JSON arrays and round-trip back as Python lists. The one
  exception is a tuple inside a `set` — that round-trips as a tuple, because
  Python sets cannot hold lists.
- Custom serialization covers `datetime`, `date`, `Decimal`, `set`, and `bytes`.
  `frozenset` is rejected with a specific error message.
- Non-finite floats (`NaN`, `Infinity`) and non-finite `Decimal` values are
  rejected on any write (insert, update, replace, upsert, bulk) so the on-disk
  JSON is strict-spec.

## Limits

- Whole-file rewrite on every commit.
- No indexes.
- No network server.
- No encryption.
- No schema migration system.
- No nested transactions.
- Reads are lock-free and rely on atomic replacement to see complete files.
- Two `Database` instances on the same file in one process are supported (writes
  serialize through the OS lock) but only one should hold an open transaction;
  the second instance reads the on-disk snapshot, not another instance's
  in-memory transaction state. Prefer one instance per file for clarity.
- Not thread-safe for concurrent use of the same `Database` instance.
- No document size or nesting-depth limits — pathological payloads can exhaust
  memory.

## Future work (out of scope for v1)

Deliberately not built — listed here as possible extensions, not roadmap promises:

- Indexes and query planning
- Append-only log / WAL instead of whole-file rewrite
- Network server or async API
- Encryption at rest
- Schema migration system
- OR / dotted-field queries, sort/limit/offset
- Optional Django + HTMX admin UI calling the same library APIs

See scope §14 in the build-ready scope document for the full V2 wish list.

## Architecture

```
       jsondb CLI
           │
           ▼
       Database  ──── transaction() ──►  Transaction
           │                                 │
           ▼                                 ▼
       Collection / query helpers  ◄────────┘
           │
           ▼
       StorageEngine
       │      │      │
       ▼      ▼      ▼
  JsonSerializer  FileLock  atomic_write
                   │             │
                   └──── filesystem
```

The dependency arrow only points down. The CLI layer never touches
`os.replace`, `msvcrt`, or `fcntl`; the document layer never opens files
directly. `Transaction` mutates an in-memory deep copy of the loaded state
and commits through the same `StorageEngine` seam every autocommit write
uses. The seam between the document layer and the storage engine is the
core architectural lesson.

Each database file `app.jsondb` has a sibling `app.jsondb.lock` lock file.
The lock file is empty (or one sentinel byte on Windows) and persists
across process exits — see [ADR 0009](docs/adr/0009-lock-file-persists.md)
for why unlinking it would race with concurrent acquirers.

See [docs/adr/README.md](docs/adr/README.md) for the full index. Summaries:

- **0001** atomic write · **0002** whole-file rewrite · **0003** whole-file lock
- **0004** UUID keys · **0005** checksum envelope · **0006** OS file locks
- **0007** integrity statuses · **0008** transaction read-routing · **0009** persistent lock file

## Tests

```powershell
python -m pytest
```

CI runs on **Ubuntu and Windows** with Python 3.11, 3.12, and 3.13 (see [.github/workflows/ci.yml](.github/workflows/ci.yml)). Current suite: **137 passed**, 1 skipped.
