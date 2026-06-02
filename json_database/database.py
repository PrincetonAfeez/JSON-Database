"""Public Database API."""

from __future__ import annotations

import copy
from pathlib import Path
from types import TracebackType
from typing import Any, Callable

from .collection import (
    Collection,
    all_documents,
    bulk_insert_documents,
    bulk_update_documents,
    delete_document,
    find_documents,
    get_document,
    insert_document,
    replace_document,
    update_document,
    upsert_document,
    validate_collection_name,
    where_documents,
)
from .errors import TransactionError
from .lock import validate_lock_timeout
from .storage import IntegrityReport, StorageEngine


class Database:
    """Small JSON-backed document database.

    One `Database` instance owns its file lock for the duration of any write
    or transaction. Holding two `Database` instances on the same file in the
    same process is supported (writes still serialize through the OS file
    lock) but reads through the second instance see the on-disk snapshot of
    the first instance's open transaction, not its in-memory state. Use one
    `Database` per file per process for clarity. One instance should be used
    from one thread at a time; concurrent threads sharing a single instance
    can race on `_active_transaction` even though OS file locks still serialize
    writes.

    `Database` can be used as a context manager:

        with Database(path) as db:
            db.collection("users").insert({"name": "Ava"})

    Exiting the context with an unclosed transaction raises `TransactionError`
    (unless the body is already unwinding a different exception). If transaction
    cleanup itself fails while the body is already raising, the original
    exception is preserved and the cleanup error is not chained.
    """

    def __init__(self, path: str | Path, timeout: float = 5.0):
        validate_lock_timeout(timeout)
        self.path = Path(path)
        self._engine = StorageEngine(self.path, timeout=timeout)
        self._active_transaction = None

    def __enter__(self) -> "Database":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        leaked_tx = self._active_transaction
        if leaked_tx is None:
            return
        # Force the leaked transaction through its rollback path so the OS
        # file lock is released regardless of how we got here. Passing a
        # synthetic exc_type makes Transaction.__exit__ skip commit and just
        # tear down the lock. Then, if the body exited cleanly, raise a loud
        # error so the user notices the leaked transaction. If the body is
        # already unwinding a different exception, let that exception win.
        try:
            leaked_tx.__exit__(
                RuntimeError,
                RuntimeError("Database context exited with an open transaction"),
                None,
            )
        except Exception:
            # Tx cleanup failed for some reason — don't mask the original
            # exception (if any). The lock-leak risk is preferable to a
            # confusing chained error in the user's traceback.
            pass
        if exc_type is None:
            raise TransactionError(
                "Database context exiting with an open transaction; "
                "commit or roll back inside the `with` block first"
            )

    def collection(self, name: str) -> Collection:
        validate_collection_name(name)
        return Collection(self, name)

    def transaction(self):
        from .transaction import Transaction

        return Transaction(self)

    def init(self, *, force: bool = False) -> None:
        self._engine.create_empty(force=force)

    def check_integrity(self) -> IntegrityReport:
        """Verify the on-disk database file without mutating it.

        Always reads the file from disk, not an open transaction's in-memory
        state. Does not acquire the write lock; a concurrent writer may cause
        a transient read error under heavy contention.
        """
        return self._engine.check_integrity()

    def dump(self) -> dict[str, Any]:
        return self._read_state()

    def meta(self) -> dict[str, Any]:
        """Return the database meta block (format, version, timestamps,
        content_sha256). Inside a transaction this reflects the in-memory
        pre-commit state — `updated_at` and `content_sha256` are still the
        last committed values until the transaction is prepared for commit."""
        return self._read_state().get("meta", {})

    def collections(self) -> list[str]:
        return sorted(self._read_state().get("collections", {}).keys())

    def _read_state(self) -> dict[str, Any]:
        """Return a state dict the caller may mutate freely.

        In autocommit mode, `_engine.load()` always returns a freshly-parsed
        unique object. Inside a transaction, the caller would otherwise
        receive the live in-memory state; deep-copying here keeps the
        transaction's working copy untouched. Every read on `Database` flows
        through this method so the two modes can never disagree.
        """
        if self._active_transaction is not None:
            return copy.deepcopy(self._active_transaction._state_ref())
        return self._engine.load()

    def _insert(self, collection: str, document: dict[str, Any]) -> str:
        return self._write(lambda state: insert_document(state, collection, document))

    def _get(self, collection: str, document_id: str) -> dict[str, Any]:
        return get_document(self._read_state(), collection, document_id)

    def _update(self, collection: str, document_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        return self._write(lambda state: update_document(state, collection, document_id, updates))

    def _replace(self, collection: str, document_id: str, document: dict[str, Any]) -> dict[str, Any]:
        return self._write(lambda state: replace_document(state, collection, document_id, document))

    def _delete(self, collection: str, document_id: str) -> None:
        self._write(lambda state: delete_document(state, collection, document_id))

    def _all(self, collection: str) -> list[dict[str, Any]]:
        return all_documents(self._read_state(), collection)

    def _find(self, collection: str, criteria: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return find_documents(self._read_state(), collection, criteria)

    def _where(self, collection: str, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        return where_documents(self._read_state(), collection, predicate)

    def _upsert(self, collection: str, document_id: str, document: dict[str, Any]) -> str:
        return self._write(lambda state: upsert_document(state, collection, document_id, document))

    def _bulk_insert(self, collection: str, documents: list[dict[str, Any]]) -> list[str]:
        return self._write(lambda state: bulk_insert_documents(state, collection, documents))

    def _bulk_update(self, collection: str, updates: list[tuple[str, dict[str, Any]]]) -> int:
        return self._write(lambda state: bulk_update_documents(state, collection, updates))

    def _write(self, mutator):
        if self._active_transaction is not None:
            raise TransactionError("database has an active transaction; use tx.collection(...)")
        return self._engine.update(mutator)
