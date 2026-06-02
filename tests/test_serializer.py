"""Test serializer functionality."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from json_database.errors import SerializationError
from json_database.serializer import JsonSerializer


def test_round_trips_custom_types():
    serializer = JsonSerializer()
    payload = {
        "created": datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc),
        "birthday": date(2006, 1, 2),
        "price": Decimal("19.99"),
        "tags": {"python", "database"},
        "raw": b"hello",
    }

    decoded = serializer.loads(serializer.dumps(payload))

    assert decoded == payload


def test_rejects_unknown_types():
    serializer = JsonSerializer()

    with pytest.raises(SerializationError):
        serializer.dumps({"bad": object()})


def test_unknown_type_tag_raises():
    serializer = JsonSerializer()

    with pytest.raises(SerializationError):
        serializer.loads('{"__jsondb_type__": "mystery", "value": "x"}')


def test_canonical_output_is_stable_for_sets():
    serializer = JsonSerializer()
    left = serializer.canonical_dumps({"letters": {"b", "a", "c"}})
    right = serializer.canonical_dumps({"letters": {"c", "b", "a"}})

    assert left == right


def test_rejects_non_finite_floats():
    serializer = JsonSerializer()

    with pytest.raises(SerializationError, match="non-finite"):
        serializer.dumps({"x": float("nan")})

    with pytest.raises(SerializationError, match="non-finite"):
        serializer.dumps({"x": float("inf")})


def test_rejects_non_finite_decimal():
    serializer = JsonSerializer()

    with pytest.raises(SerializationError, match="non-finite"):
        serializer.dumps({"x": Decimal("NaN")})


def test_tuple_in_set_round_trips_as_tuple():
    serializer = JsonSerializer()
    payload = {"coords": {(1, 2), (3, 4)}}
    decoded = serializer.loads(serializer.dumps(payload))
    assert decoded == payload


def test_decoding_set_with_unhashable_member_raises():
    """A hand-edited file claiming a set contains a dict should not silently
    succeed — the encoder cannot have produced this, so reject it on read."""
    serializer = JsonSerializer()
    forged = (
        '{"__jsondb_type__": "set", '
        '"value": [{"__jsondb_type__": "datetime", "value": "x"}]}'
    )
    with pytest.raises(SerializationError):
        serializer.loads(forged)


def test_frozenset_rejected_with_specific_message():
    serializer = JsonSerializer()
    with pytest.raises(SerializationError, match="frozenset is not supported"):
        serializer.dumps({"x": frozenset({"a", "b"})})


def test_validate_dry_runs_without_output():
    serializer = JsonSerializer()
    serializer.validate({"x": 1})  # no exception
    with pytest.raises(SerializationError):
        serializer.validate({"x": object()})
