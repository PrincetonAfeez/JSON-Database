# ADR 0008: Reads Through the Database Route to the Active Transaction

## Decision

When a transaction is open on a `Database` instance, reads performed through
that same instance — `db.collection("x").all()`, `db.collection("x").get(...)`,
`db.collection("x").find(...)`, `db.collection("x").where(...)`, `db.dump()`,
`db.meta()`, `db.collections()` — return the transaction's in-memory state,
not the on-disk snapshot. Writes through the database (outside `tx.collection`)
still raise `TransactionError`.

`check_integrity()` is **not** routed through the active transaction. It always
inspects the on-disk file.

## Rationale

A user who holds both a `Database` handle and a `Transaction` handle should
see one consistent picture of the database. The original implementation
returned stale, pre-transaction data when reading through the database, which
silently disagreed with reads through the transaction. Routing reads through
the active transaction makes the two handles agree.

The `_read_state` helper deep-copies the transaction's in-memory state so
callers cannot mutate the working copy by accident; `Transaction.state` is the
matching public accessor.

Integrity check is excluded because it is an explicit audit of durable bytes
on disk, not a view of uncommitted application state.

## Trade-Off

Holding two `Database` instances on the same file in the same process is
still supported (the OS file lock serializes their writes), but the second
instance does not know about the first's open transaction and so still reads
the on-disk snapshot. The recommended pattern is one `Database` per file per
process. This is a deliberate boundary of the V1 design — implementing a
cross-instance registry would buy little for a learning database.
