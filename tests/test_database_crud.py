"""Test database CRUD functionality."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from json_database import Database
from json_database.errors import NotFoundError, TransactionError, ValidationError


def test_crud_and_uuid_ids(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    users = db.collection("users")

    document_id = users.insert({"name": "Princeton", "age": 20})

    assert isinstance(document_id, str)
    assert users.get(document_id) == {"id": document_id, "name": "Princeton", "age": 20}

    updated = users.update(document_id, {"age": 21})
    assert updated["age"] == 21

    all_users = users.all()
    assert all_users == [updated]

    users.delete(document_id)
    with pytest.raises(NotFoundError):
        users.get(document_id)


def test_missing_database_is_created_on_first_write(tmp_path):
    path = tmp_path / "missing.jsondb"
    db = Database(path)

    db.collection("users").insert({"name": "Ava"})

    assert path.exists()


def test_documents_are_returned_as_copies(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    users = db.collection("users")
    document_id = users.insert({"name": "Ava"})

    doc = users.get(document_id)
    doc["name"] = "Mutated"

    assert users.get(document_id)["name"] == "Ava"


def test_rejects_invalid_collection_and_document_shapes(tmp_path):
    db = Database(tmp_path / "app.jsondb")

    with pytest.raises(ValidationError):
        db.collection("../bad")

    with pytest.raises(ValidationError):
        db.collection("users").insert({"__jsondb_type__": "datetime", "value": "x"})

    with pytest.raises(ValidationError):
        db.collection("users").insert({"id": "custom"})


def test_custom_values_persist_in_documents(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    events = db.collection("events")
    timestamp = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)
    document_id = events.insert(
        {
            "when": timestamp,
            "birthday": date(2006, 1, 2),
            "price": Decimal("12.50"),
            "tags": {"python", "db"},
            "raw": b"hello",
        }
    )

    reloaded = Database(tmp_path / "app.jsondb").collection("events").get(document_id)

    assert reloaded["when"] == timestamp
    assert reloaded["birthday"] == date(2006, 1, 2)
    assert reloaded["price"] == Decimal("12.50")
    assert reloaded["tags"] == {"python", "db"}
    assert reloaded["raw"] == b"hello"


def test_insert_rejects_unserializable_value_with_validation_error(tmp_path):
    """The boundary contract: bad values surface as ValidationError at insert
    time, not as SerializationError from the commit path after a UUID has been
    generated and discarded."""
    db = Database(tmp_path / "app.jsondb")

    with pytest.raises(ValidationError, match="unserializable"):
        db.collection("users").insert({"bad": object()})


def test_meta_returns_format_version_and_checksum(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    db.init()

    meta = db.meta()

    assert meta["format"] == "json_database"
    assert meta["version"] == 1
    assert isinstance(meta["content_sha256"], str) and len(meta["content_sha256"]) == 64


def test_dump_inside_transaction_returns_independent_state(tmp_path):
    """`Database.dump()` mid-transaction must return a deep copy — mutating
    the result must not corrupt the transaction's working state."""
    db = Database(tmp_path / "app.jsondb")
    db.collection("users").insert({"name": "Ava"})

    with db.transaction() as tx:
        dumped = db.dump()
        dumped["collections"]["users"].clear()
        # The transaction still sees the original document.
        assert len(tx.collection("users").all()) == 1


