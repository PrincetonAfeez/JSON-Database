# JSON Database

A pure Python JSON document database that teaches durable storage by implementing
collections, UUID primary keys, atomic writes, whole-file locks, transactions,
custom serialization, and single-file SHA-256 integrity checks behind a reusable
library and thin CLI.

## Install For Local Development

```powershell
python -m pip install -e ".[dev]"
```

The runtime library has no dependencies outside the Python standard library.
The `[dev]` extra installs `pytest`.

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
python -m json_database --db app.jsondb insert users '{"name": "Princeton", "age": 20}'
python -m json_database --db app.jsondb get users <id>
python -m json_database --db app.jsondb update users <id> '{"age": 21}'
python -m json_database --db app.jsondb query users '{"age": {"$gt": 18}}'
python -m json_database --db app.jsondb check
python -m json_database --db app.jsondb check --json   # machine-readable
python -m json_database --version
```

After editable install, the same commands are available through `jsondb`.

`init` is optional — the first write creates the database file if it does not
exist yet. `init` is still useful when you want an empty on-disk file before
any documents are inserted.

### Missing database file behavior

`check` / `check_integrity()` report `status="missing"` when the file does not
exist. Other read paths (`dump`, `meta`, `collections`, `get`, `query`, …)
synthesize an in-memory empty database instead, so they succeed without
creating a file. Only a write (or explicit `init`) creates the file on disk.

### CLI exit codes

| Code | Meaning                                                                 |
| ---- | ----------------------------------------------------------------------- |
| 0    | Success                                                                 |
| 1    | Not found (missing collection or document)                              |
| 2    | Invalid user input, invalid JSON argument, invalid query, or transaction state error |
| 3    | Lock timeout                                                            |
| 4    | Integrity failure, missing database file, or invalid database format    |
| 5    | Storage failure or other unexpected internal error                      |

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

- `insert()` rejects user-supplied `id`. `replace()` and `upsert()` accept an
  `id` field only if it equals the target id — they preserve the id across
  the operation.
- `update()` is a shallow merge. The `id` field cannot appear in `updates`.
- Tuples encode as JSON arrays and round-trip back as Python lists. The one
  exception is a tuple inside a `set` — that round-trips as a tuple, because
  Python sets cannot hold lists.
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
- One `Database` instance per file per process; not thread-safe for concurrent
  use of the same instance.
- No document size or nesting-depth limits — pathological payloads can exhaust
  memory.

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

See `docs/adr/` for the decisions behind atomic write, whole-file locking,
the single-file checksum, and UUID primary keys.

## Tests

```powershell
python -m pytest
```
