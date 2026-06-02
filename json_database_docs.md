# Architecture Decision Record
## App — JSON Database
**Embedded Storage Group | Document 1 of 5**
**Status: Accepted**

---

## Context

The Embedded Storage group requires a pure-Python JSON document database that demonstrates durable local storage without relying on SQLite, a server process, or a third-party database engine. The app must support named collections, UUID primary keys, CRUD operations, query operators, transactions, strict JSON serialization, atomic file replacement, file locking, and integrity checks.

The central architectural problem is not simply writing dictionaries to a JSON file. The project must protect user data against partial writes, concurrent writers, accidental external edits, invalid document shapes, unsupported values, and transaction leaks. The codebase therefore separates the public database API from collection mutation helpers, query evaluation, serialization, storage, locking, and CLI concerns.

The chosen architecture is a reusable library with a thin argparse CLI. The library exposes `Database`, `Collection`, `Transaction`, `IntegrityReport`, query operators, and project-specific exception classes. Storage is handled by `StorageEngine`, which owns load, validation, checksum verification, locking, and atomic commits.

---

## Decisions

### Decision 1 — Pure Python embedded database over SQLite or a server

**Chosen:** Build a small JSON-backed document database using only the Python standard library at runtime.

**Rejected:** SQLite, TinyDB, a network server, or an external document database.

**Reason:** The project is meant to teach durable storage mechanics directly: file layout, atomic writes, checksums, locks, transactions, and serialization. Using SQLite would solve most of those problems for the app and hide the learning target.

---

### Decision 2 — Whole-file rewrite on commit

**Chosen:** Every successful write commits the entire database file.

**Rejected:** Append-only log, WAL, per-collection files, or page-level updates.

**Reason:** Whole-file rewrite is simple, inspectable, and appropriate for a small educational embedded database. It keeps recovery logic small and makes the checksum envelope straightforward. The accepted trade-off is poor scaling for large datasets.

---

### Decision 3 — Atomic temp-file replacement

**Chosen:** Writes go to a temporary file in the same directory, flush and `fsync`, then replace the target with `os.replace`.

**Rejected:** Directly overwriting the database file.

**Reason:** Direct overwrites can leave a torn file if the process crashes mid-write. Atomic replacement gives readers either the previous complete file or the new complete file. POSIX also fsyncs the parent directory after replacement.

---

### Decision 4 — Exclusive whole-file write lock

**Chosen:** Every mutating operation acquires a sibling lock file named `<db>.lock`.

**Rejected:** No locking, per-collection locks, in-memory process locks only, or deleting the lock file after use.

**Reason:** The database file is a single durable unit. Whole-file locking serializes writers and matches the whole-file rewrite design. The lock file persists because unlinking lock files can race with concurrent acquirers.

---

### Decision 5 — Reads are lock-free

**Chosen:** Reads load the current file without taking the write lock.

**Rejected:** Locking every read.

**Reason:** Atomic replacement should let readers observe either the old complete database or the new complete database. This keeps read paths simple and avoids unnecessary contention. Integrity errors still surface if the file is externally corrupted.

---

### Decision 6 — Single-file checksum envelope

**Chosen:** Store `meta.content_sha256` inside the same JSON database file.

**Rejected:** No checksum or a separate checksum sidecar file.

**Reason:** A single-file database is easier to move and inspect. The checksum detects hand edits, partial corruption, and invalid modifications. Because the checksum field is inside the data it covers, checksum computation deep-copies state and temporarily nulls the checksum field.

---

### Decision 7 — UUID document primary keys

**Chosen:** `insert()` creates UUID string IDs and rejects user-supplied `id` fields.

**Rejected:** Sequential integer IDs or caller-supplied insert IDs.

**Reason:** UUIDs avoid needing a durable sequence counter and avoid collisions between independent inserts. `replace()` and `upsert()` may accept an `id` in the document only when it equals the target ID, preserving identity without allowing mutation of primary keys.

---

