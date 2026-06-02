"""Durable storage engine for the JSON database file."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar

from .atomic import atomic_write, windows_retry_on_permission_error
from .collection import validate_collection_name
from .errors import DatabaseFormatError, IntegrityError, SerializationError, StorageError, ValidationError
from .lock import FileLock, validate_lock_timeout
from .serializer import JsonSerializer, TYPE_KEY


FORMAT = "json_database"
VERSION = 1
T = TypeVar("T")

IntegrityStatus = Literal["ok", "missing", "corrupt", "format", "storage"]


@dataclass(frozen=True)
class IntegrityReport:
    """Result of `Database.check_integrity()`.

    `expected`/`actual` are populated only when `status == "corrupt"` so that a
    success report does not look like it is hiding a comparison.
    """

    path: Path
    ok: bool
    status: IntegrityStatus
    message: str
    expected: str | None = None
    actual: str | None = None


class StorageEngine:
    """Owns file IO, checksum verification, locking, and atomic commits."""

    def __init__(
        self,
        path: str | Path,
        *,
        timeout: float = 5.0,
        serializer: JsonSerializer | None = None,
    ):
        self.path = Path(path)
        validate_lock_timeout(timeout)
        self.timeout = timeout
        self.serializer = serializer or JsonSerializer(pretty=True)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    def lock(self) -> FileLock:
        return FileLock(self.lock_path, timeout=self.timeout)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return make_empty_state(serializer=self.serializer)
        try:
            raw = _read_bytes_atomic(self.path)
        except OSError as exc:
            raise StorageError(f"could not read database file {self.path}: {exc}") from exc
        if not raw:
            raise DatabaseFormatError(f"database file is empty: {self.path}")
        try:
            parsed = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DatabaseFormatError(f"invalid database JSON: {exc}") from exc
        self._validate_raw_document_fields(parsed)
        try:
            state = self.serializer._decode(parsed)
        except SerializationError as exc:
            raise DatabaseFormatError(f"invalid database JSON: {exc}") from exc
        self._validate_state_shape(state)
        self._verify_checksum(state)
        return state

    def create_empty(self, *, force: bool = False) -> None:
        with self.lock():
            if self.path.exists() and not force:
                raise StorageError(f"database file already exists: {self.path}")
            self._commit_unlocked(make_empty_state(serializer=self.serializer))

    def update(self, mutator: Callable[[dict[str, Any]], T]) -> T:
        with self.lock():
            state = self.load()
            result = mutator(state)
            self._commit_unlocked(state)
            return result

    def check_integrity(self) -> IntegrityReport:
        if not self.path.exists():
            return IntegrityReport(
                self.path,
                ok=False,
                status="missing",
                message=f"database file does not exist: {self.path}",
            )
        try:
            self.load()
        except IntegrityError as exc:
            return IntegrityReport(
                self.path,
                ok=False,
                status="corrupt",
                message=str(exc),
                expected=exc.expected,
                actual=exc.actual,
            )
        except DatabaseFormatError as exc:
            return IntegrityReport(self.path, ok=False, status="format", message=str(exc))
        except StorageError as exc:
            return IntegrityReport(self.path, ok=False, status="storage", message=str(exc))
        return IntegrityReport(self.path, ok=True, status="ok", message="integrity check passed")

    def _commit_unlocked(self, state: dict[str, Any]) -> None:
        prepared = self._prepare_for_commit(state)
        data = self.serializer.dumps(prepared)
        atomic_write(self.path, data)

    def _prepare_for_commit(self, state: dict[str, Any]) -> dict[str, Any]:
        self._validate_state_shape_for_commit(state)
        prepared = copy.deepcopy(state)
        meta = prepared.setdefault("meta", {})
        now = datetime.now(timezone.utc)
        meta.setdefault("format", FORMAT)
        meta.setdefault("version", VERSION)
        meta.setdefault("created_at", now)
        meta["updated_at"] = now
        meta["content_sha256"] = None
        meta["content_sha256"] = compute_checksum(prepared, self.serializer)
        self._validate_state_shape(prepared)
        return prepared

    def _validate_state_shape_for_commit(self, state: Any) -> None:
        # Validate against the full schema EXCEPT the checksum, which
        # `_prepare_for_commit` writes after this check. We do not mutate
        # `state` here — `_prepare_for_commit` works on a deep copy.
        if not isinstance(state, dict):
            raise DatabaseFormatError("database state must be an object")
        self._validate_state_shape(state, require_checksum=False)

    def _validate_raw_document_fields(self, state: Any) -> None:
        if not isinstance(state, dict):
            return
        collections = state.get("collections")
        if not isinstance(collections, dict):
            return
        for collection_name, documents in collections.items():
            try:
                validate_collection_name(collection_name)
            except ValidationError as exc:
                raise DatabaseFormatError(
                    f"invalid collection name {collection_name!r}: {exc} [{self.path}]"
                ) from exc
            if not isinstance(documents, dict):
                continue
            for document_id, document in documents.items():
                if not isinstance(document_id, str) or not document_id:
                    raise DatabaseFormatError(
                        f"document id cannot be empty [{self.path}]"
                    )
                if isinstance(document, dict):
                    if document.get("id") == "":
                        raise DatabaseFormatError(
                            f"document id field cannot be empty [{self.path}]"
                        )
                    _validate_raw_document_tree(document, self.path)

    def _validate_state_shape(self, state: Any, *, require_checksum: bool = True) -> None:
        if not isinstance(state, dict):
            raise DatabaseFormatError(f"database state must be an object [{self.path}]")
        meta = state.get("meta")
        collections = state.get("collections")
        if not isinstance(meta, dict):
            raise DatabaseFormatError(f"database meta must be an object [{self.path}]")
        if meta.get("format") != FORMAT:
            raise DatabaseFormatError(
                f"database format is not json_database: {meta.get('format')!r} [{self.path}]"
            )
        if meta.get("version") != VERSION:
            raise DatabaseFormatError(
                f"unsupported database version: {meta.get('version')!r} "
                f"(expected {VERSION}) [{self.path}]"
            )
        if require_checksum and not isinstance(meta.get("content_sha256"), str):
            raise DatabaseFormatError(f"database checksum missing [{self.path}]")
        if not isinstance(collections, dict):
            raise DatabaseFormatError(f"database collections must be an object [{self.path}]")
        for collection_name, documents in collections.items():
            try:
                validate_collection_name(collection_name)
            except ValidationError as exc:
                raise DatabaseFormatError(
                    f"invalid collection name {collection_name!r}: {exc} [{self.path}]"
                ) from exc
            if not isinstance(documents, dict):
                raise DatabaseFormatError(
                    f"collection must be an object: {collection_name} [{self.path}]"
                )
            for document_id, document in documents.items():
                if not isinstance(document_id, str):
                    raise DatabaseFormatError(
                        f"document id must be a string in {collection_name} [{self.path}]"
                    )
                if not document_id:
                    raise DatabaseFormatError(
                        f"document id cannot be empty in {collection_name} [{self.path}]"
                    )
                if not isinstance(document, dict):
                    raise DatabaseFormatError(
                        f"document must be an object: {collection_name}/{document_id} [{self.path}]"
                    )
                if document.get("id") != document_id:
                    raise DatabaseFormatError(
                        f"document id mismatch: {collection_name}/{document_id} [{self.path}]"
                    )

    def _verify_checksum(self, state: dict[str, Any]) -> None:
        expected = state["meta"].get("content_sha256")
        actual = compute_checksum(state, self.serializer)
        if expected != actual:
            raise IntegrityError(
                f"database checksum mismatch; file may be corrupt or modified "
                f"outside json_database [{self.path}]",
                expected=expected,
                actual=actual,
            )


def make_empty_state(*, serializer: JsonSerializer | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    state: dict[str, Any] = {
        "meta": {
            "format": FORMAT,
            "version": VERSION,
            "created_at": now,
            "updated_at": now,
            "content_sha256": None,
        },
        "collections": {},
    }
    active = serializer or JsonSerializer(pretty=True)
    state["meta"]["content_sha256"] = compute_checksum(state, active)
    return state


def _validate_raw_document_tree(document: dict[str, Any], path: Path) -> None:
    if TYPE_KEY in document:
        raise DatabaseFormatError(
            f"{TYPE_KEY} is reserved and cannot be a document field [{path}]"
        )
    for value in document.values():
        _validate_raw_value_for_reserved_keys(value, path)


def _validate_raw_value_for_reserved_keys(value: Any, path: Path) -> None:
    if isinstance(value, dict):
        keys = set(value.keys())
        if TYPE_KEY in keys:
            if keys != {TYPE_KEY, "value"}:
                raise DatabaseFormatError(
                    f"{TYPE_KEY} is reserved for internal serialization [{path}]"
                )
            return
        for item in value.values():
            _validate_raw_value_for_reserved_keys(item, path)
    elif isinstance(value, list):
        for item in value:
            _validate_raw_value_for_reserved_keys(item, path)


def _read_bytes_atomic(path: Path) -> bytes:
    """Read the database file, tolerating Windows' brief unavailability
    window during a concurrent writer's `os.replace`.

    POSIX `read` does not race with `rename`; one syscall returns the
    complete old or new file. On Windows, `CreateFile` for read can briefly
    return `ERROR_ACCESS_DENIED` while `MoveFileEx` is swapping the target.
    The shared `windows_retry_on_permission_error` shim is a no-op on POSIX
    and a small retry budget on Windows.
    """
    return windows_retry_on_permission_error(lambda: path.read_bytes())


def compute_checksum(state: dict[str, Any], serializer: JsonSerializer) -> str:
    """Hash the canonical JSON form of `state` with `content_sha256` nulled.

    Deep-copies `state` first so the temporary null does not leak back to the
    caller. This is the price of a single-file checksum envelope — the
    checksum field lives inside the very state it covers.
    """
    canonical = copy.deepcopy(state)
    canonical.setdefault("meta", {})["content_sha256"] = None
    digest = hashlib.sha256(serializer.canonical_dumps(canonical)).hexdigest()
    return digest
