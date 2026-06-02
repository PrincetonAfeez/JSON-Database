"""Transaction context manager."""

from __future__ import annotations

import copy
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


class Transaction:
    """All-or-nothing database transaction.

    On `__enter__` the transaction acquires the database's exclusive file
    lock and loads a deep copy of the current on-disk state into memory.
    Every collection operation mutates that copy. On a clean `__exit__` the
    transaction calls `StorageEngine._commit_unlocked` (which re-runs the full
    state-shape validation, recomputes the checksum, and writes atomically).
    On any exception the in-memory state is discarded and the file is
    untouched. Nested transactions are rejected.
    """

    def __init__(self, database):
        self._database = database
        self._state: dict[str, Any] | None = None
        self._lock = None
        self._active = False

    def __enter__(self) -> "Transaction":
        if self._database._active_transaction is not None:
            raise TransactionError("nested transactions are not supported")
        self._lock = self._database._engine.lock()
        self._lock.__enter__()
        try:
            self._state = copy.deepcopy(self._database._engine.load())
            self._database._active_transaction = self
            self._active = True
            return self
        except BaseException:
            # Catches `Exception`, but also `KeyboardInterrupt` / `SystemExit`
            # raised by the user mid-`deepcopy` of a large state. Without the
            # broader catch, the OS file lock would be held until process exit
            # and the lock file would linger as a stale acquirer's anchor.
            self._lock.__exit__(None, None, None)
            self._lock = None
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            if exc_type is None:
                self._ensure_active()
                self._database._engine._commit_unlocked(self._state)
            return False
        finally:
            self._active = False
            self._state = None
            self._database._active_transaction = None
            if self._lock is not None:
                self._lock.__exit__(exc_type, exc, traceback)
                self._lock = None

    def collection(self, name: str) -> Collection:
        validate_collection_name(name)
        self._ensure_active()
        return Collection(self, name)

    def _insert(self, collection: str, document: dict[str, Any]) -> str:
        return insert_document(self._state_ref(), collection, document)

    def _get(self, collection: str, document_id: str) -> dict[str, Any]:
        return get_document(self._state_ref(), collection, document_id)

    def _update(self, collection: str, document_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        return update_document(self._state_ref(), collection, document_id, updates)

    def _replace(self, collection: str, document_id: str, document: dict[str, Any]) -> dict[str, Any]:
        return replace_document(self._state_ref(), collection, document_id, document)

    def _delete(self, collection: str, document_id: str) -> None:
        delete_document(self._state_ref(), collection, document_id)

    def _all(self, collection: str) -> list[dict[str, Any]]:
        return all_documents(self._state_ref(), collection)

    def _find(self, collection: str, criteria: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return find_documents(self._state_ref(), collection, criteria)

    def _where(self, collection: str, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        return where_documents(self._state_ref(), collection, predicate)

    def _upsert(self, collection: str, document_id: str, document: dict[str, Any]) -> str:
        return upsert_document(self._state_ref(), collection, document_id, document)

    def _bulk_insert(self, collection: str, documents: list[dict[str, Any]]) -> list[str]:
        return bulk_insert_documents(self._state_ref(), collection, documents)

    def _bulk_update(self, collection: str, updates: list[tuple[str, dict[str, Any]]]) -> int:
        return bulk_update_documents(self._state_ref(), collection, updates)

    @property
    def state(self) -> dict[str, Any]:
        """A deep copy of the transaction's in-memory state. Safe to mutate.
        Intended for callers outside this module that want to read the
        in-progress state (e.g., `Database.dump()` inside a transaction).
        Internal helpers in this module use `_state_ref` directly to avoid
        the copy."""
        return copy.deepcopy(self._state_ref())

    def _state_ref(self) -> dict[str, Any]:
        self._ensure_active()
        assert self._state is not None
        return self._state

    def _ensure_active(self) -> None:
        if not self._active or self._state is None:
            raise TransactionError("transaction is not active")