### Decision 8 — Collection state helpers separate from `Database`

**Chosen:** `collection.py` contains collection validation, CRUD mutation helpers, bulk operations, and document validation.

**Rejected:** Placing all document mutation directly inside `Database`.

**Reason:** `Database` should own storage orchestration. `Collection` should expose user-facing operations. Helper functions should mutate state dictionaries in a way that both autocommit writes and transactions can reuse.

---

### Decision 9 — Transactions mutate a deep in-memory copy

**Chosen:** `Transaction.__enter__()` acquires the database lock, loads a deep copy of on-disk state, mutates that copy, and commits on clean exit.

**Rejected:** Per-operation transaction writes or nested transactions.

**Reason:** Copy-on-enter provides all-or-nothing semantics while reusing the same validation/checksum/atomic-write commit path. Nested transactions are rejected because there is only one in-memory working state per database instance.

---

### Decision 10 — Strict deterministic serialization

**Chosen:** Use a custom `JsonSerializer` with deterministic JSON output, explicit type tags, UTF-8 bytes, sorted keys, and rejection of non-finite floats/Decimals.

**Rejected:** Python `pickle`, arbitrary object serialization, or JSON with `allow_nan=True`.

**Reason:** The on-disk file should remain JSON, inspectable, portable, and checksum-stable. Custom tags support common Python values while rejecting unsafe or ambiguous data.

---

### Decision 11 — Small Mongo-like operator query language

**Chosen:** Support equality plus `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin`, `$contains`, and `$exists`.

**Rejected:** SQL, dotted paths, OR queries, sort/limit/offset, or query planning.

**Reason:** The app needs useful filtering but not a full query engine. The operator set demonstrates comparison semantics, existence handling, and error boundaries without requiring indexes or planners.

---

### Decision 12 — Thin CLI over library APIs

**Chosen:** The CLI exposes `init`, `insert`, `get`, `update`, `replace`, `delete`, `query`, `dump`, `check`, and `collections`.

**Rejected:** Exposing every library feature in the CLI.

**Reason:** The CLI is for demonstration and simple operations. Transactions, bulk operations, predicate `where()`, and `upsert()` remain library-only to keep CLI scope controlled.

---

## Consequences

**Positive:**
- Storage behavior is explicit and teachable.
- The runtime has no third-party dependencies.
- Writes are atomic and guarded by OS-level locks.
- Integrity checks detect external edits and corrupt files.
- Transactions reuse the same commit path as autocommit writes.
- Deep-copy read behavior protects stored state from caller mutation.
- CLI exit codes give predictable shell behavior.
- The public API is small and portfolio-friendly.

**Negative / Trade-offs:**
- Whole-file rewrites do not scale to large datasets.
- No indexes or query planning.
- Reads are lock-free and may briefly hit transient storage status during concurrent replacement on some platforms.
- No encryption or access control.
- No schema migrations.
- Not thread-safe for sharing the same `Database` instance across concurrent threads.
- No nested transactions.
- JSON tags reserve `__jsondb_type__` as an internal key.

---

## Alternatives Not Explored

- SQLite backend.
- Append-only log / WAL.
- Per-collection files.
- Indexed queries.
- Dotted-field/nested query language.
- Network server mode.
- Encryption at rest.
- Async API.
- Django admin UI.

---

*Constitution reference: Article 1 (architectural thinking), Article 3.4 (larger project classification), Article 4 (engineering quality), Article 6 (behavior verification), and Article 7 (progressive complexity).*

---


# Technical Design Document
## App — JSON Database
**Embedded Storage Group | Document 2 of 5**

---

## Overview

JSON Database is a pure-Python embedded document database. It stores all data in one `.jsondb` file, organized as named collections of JSON-like documents. The database uses UUID primary keys, strict serialization, SHA-256 integrity metadata, atomic replacement, write locks, and transaction support.

