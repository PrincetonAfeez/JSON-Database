"""Collection API and document-state helpers."""

from __future__ import annotations

import copy
import re
import uuid
from pathlib import PurePath
from typing import Any, Callable, Protocol

from .errors import NotFoundError, SerializationError, ValidationError
from .query import filter_documents, run_predicate
from .serializer import TYPE_KEY, JsonSerializer


_COLLECTION_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_VALIDATION_SERIALIZER = JsonSerializer(pretty=False)


class CollectionOwner(Protocol):
    def _insert(self, collection: str, document: dict[str, Any]) -> str: ...

    def _get(self, collection: str, document_id: str) -> dict[str, Any]: ...

    def _update(self, collection: str, document_id: str, updates: dict[str, Any]) -> dict[str, Any]: ...

    def _replace(self, collection: str, document_id: str, document: dict[str, Any]) -> dict[str, Any]: ...

    def _delete(self, collection: str, document_id: str) -> None: ...

    def _all(self, collection: str) -> list[dict[str, Any]]: ...

    def _find(self, collection: str, criteria: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    def _where(self, collection: str, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]: ...

    def _upsert(self, collection: str, document_id: str, document: dict[str, Any]) -> str: ...

    def _bulk_insert(self, collection: str, documents: list[dict[str, Any]]) -> list[str]: ...

    def _bulk_update(self, collection: str, updates: list[tuple[str, dict[str, Any]]]) -> int: ...


class Collection:
    """Named group of JSON-like documents."""

    def __init__(self, owner: CollectionOwner, name: str):
        validate_collection_name(name)
        self._owner = owner
        self.name = name

    def insert(self, document: dict[str, Any]) -> str:
        """Insert a new document and return its UUID id. The caller may not supply `id`."""
        return self._owner._insert(self.name, document)

    def get(self, document_id: str) -> dict[str, Any]:
        return self._owner._get(self.name, document_id)

    def update(self, document_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Shallow-merge `updates` into the existing document. The `id` field cannot be changed."""
        return self._owner._update(self.name, document_id, updates)

    def replace(self, document_id: str, document: dict[str, Any]) -> dict[str, Any]:
        """Replace the document with `document`.

        Unlike `insert`, `document` MAY contain an `id` field as long as it equals
        `document_id` — the id is preserved across the replacement. Supplying a
        different id raises `ValidationError`.
        """
        return self._owner._replace(self.name, document_id, document)

    def delete(self, document_id: str) -> None:
        self._owner._delete(self.name, document_id)

    def all(self) -> list[dict[str, Any]]:
        return self._owner._all(self.name)

    def find(self, criteria: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._owner._find(self.name, criteria)

    def where(self, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        return self._owner._where(self.name, predicate)

    def upsert(self, document_id: str, document: dict[str, Any]) -> str:
        """Insert-or-replace by id. Like `replace`, the `id` field in `document`
        may be present but must equal `document_id`."""
        return self._owner._upsert(self.name, document_id, document)

    def bulk_insert(self, documents: list[dict[str, Any]]) -> list[str]:
        return self._owner._bulk_insert(self.name, documents)

    def bulk_update(self, updates: list[tuple[str, dict[str, Any]]]) -> int:
        """Apply many shallow-merge updates atomically. Returns the count of
        updates applied; call `get()` afterward if you need the merged
        document shape. If any update is invalid (missing document, bad
        value, attempted id change), none of the updates apply."""
        return self._owner._bulk_update(self.name, updates)


def validate_collection_name(name: str) -> None:
    if not isinstance(name, str):
        raise ValidationError("collection name must be a string")
    if not name:
        raise ValidationError("collection name cannot be empty")
    if name.startswith("__"):
        raise ValidationError("collection name cannot start with __")
    if PurePath(name).name != name or "/" in name or "\\" in name:
        raise ValidationError("collection name cannot contain path separators")
    if not _COLLECTION_RE.match(name):
        raise ValidationError("collection name may only contain letters, numbers, underscore, and dash")


def insert_document(state: dict[str, Any], collection: str, document: dict[str, Any]) -> str:
    validate_document(document)
    if "id" in document:
        raise ValidationError("insert() rejects user-supplied id")
    document_id = str(uuid.uuid4())
    stored = copy.deepcopy(document)
    stored["id"] = document_id
    _ensure_collection(state, collection)[document_id] = stored
    return document_id


def get_document(state: dict[str, Any], collection: str, document_id: str) -> dict[str, Any]:
    document = _get_document_ref(state, collection, document_id)
    return copy.deepcopy(document)


def update_document(
    state: dict[str, Any], collection: str, document_id: str, updates: dict[str, Any]
) -> dict[str, Any]:
    validate_document(updates)
    if "id" in updates:
        raise ValidationError("update() cannot change document id")
    document = _get_document_ref(state, collection, document_id)
    document.update(copy.deepcopy(updates))
    return copy.deepcopy(document)


def replace_document(
    state: dict[str, Any], collection: str, document_id: str, document: dict[str, Any]
) -> dict[str, Any]:
    validate_document(document)
    stored = copy.deepcopy(document)
    _validate_body_id("replace", stored, document_id)
    _get_document_ref(state, collection, document_id)
    stored["id"] = document_id
    _ensure_collection(state, collection)[document_id] = stored
    return copy.deepcopy(stored)


def delete_document(state: dict[str, Any], collection: str, document_id: str) -> None:
    _validate_document_id(document_id)
    documents = _get_collection_ref(state, collection)
    if document_id not in documents:
        raise NotFoundError(f"document not found: {collection}/{document_id}")
    del documents[document_id]


def all_documents(state: dict[str, Any], collection: str) -> list[dict[str, Any]]:
    documents = _get_collection_ref(state, collection, missing_ok=True)
    return [copy.deepcopy(document) for document in documents.values()]


def find_documents(
    state: dict[str, Any], collection: str, criteria: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return filter_documents(all_documents(state, collection), criteria)


def where_documents(
    state: dict[str, Any], collection: str, predicate: Callable[[dict[str, Any]], bool]
) -> list[dict[str, Any]]:
    return run_predicate(all_documents(state, collection), predicate)


def upsert_document(state: dict[str, Any], collection: str, document_id: str, document: dict[str, Any]) -> str:
    _validate_document_id(document_id)
    validate_document(document)
    stored = copy.deepcopy(document)
    _validate_body_id("upsert", stored, document_id)
    stored["id"] = document_id
    _ensure_collection(state, collection)[document_id] = stored
    return document_id


def bulk_insert_documents(state: dict[str, Any], collection: str, documents: list[dict[str, Any]]) -> list[str]:
    if not isinstance(documents, list):
        raise ValidationError("bulk_insert() expects a list of documents")
    for document in documents:
        validate_document(document)
        if "id" in document:
            raise ValidationError("bulk_insert() rejects user-supplied id")
    ids = [str(uuid.uuid4()) for _ in documents]
    collection_state = _ensure_collection(state, collection)
    for document_id, document in zip(ids, documents, strict=True):
        stored = copy.deepcopy(document)
        stored["id"] = document_id
        collection_state[document_id] = stored
    return ids


def bulk_update_documents(
    state: dict[str, Any], collection: str, updates: list[tuple[str, dict[str, Any]]]
) -> int:
    if not isinstance(updates, list):
        raise ValidationError("bulk_update() expects a list of updates")
    documents = _get_collection_ref(state, collection)
    normalized: list[tuple[str, dict[str, Any]]] = []
    for item in updates:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValidationError("bulk_update() expects (document_id, updates) pairs")
        document_id, update = item
        _validate_document_id(document_id)
        if document_id not in documents:
            raise NotFoundError(f"document not found: {collection}/{document_id}")
        validate_document(update)
        if "id" in update:
            raise ValidationError("bulk_update() cannot change document id")
        normalized.append((document_id, update))
    for document_id, update in normalized:
        documents[document_id].update(copy.deepcopy(update))
    return len(normalized)


def validate_document(document: Any) -> None:
    """Validate that a document is a JSON-serializable dict.

    Runs the serializer's `validate` (a dry-run encode) so unsupported types
    surface as `ValidationError` at the write-call boundary instead of as
    `SerializationError` from deep inside the commit path. The commit re-
    encodes anyway, so the cost is one extra traversal per write — a
    deliberate tradeoff for a clean exception contract.
    """
    if not isinstance(document, dict):
        raise ValidationError("document must be an object")
    _reject_reserved_type_key(document)
    try:
        _VALIDATION_SERIALIZER.validate(document)
    except SerializationError as exc:
        raise ValidationError(f"document contains unserializable value: {exc}") from exc


def _reject_reserved_type_key(value: Any) -> None:
    if isinstance(value, dict):
        if TYPE_KEY in value:
            raise ValidationError(f"{TYPE_KEY} is reserved for internal serialization")
        for item in value.values():
            _reject_reserved_type_key(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _reject_reserved_type_key(item)


def _ensure_collection(state: dict[str, Any], collection: str) -> dict[str, dict[str, Any]]:
    validate_collection_name(collection)
    collections = state.setdefault("collections", {})
    return collections.setdefault(collection, {})


def _get_collection_ref(
    state: dict[str, Any], collection: str, *, missing_ok: bool = False
) -> dict[str, dict[str, Any]]:
    validate_collection_name(collection)
    collections = state.get("collections") or {}
    if collection not in collections:
        if missing_ok:
            return {}
        raise NotFoundError(f"collection not found: {collection}")
    return collections[collection]


def _validate_body_id(operation: str, stored: dict[str, Any], document_id: str) -> None:
    if "id" in stored and stored["id"] != document_id:
        raise ValidationError(f"{operation}() cannot change document id")


def _validate_document_id(document_id: str) -> None:
    if not isinstance(document_id, str) or not document_id:
        raise ValidationError("document id must be a non-empty string")


def _get_document_ref(state: dict[str, Any], collection: str, document_id: str) -> dict[str, Any]:
    _validate_document_id(document_id)
    documents = _get_collection_ref(state, collection)
    if document_id not in documents:
        raise NotFoundError(f"document not found: {collection}/{document_id}")
    return documents[document_id]