def test_transaction_state_property_is_a_snapshot(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    db.collection("users").insert({"name": "Ava"})

    with db.transaction() as tx:
        snapshot = tx.state
        snapshot["collections"]["users"].clear()
        # Mutating the snapshot must not corrupt the transaction.
        assert len(tx.collection("users").all()) == 1


def test_update_returns_a_copy(tmp_path):
    """`update()` must return a deep copy of the merged document, mirroring
    the contract pinned by `test_documents_are_returned_as_copies` for
    `get()`."""
    db = Database(tmp_path / "app.jsondb")
    users = db.collection("users")
    document_id = users.insert({"name": "Ava"})

    updated = users.update(document_id, {"name": "Mia"})
    updated["name"] = "Mutated"

    assert users.get(document_id)["name"] == "Mia"


def test_database_context_manager_succeeds_on_clean_exit(tmp_path):
    path = tmp_path / "app.jsondb"
    with Database(path) as db:
        db.collection("users").insert({"name": "Ava"})
    # Re-open and verify the write persisted.
    assert len(Database(path).collection("users").all()) == 1


def test_database_context_manager_raises_if_transaction_open_on_exit(tmp_path):
    """A user who exits the `with` block without committing or rolling back
    their transaction should see a loud error, not silent data loss."""
    db = Database(tmp_path / "app.jsondb")
    tx = db.transaction()
    tx.__enter__()
    try:
        # The body runs cleanly; the unclosed `tx` is what `db.__exit__`
        # must surface.
        with pytest.raises(TransactionError, match="open transaction"):
            with db:
                tx.collection("users").insert({"name": "Ava"})
    finally:
        # Clean up the leaked tx so the lock releases for later tests.
        # Passing an exc_type makes Transaction skip commit (rollback).
        tx.__exit__(RuntimeError, RuntimeError("test cleanup"), None)


def test_database_context_manager_does_not_mask_body_exception(tmp_path):
    """If the body raises and a transaction is also open, the body's
    exception wins — we do not suppress it with our own."""
    db = Database(tmp_path / "app.jsondb")
    tx = db.transaction()
    tx.__enter__()
    try:
        with pytest.raises(ValueError, match="body"):
            with db:
                raise ValueError("body")
    finally:
        tx.__exit__(RuntimeError, RuntimeError("test cleanup"), None)


def test_collection_name_rejects_unicode(tmp_path):
    """Collection names are deliberately restricted to ASCII identifier
    characters by the regex in `validate_collection_name`. Pin the contract
    so a well-meaning refactor doesn't silently broaden the surface."""
    db = Database(tmp_path / "app.jsondb")

    with pytest.raises(ValidationError, match="letters, numbers, underscore, and dash"):
        db.collection("café")


def test_database_exit_releases_lock_after_unclosed_transaction(tmp_path):
    """After `Database.__exit__` surfaces the unclosed-transaction error,
    the OS file lock must already be released — otherwise the next acquirer
    sits waiting until process exit."""
    path = tmp_path / "app.jsondb"
    db = Database(path)
    tx = db.transaction()
    tx.__enter__()

    with pytest.raises(TransactionError, match="open transaction"):
        with db:
            pass

    # If the lock had leaked, this would block until the (5 s default)
    # timeout fires and then raise LockError. We use a short timeout so the
    # regression is loud.
    db2 = Database(path, timeout=0.5)
    db2.collection("users").insert({"name": "Ava"})
    assert len(db2.collection("users").all()) == 1


def test_two_database_instances_share_disk_view(tmp_path):
    """Two `Database` instances on the same file: writes through one are
    visible to the other after commit. Reads through the second instance
    during the first's transaction see the on-disk snapshot, not the
    in-memory transaction state."""
    path = tmp_path / "app.jsondb"
    db1 = Database(path)
    db2 = Database(path)

    db1.collection("users").insert({"name": "Ava"})
    assert len(db2.collection("users").all()) == 1

    with db1.transaction() as tx:
        tx.collection("users").insert({"name": "Mia"})
        # db1 sees the in-memory tx state (routed in `_read_state`).
        assert len(db1.collection("users").all()) == 2
        # db2 has no knowledge of db1's open transaction; it sees the
        # on-disk snapshot which is still the single committed document.
        assert len(db2.collection("users").all()) == 1

    # After commit, both instances see the new document.
    assert len(db2.collection("users").all()) == 2


def test_missing_collection_list_queries_return_empty(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")

    assert users.all() == []
    assert users.find({"name": "Ava"}) == []
    assert users.where(lambda doc: True) == []


def test_missing_collection_point_lookups_raise(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")

    with pytest.raises(NotFoundError):
        users.get("any-id")

    with pytest.raises(NotFoundError):
        users.update("any-id", {"name": "Ava"})


def test_dump_on_missing_file_does_not_create_file(tmp_path):
    path = tmp_path / "missing.jsondb"
    db = Database(path)

    db.dump()

    assert not path.exists()


def test_empty_document_id_is_rejected(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    document_id = users.insert({"name": "Ava"})

    for action in (
        lambda: users.get(""),
        lambda: users.update("", {"name": "X"}),
        lambda: users.delete(""),
        lambda: users.replace("", {"name": "X"}),
        lambda: users.upsert("", {"name": "X"}),
        lambda: users.bulk_update([(document_id, {"active": True}), ("", {"active": False})]),
    ):
        with pytest.raises(ValidationError, match="non-empty string"):
            action()


def test_collection_name_rejects_empty_and_double_underscore_prefix(tmp_path):
    db = Database(tmp_path / "app.jsondb")

    with pytest.raises(ValidationError, match="cannot be empty"):
        db.collection("")

    with pytest.raises(ValidationError, match="cannot start with __"):
        db.collection("__secret")


def test_nested_reserved_type_key_is_rejected(tmp_path):
    db = Database(tmp_path / "app.jsondb")

    with pytest.raises(ValidationError, match="__jsondb_type__"):
        db.collection("users").insert({"profile": {"__jsondb_type__": "datetime", "value": "x"}})


def test_tuple_round_trips_as_list_through_database(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    document_id = users.insert({"coords": (1, 2)})

    assert users.get(document_id)["coords"] == [1, 2]


def test_replace_returns_a_copy(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    document_id = users.insert({"name": "Ava"})

    replaced = users.replace(document_id, {"name": "Mia"})
    replaced["name"] = "Mutated"

    assert users.get(document_id)["name"] == "Mia"


def test_insert_rejects_frozenset_at_collection_boundary(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")

    with pytest.raises(ValidationError, match="frozenset is not supported"):
        users.insert({"tags": frozenset({"a"})})


def test_get_rejects_non_string_document_id(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava"})

    with pytest.raises(ValidationError, match="non-empty string"):
        users.get(123)


def test_missing_collection_delete_and_replace_raise(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")

    with pytest.raises(NotFoundError, match="collection not found"):
        users.delete("any-id")

    with pytest.raises(NotFoundError, match="collection not found"):
        users.replace("any-id", {"name": "Ava"})


def test_empty_collection_vs_missing_document_messages_differ(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    document_id = users.insert({"name": "Ava"})
    users.delete(document_id)

    assert users.all() == []

    with pytest.raises(NotFoundError, match="document not found"):
        users.get(document_id)