**Package:** `json_database`  
**Console script:** `jsondb`  
**Module CLI:** `python -m json_database`  
**Python requirement:** `>=3.11`  
**Runtime dependencies:** none  
**Development dependency:** pytest  
**Current package version:** `0.1.1`

---

## Data Flow

### Autocommit write

```text
Collection.insert/update/replace/delete
  │
  ▼
Database._write(mutator)
  │
  ▼
StorageEngine.update()
  ├── acquire FileLock
  ├── load existing state
  ├── verify schema + checksum
  ├── run mutator against state
  ├── prepare meta/checksum
  ├── serializer.dumps()
  ├── atomic_write()
  └── release FileLock
```

---

### Read

```text
Collection.get/all/find/where or Database.dump/meta/collections
  │
  ▼
Database._read_state()
  ├── if transaction active: deep copy transaction state
  └── else: StorageEngine.load()
        ├── read bytes
        ├── parse JSON
        ├── decode custom tags
        ├── validate state shape
        └── verify checksum
```

---

### Transaction

```text
with db.transaction() as tx:
  │
  ▼
Transaction.__enter__()
  ├── reject nested transaction
  ├── acquire database lock
  ├── load state from disk
  └── deep-copy state into transaction memory

operations mutate transaction state only

clean exit
  │
  ▼
StorageEngine._commit_unlocked(transaction_state)
  ├── validate state
  ├── recompute checksum
  ├── atomic write
  └── release lock

exception exit
  │
  ▼
discard memory state and release lock
```

---

### Integrity check

```text
Database.check_integrity()
  │
  ▼
StorageEngine.check_integrity()
  ├── missing file → status=missing
  ├── load() success → status=ok
  ├── IntegrityError → status=corrupt
  ├── DatabaseFormatError → status=format
  └── StorageError → status=storage
```

---

## Module-Level Structure

```text
JSON-Database/
  json_database/
    __init__.py
    __main__.py
    atomic.py
    cli.py
    collection.py
    database.py
    errors.py
    lock.py
    query.py
    serializer.py
    storage.py
    transaction.py
  docs/
    ACCEPTANCE.md
    WHAT_I_LEARNED.md
    adr/
  scripts/
    demo.py
  tests/
  pyproject.toml
  README.md
  .github/workflows/ci.yml
```

---

## Module Dependency Graph

```text
json_database.__init__
  ├── database.Database
  ├── errors
  ├── query.OPERATORS
  └── storage.IntegrityReport

cli.py
  ├── Database
  ├── JsonSerializer
  └── errors mapped to exit codes

database.py
  ├── collection.Collection + state helpers
  ├── lock.validate_lock_timeout
  ├── storage.StorageEngine
  └── transaction.Transaction

collection.py
  ├── query.filter_documents / run_predicate
  ├── serializer.JsonSerializer
  └── errors

transaction.py
  ├── collection state helpers
  ├── database._engine.lock()
  └── database._engine._commit_unlocked()

storage.py
  ├── atomic.atomic_write
  ├── collection.validate_collection_name
  ├── lock.FileLock
  ├── serializer.JsonSerializer
  └── checksum / schema validation

atomic.py
  └── os.replace + temp file + fsync

lock.py
  ├── fcntl on POSIX
  └── msvcrt on Windows
```

---

## Core Data Structures

### Database file shape

```json
{
  "meta": {
    "format": "json_database",
    "version": 1,
    "created_at": "...",
    "updated_at": "...",
    "content_sha256": "..."
  },
  "collections": {
    "users": {
      "uuid": {
        "id": "uuid",
        "name": "Ava"
      }
    }
  }
}
```

---

### `Database`

Responsibilities:
- own path and `StorageEngine`
- create `Collection` handles
- expose `transaction()`
- expose `init()`, `check_integrity()`, `dump()`, `meta()`, and `collections()`
- route reads through `_read_state()`
- route autocommit writes through `_write()`
- reject autocommit writes while a transaction is active

---

### `Collection`

