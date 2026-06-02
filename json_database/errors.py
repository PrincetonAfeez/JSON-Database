"""Custom exceptions for json_database."""


class JsonDBError(Exception):
    """Base class for all expected json_database errors."""


class SerializationError(JsonDBError):
    """Raised when JSON serialization or decoding fails."""


class LockError(JsonDBError):
    """Raised when a database lock cannot be acquired."""


class IntegrityError(JsonDBError):
    """Raised when the stored checksum does not match the database content."""

    def __init__(self, message: str, *, expected: str | None = None, actual: str | None = None):
        super().__init__(message)
        self.expected = expected
        self.actual = actual


class NotFoundError(JsonDBError):
    """Raised when a collection or document does not exist."""


class TransactionError(JsonDBError):
    """Raised when transaction state is invalid."""


class QueryError(JsonDBError):
    """Raised when a query is invalid or fails."""


class ValidationError(JsonDBError):
    """Raised when user input violates database rules."""


class StorageError(JsonDBError):
    """Raised when storage cannot complete an operation."""


class DatabaseFormatError(JsonDBError):
    """Raised when a database file cannot be parsed or has an invalid shape."""
