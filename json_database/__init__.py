"""A small JSON-backed document database."""

from .database import Database
from .errors import (
    DatabaseFormatError,
    IntegrityError,
    JsonDBError,
    LockError,
    NotFoundError,
    QueryError,
    SerializationError,
    StorageError,
    TransactionError,
    ValidationError,
)
from .query import OPERATORS
from .storage import IntegrityReport

__version__ = "0.1.1"

__all__ = [
    "Database",
    "DatabaseFormatError",
    "IntegrityError",
    "IntegrityReport",
    "JsonDBError",
    "LockError",
    "NotFoundError",
    "OPERATORS",
    "QueryError",
    "SerializationError",
    "StorageError",
    "TransactionError",
    "ValidationError",
    "__version__",
]