Public methods:
- `insert(document)`
- `get(document_id)`
- `update(document_id, updates)`
- `replace(document_id, document)`
- `delete(document_id)`
- `all()`
- `find(criteria=None)`
- `where(predicate)`
- `upsert(document_id, document)`
- `bulk_insert(documents)`
- `bulk_update(updates)`

---

### `Transaction`

Responsibilities:
- reject nested transactions
- acquire database file lock for full transaction lifetime
- deep-copy on-disk state
- mutate in-memory state
- commit only on clean exit
- rollback by discarding in-memory state on exception
- release lock on every exit path

---

### `IntegrityReport`

Fields:
- `path`
- `ok`
- `status`
- `message`
- `expected`
- `actual`

Statuses:
- `ok`
- `missing`
- `corrupt`
- `format`
- `storage`

---

### `JsonSerializer`

Supports:
- `None`, bool, str, int, finite float
- `datetime`
- `date`
- `Decimal`
- `bytes`
- `set`
- dict with string keys
- list / tuple

Rejects:
- non-finite float
- non-finite Decimal
- `frozenset`
- non-string dict keys
- unsupported Python objects
- reserved document field `__jsondb_type__`

---

## Function and Class Reference

### `Database(path, timeout=5.0)`

Creates a database handle. The file does not need to exist. Reads synthesize an empty state when the file is missing; writes create the file.

---

### `Database.init(force=False)`

Creates an empty database file. Raises `StorageError` if the file already exists and `force` is false.

---

### `Database.check_integrity()`

Reads the on-disk database and returns `IntegrityReport` without mutating the file.

---

### `Database.transaction()`

Returns a transaction context manager. Nested transactions are rejected.

---

### `insert_document()`

Validates a document, rejects user-supplied `id`, assigns a UUID, stores a deep copy, and returns the new ID.

---

### `update_document()`

Validates update dict, rejects `id`, shallow-merges updates into the existing document, and returns a deep copy.

---

### `replace_document()`

Validates the replacement document, requires the target document to exist, preserves the target ID, and allows an `id` field only when it matches the target ID.

---

### `upsert_document()`

Creates or replaces a document by caller-supplied ID. Allows an `id` field only when it matches the target ID.

---

### `bulk_insert_documents()`

Validates every document first, rejects user-supplied IDs, then inserts all documents with generated UUIDs.

---

### `bulk_update_documents()`

Validates every update and target document first. If any update is invalid, none apply.

---

### `matches(document, criteria)`

Evaluates equality and operator criteria. Multiple criteria keys are ANDed.

Supported operators:
- `$eq`
- `$ne`
- `$gt`
- `$gte`
- `$lt`
- `$lte`
- `$in`
- `$nin`
- `$contains`
- `$exists`

---

### `atomic_write(path, data)`

Writes bytes to a temp file, flushes, fsyncs, restores target mode on POSIX when possible, atomically replaces the target, and fsyncs the parent directory on POSIX.

---

### `FileLock(path, timeout=5.0, poll_interval=0.05)`

Cross-platform exclusive lock:
- POSIX: `fcntl.flock`
- Windows: `msvcrt.locking`

Lock file is not deleted after release.

---

## Error Handling Strategy

All expected application errors inherit from `JsonDBError`.

Error classes:
- `SerializationError`
- `LockError`
- `IntegrityError`
- `NotFoundError`
- `TransactionError`
- `QueryError`
- `ValidationError`
- `StorageError`
- `DatabaseFormatError`

CLI maps them to stable exit codes.

---

## External Dependencies

Runtime:
```text
None
```

Development:
```text
pytest>=8.3.5
```

---

## Concurrency Model

- Writes serialize through OS-backed file locks.
- Transactions hold the lock for the whole transaction.
- Reads are lock-free and rely on atomic replacement.
- Two `Database` instances pointing to the same file can serialize writes through the OS lock.
- A single `Database` instance is not thread-safe for concurrent use.
- Nested transactions are not supported.

---

## Known Limits

