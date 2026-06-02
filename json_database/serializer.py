"""Deterministic JSON serialization with explicit custom type tags.

The serializer round-trips Python `datetime`, `date`, `Decimal`, `set`, and
`bytes` values through a tagged dictionary envelope. Tuples are encoded as
JSON arrays and decode back to lists (one-way) — this is the only intentional
lossy conversion. Non-finite floats (NaN, Infinity) are rejected so that the
on-disk JSON is strict-spec and the checksum is reproducible.
"""

from __future__ import annotations

import base64
import json
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .errors import SerializationError


TYPE_KEY = "__jsondb_type__"


class JsonSerializer:
    """Serialize Python data to JSON bytes and back."""

    def __init__(self, *, pretty: bool = True):
        self.pretty = pretty

    def dumps(self, data: Any) -> bytes:
        return self._dumps(data, pretty=self.pretty)

    def canonical_dumps(self, data: Any) -> bytes:
        return self._dumps(data, pretty=False)

    def loads(self, raw: bytes | str) -> Any:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SerializationError(f"invalid JSON: {exc}") from exc
        return self._decode(parsed)

    def validate(self, value: Any) -> None:
        """Dry-run encode `value` to surface unsupported types as
        `SerializationError` without producing output. This is the public
        contract callers should use for boundary validation."""
        self._encode(value)

    def _dumps(self, data: Any, *, pretty: bool) -> bytes:
        try:
            encoded = self._encode(data)
            text = json.dumps(
                encoded,
                ensure_ascii=False,
                sort_keys=True,
                indent=2 if pretty else None,
                separators=None if pretty else (",", ":"),
                allow_nan=False,
            )
            return (text + "\n").encode("utf-8")
        except SerializationError:
            raise
        except (TypeError, ValueError) as exc:
            raise SerializationError(f"cannot serialize value: {exc}") from exc

    def _encode(self, value: Any) -> Any:
        # bool must be checked before int because bool is a subclass of int.
        if value is None or isinstance(value, (bool, str)):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                raise SerializationError("cannot serialize non-finite float")
            return value
        if isinstance(value, datetime):
            return {TYPE_KEY: "datetime", "value": value.isoformat()}
        if isinstance(value, date):
            return {TYPE_KEY: "date", "value": value.isoformat()}
        if isinstance(value, Decimal):
            if value.is_nan() or value.is_infinite():
                raise SerializationError("cannot serialize non-finite Decimal")
            return {TYPE_KEY: "decimal", "value": str(value)}
        if isinstance(value, bytes):
            encoded = base64.b64encode(value).decode("ascii")
            return {TYPE_KEY: "bytes", "value": encoded}
        if isinstance(value, frozenset):
            raise SerializationError(
                "frozenset is not supported; convert to set or list before storing"
            )
        if isinstance(value, set):
            encoded_items = [self._encode(item) for item in value]
            encoded_items.sort(
                key=lambda item: json.dumps(
                    item, sort_keys=True, separators=(",", ":"), allow_nan=False
                )
            )
            return {TYPE_KEY: "set", "value": encoded_items}
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise SerializationError(f"JSON object keys must be strings, got {type(key).__name__}")
                result[key] = self._encode(item)
            return result
        if isinstance(value, (list, tuple)):
            return [self._encode(item) for item in value]
        raise SerializationError(f"cannot serialize value of type {type(value).__name__}")

    def _decode(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._decode(item) for item in value]
        if not isinstance(value, dict):
            return value
        if TYPE_KEY in value:
            return self._decode_tagged(value)
        return {key: self._decode(item) for key, item in value.items()}

    def _decode_tagged(self, value: dict[str, Any]) -> Any:
        tag = value.get(TYPE_KEY)
        raw = value.get("value")
        if not isinstance(tag, str):
            raise SerializationError(f"invalid {TYPE_KEY} tag")
        if tag == "datetime":
            if not isinstance(raw, str):
                raise SerializationError("datetime value must be a string")
            try:
                return datetime.fromisoformat(raw)
            except ValueError as exc:
                raise SerializationError(f"invalid datetime value: {raw}") from exc
        if tag == "date":
            if not isinstance(raw, str):
                raise SerializationError("date value must be a string")
            try:
                return date.fromisoformat(raw)
            except ValueError as exc:
                raise SerializationError(f"invalid date value: {raw}") from exc
        if tag == "decimal":
            if not isinstance(raw, str):
                raise SerializationError("decimal value must be a string")
            try:
                return Decimal(raw)
            except Exception as exc:
                raise SerializationError(f"invalid decimal value: {raw}") from exc
        if tag == "bytes":
            if not isinstance(raw, str):
                raise SerializationError("bytes value must be a string")
            try:
                return base64.b64decode(raw.encode("ascii"), validate=True)
            except Exception as exc:
                raise SerializationError("invalid base64 bytes value") from exc
        if tag == "set":
            if not isinstance(raw, list):
                raise SerializationError("set value must be a list")
            items = []
            for item in raw:
                decoded = self._decode(item)
                items.append(_coerce_set_member(decoded))
            return set(items)
        raise SerializationError(f"unknown {TYPE_KEY}: {tag}")


def _coerce_set_member(value: Any) -> Any:
    """Coerce a decoded value into something a Python `set` can hold.

    Lists are turned into tuples so that tuple values round-trip through the
    JSON array form. Anything else that is already unhashable (dict, set) is a
    sign of a hand-edited or corrupt encoding — surface it loudly.
    """
    if isinstance(value, list):
        return tuple(_coerce_set_member(item) for item in value)
    try:
        hash(value)
    except TypeError as exc:
        raise SerializationError(
            f"set cannot contain unhashable item of type {type(value).__name__}"
        ) from exc
    return value