- Whole-file rewrite on every commit.
- No indexes.
- No query planner.
- No nested transactions.
- No encryption.
- No network server.
- No schema migration system.
- No document size or nesting-depth enforcement.
- No OR / dotted-field query language.
- Reads do not acquire the write lock.

---

## Design Patterns Used

- **Embedded library plus thin CLI**
- **Storage engine seam**
- **Collection facade**
- **State mutation helpers**
- **Atomic commit path**
- **Transaction copy-on-write**
- **Explicit checksum envelope**
- **Custom serializer with type tags**
- **Exception hierarchy**
- **Context manager cleanup**

---

## Verification Summary

The repo README documents CI on Ubuntu and Windows with Python 3.11 and 3.12, and a current suite of 137 passing tests with 1 skipped. The codebase also includes portfolio documentation, acceptance traceability, ADRs, and a durability demo script.

---

*Constitution reference: Article 4 (engineering quality), Article 6 (behavior verification), Article 7 (progressive complexity), and Article 8 (valid learner work).*

---


# Interface Design Specification
## App — JSON Database
**Embedded Storage Group | Document 3 of 5**

---

## Public CLI Interface

### Module invocation

```powershell
python -m json_database --db app.jsondb <command> [arguments]
```

### Console script

```powershell
jsondb --db app.jsondb <command> [arguments]
```

### Version

```powershell
jsondb --version
```

---

## Global CLI Options

| Option | Required | Default | Description |
|---|---:|---|---|
| `--db` | Yes | none | Path to database file |
| `--timeout` | No | `5.0` | Lock timeout in seconds |
| `--pretty` | No | false | Pretty-print JSON output |
| `--version` | No | none | Print CLI version |

---

## CLI Commands

| Command | Syntax | Description |
|---|---|---|
| `init` | `init [--force]` | Create empty database file |
| `insert` | `insert <collection> <document-json>` | Insert one document and print ID |
| `get` | `get <collection> <document_id>` | Print one document |
| `update` | `update <collection> <document_id> <updates-json>` | Shallow merge updates |
| `replace` | `replace <collection> <document_id> <document-json>` | Replace an existing document |
| `delete` | `delete <collection> <document_id>` | Delete a document |
| `query` | `query <collection> <criteria-json>` | Find documents matching criteria |
| `dump` | `dump [collection]` | Print full database or one collection |
| `check` | `check [--json]` | Verify database integrity |
| `collections` | `collections` | List collection names |

---

## CLI Exit Codes

| Code | Meaning |
|---:|---|
| `0` | Success |
| `1` | Not found |
| `2` | Invalid user input, JSON, query, transaction state, or lock timeout |
| `3` | Lock timeout |
| `4` | Integrity failure, missing database file, or invalid database format |
| `5` | Storage failure or unexpected internal JsonDB error |

---

## CLI Examples

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
```

---

## Library Interface

### Import

```python
from json_database import Database, OPERATORS
```

---

### Create database handle

```python
db = Database("app.jsondb", timeout=5.0)
```

---

### Context manager

```python
with Database("app.jsondb") as db:
    users = db.collection("users")
    user_id = users.insert({"name": "Ava"})
```

Exiting a `Database` context with an unclosed transaction raises `TransactionError` after attempting transaction cleanup.

---

### Collection CRUD

```python
users = db.collection("users")

user_id = users.insert({"name": "Ava", "age": 20})
user = users.get(user_id)
updated = users.update(user_id, {"age": 21})
replaced = users.replace(user_id, {"name": "Ava", "age": 22})
users.delete(user_id)
```

---

### Query

```python
users.find({"age": {"$gte": 21}})
users.where(lambda doc: doc["age"] >= 21)
```

---

### Upsert and bulk operations

```python
users.upsert("known-id", {"name": "Ava"})
ids = users.bulk_insert([{"name": "A"}, {"name": "B"}])
count = users.bulk_update([(ids[0], {"active": True})])
```

---

### Transaction

```python
with db.transaction() as tx:
    users = tx.collection("users")
    users.insert({"name": "Ava"})
    tx.collection("logs").insert({"event": "created_user"})
```

Behavior:
- clean exit commits all changes
- exception exit rolls back all changes
- nested transactions raise `TransactionError`
- autocommit writes on `db` while a transaction is active raise `TransactionError`

---

## Data Contract

### Collection names

Must:
- be a string
- be non-empty
- match `[A-Za-z0-9_-]+`
- not start with `__`
- not contain path separators

---

### Document IDs

- `insert()` generates UUID IDs.
- `insert()` rejects user-supplied `id`.
- `update()` rejects `id` in updates.
- `replace()` requires existing ID and preserves that ID.
- `upsert()` creates/replaces by target ID.

---

### Document values

Documents must be dicts. Supported values include JSON primitives plus:
- `datetime`
- `date`
- `Decimal`
- `set`
- `bytes`

Unsupported or rejected:
- non-string dict keys
- non-finite floats
- non-finite Decimals
- `frozenset`
- reserved `__jsondb_type__` field

---

## Query Contract

Plain equality:
```json
{"name": "Ava"}
```

Operators:
```json
{"age": {"$gt": 18}}
{"role": {"$in": ["admin", "staff"]}}
{"archived": {"$exists": false}}
```

Semantics:
- multiple criteria keys are ANDed
- plain equality requires field existence
- `$ne` and `$nin` match missing fields
- incompatible comparison types return no match
- `$contains` tests substring/list membership and dict key membership
- predicate exceptions in `where()` are wrapped as `QueryError`

---

## Integrity Report Contract

`check --json` returns:

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

Statuses:
- `ok`
- `missing`
- `corrupt`
- `format`
- `storage`

---

## Side Effects

| Operation | Side Effect |
|---|---|
| `init` | Creates database and lock file |
| `insert/update/replace/delete/upsert/bulk_*` | Acquires lock and rewrites database file |
| `transaction` clean exit | Commits one atomic rewrite |
| `transaction` exception exit | Discards in-memory state |
| `check` | Reads disk only; does not mutate |
| reads on missing DB | Synthesize empty in-memory state |

---

## Environment Variables

None required.

---

## Configuration Files

### `pyproject.toml`

Defines package metadata, Python requirement, zero runtime dependencies, pytest config, and the `jsondb` console script.

### `.github/workflows/ci.yml`

Runs pytest on Ubuntu and Windows across Python 3.11 and 3.12.

---

*Constitution reference: Article 4 (input/output boundaries), Article 6 (verification), and Article 8 (understandable and verifiable work).*

---


# Runbook
## App — JSON Database
**Embedded Storage Group | Document 4 of 5**

---

## Requirements

- Python 3.11+
- No runtime dependencies
- pytest for development/testing
- Filesystem that supports atomic replacement and advisory/byte-range locks

---

## Installation

```powershell
python -m pip install -e ".[dev]"
```

Runtime only:

```powershell
python -m pip install -e .
```

---

## Quick Start

```powershell
python -m json_database --db app.jsondb init
python -m json_database --db app.jsondb insert users '{"name": "Ava", "age": 20}'
python -m json_database --db app.jsondb check
python -m pytest -q
```

---

## Running Tests

```powershell
python -m pytest
python -m pytest -q
```

CI runs:

```powershell
python -m pytest -q --durations=10
```

on Ubuntu and Windows with Python 3.11 and 3.12.

---

## Standard Operating Procedures

### Initialize database

```powershell
jsondb --db app.jsondb init
```

Overwrite existing database:

```powershell
jsondb --db app.jsondb init --force
```

---

### Insert document

```powershell
jsondb --db app.jsondb insert users '{"name": "Ava", "age": 20}'
```

Expected:
```text
<uuid>
```

---

### Get document

```powershell
jsondb --db app.jsondb get users <id>
```

Expected:
```json
{"age":20,"id":"<id>","name":"Ava"}
```

---

### Update document

```powershell
jsondb --db app.jsondb update users <id> '{"age": 21}'
```

---

### Replace document

```powershell
jsondb --db app.jsondb replace users <id> '{"name": "Mia"}'
```

---

### Delete document

```powershell
jsondb --db app.jsondb delete users <id>
```

Expected:
```text
deleted: users/<id>
```

---

### Query documents

```powershell
jsondb --db app.jsondb query users '{"age": {"$gt": 18}}'
```

---

### Dump database

```powershell
jsondb --db app.jsondb dump
jsondb --db app.jsondb dump users
```

---

### Check integrity

```powershell
jsondb --db app.jsondb check
jsondb --db app.jsondb check --json
```

---

## Health Checks

### CLI version

```powershell
jsondb --version
```

Expected:
```text
jsondb 0.1.1
```

---

### Integrity check

```powershell
jsondb --db app.jsondb check
```

Healthy:
```text
OK: integrity check passed
```

---

### Library import

```powershell
python -c "from json_database import Database, OPERATORS; print(Database, sorted(OPERATORS))"
```

---

### Basic write/read

```powershell
$id = python -m json_database --db app.jsondb insert users '{"name":"Ava"}'
python -m json_database --db app.jsondb get users $id
```

---

## Expected Error Cases

### Existing database init without force

```powershell
jsondb --db app.jsondb init
```

Exit:
```text
5
```

---

### Missing document

```powershell
jsondb --db app.jsondb get users missing-id
```

Exit:
```text
1
```

---

### Invalid JSON argument

```powershell
jsondb --db app.jsondb insert users '{bad json}'
```

Exit:
```text
2
```

---

### Corrupt database

If file contents are edited manually and checksum no longer matches:

```powershell
jsondb --db app.jsondb check
```

Exit:
```text
4
```

---

### Lock timeout

If another writer holds the lock longer than timeout:

```powershell
jsondb --db app.jsondb --timeout 1 insert users '{"name":"Ava"}'
```

Exit:
```text
3
```

---

## Troubleshooting Decision Tree

```text
Command failed
  ├── Exit code 1?
  │   └── collection or document not found
  ├── Exit code 2?
  │   ├── invalid JSON argument
  │   ├── invalid query operator
  │   ├── invalid collection name
  │   ├── user supplied forbidden id
  │   └── invalid timeout
  ├── Exit code 3?
  │   └── another process holds the database lock
  ├── Exit code 4?
  │   ├── run check --json
  │   ├── inspect status: missing/corrupt/format/storage
  │   └── restore from backup if corrupt
  └── Exit code 5?
      ├── disk or filesystem failure
      ├── init attempted on existing DB
      └── unexpected storage issue
```

---

## Recovery Procedures

### Recover from accidental manual edit

1. Run:
   ```powershell
   jsondb --db app.jsondb check --json
   ```
2. If `status` is `corrupt`, restore a known-good copy.
3. Avoid editing `.jsondb` by hand unless recomputing checksum through the library.

---

### Recover from bad local test database

```powershell
Remove-Item app.jsondb, app.jsondb.lock -ErrorAction SilentlyContinue
jsondb --db app.jsondb init
```

---

### Recover from open transaction misuse

Always close transaction contexts:

```python
with db.transaction() as tx:
    tx.collection("users").insert({"name": "Ava"})
```

Do not start nested transactions.

---

### Recover from lock contention

1. Confirm another process is using the database.
2. Wait for it to finish.
3. Retry with a longer timeout:
   ```powershell
   jsondb --db app.jsondb --timeout 10 insert users '{"name":"Ava"}'
   ```

---

## Maintenance Notes

- Keep runtime dependencies empty unless a new ADR justifies adding one.
- Keep the storage engine below the document layer.
- Add tests before changing checksum, lock, or atomic-write behavior.
- Keep lock files persistent; do not unlink them after release.
- Do not expose transactions in the CLI unless the command contract is redesigned.
- Do not add indexes without documenting query planning and migration strategy.
- Preserve exit codes because shell users may depend on them.
- Preserve strict serialization and non-finite number rejection.

---

*Constitution reference: Article 6 (behavior verification), Article 5 (constraints and trade-offs), and Article 8 (verifiable learner work).*

---


# Lessons Learned
## App — JSON Database
**Embedded Storage Group | Document 5 of 5**

---

## Why This Design Was Chosen

This design was chosen because a JSON database is a storage-systems learning project disguised as a small utility. The obvious implementation would be to load a JSON file, mutate a dictionary, and write it back. That would work for a toy demo but would not teach durability.

The project instead treats durability as the main feature. Atomic writes, file locks, checksums, strict serialization, transaction cleanup, and deep-copy reads are first-class design choices. The result is still small, but it demonstrates real storage engineering concerns.

The separation between `Database`, `Collection`, `StorageEngine`, `JsonSerializer`, `FileLock`, and `Transaction` is the most important architectural lesson. Each module has a specific responsibility and a clear boundary.

---

## What Was Intentionally Omitted

**SQLite:** Omitted because it would hide the storage mechanics.

**Indexes:** Omitted because whole-file scan is enough for V1.

**Network server:** Omitted to keep the database embedded.

**Encryption:** Omitted because the project focuses on durability, not security.

**Schema migrations:** Omitted because document shape is flexible.

**Nested transactions:** Omitted because one active working copy per database is simpler and safer.

**Dotted-field queries and OR:** Omitted to keep the query evaluator small.

**CLI transactions and bulk operations:** Omitted to keep the CLI thin.

---

## Biggest Weakness

The biggest weakness is scalability. Whole-file rewrite is simple and durable, but it does not scale to large databases. Every write rewrites the entire file, every load parses the entire file, and every query scans documents in memory.

The second weakness is lack of schema migration support. The file has a format version, but there is no migration system for future versions.

The third weakness is that reads are lock-free. This is reasonable with atomic replacement, but it means integrity checks and load paths must handle corrupt or transient storage states cleanly.

---

## Scaling Considerations

**If data grows:**
- move from whole-file rewrite to append-only log or WAL
- add compaction
- add indexes
- add query planning
- add document size limits

**If concurrency grows:**
- consider read locks or snapshot isolation rules
- document multi-process expectations
- add stress tests for lock contention

**If schema evolves:**
- create migration runner
- version collection/document schemas
- add backup-before-migration behavior

**If security matters:**
- add encryption at rest
- add key management policy
- add file permission checks

---

## What the Next Refactor Would Be

1. **Add an append-only journal** — reduce write cost and improve crash recovery story.

2. **Add optional indexes** — support faster equality queries on selected fields.

3. **Add migration framework** — make file format versioning actionable.

4. **Add JSON export/import commands** — formalize safe backup/restore workflows.

5. **Add more concurrency stress tests** — especially around Windows replace/read races.

---

## What This Project Taught

- **Durability is a feature.** Writing JSON is easy; writing JSON safely is the real problem.

- **Atomic replacement matters.** A temp file plus fsync plus `os.replace` is a meaningful upgrade over direct writes.

- **Locks are subtle.** Deleting a lock file can create races; persistence of the lock file is intentional.

- **Checksums need canonical serialization.** A checksum only works when the bytes being hashed are deterministic.

- **Transactions need cleanup discipline.** A transaction must release locks even when exceptions occur.

- **Strict JSON is safer.** Rejecting non-finite numbers prevents invalid JSON and unstable checksums.

- **Deep copies protect boundaries.** Returning live state from a database leaks internal mutability.

- **Small CLIs still need contracts.** Exit codes, error classes, and JSON output shapes matter.

---

*Constitution v2.0 checklist: This document satisfies Article 5 (trade-off documentation), Article 6 (verification), and Article 7 (progressive complexity) for JSON Database.*
