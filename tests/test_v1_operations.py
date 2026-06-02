"""Test V1 operations functionality."""

import pytest

from json_database import Database
from json_database.errors import NotFoundError, ValidationError


def test_replace_upsert_and_collections(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    users = db.collection("users")
    document_id = users.insert({"name": "Ava", "age": 20})

    replaced = users.replace(document_id, {"name": "Mia"})
    assert replaced == {"id": document_id, "name": "Mia"}

    users.upsert("custom-id", {"name": "Noah"})
    assert users.get("custom-id") == {"id": "custom-id", "name": "Noah"}
    assert db.collections() == ["users"]


def test_replace_on_missing_document_raises(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava"})

    with pytest.raises(NotFoundError):
        users.replace("does-not-exist", {"name": "x"})


def test_replace_rejects_conflicting_id(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    document_id = users.insert({"name": "Ava"})

    with pytest.raises(ValidationError, match="cannot change document id"):
        users.replace(document_id, {"id": "other-id", "name": "Mia"})


@pytest.mark.parametrize(
    "document",
    [{"id": None, "name": "Mia"}, {"id": "", "name": "Mia"}],
    ids=["null-id", "empty-string-id"],
)
def test_replace_rejects_invalid_id_field(tmp_path, document):
    users = Database(tmp_path / "app.jsondb").collection("users")
    document_id = users.insert({"name": "Ava"})

    with pytest.raises(ValidationError, match="cannot change document id"):
        users.replace(document_id, document)


def test_upsert_overwrites_existing_id(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.upsert("fixed-id", {"name": "Ava", "age": 20})
    users.upsert("fixed-id", {"name": "Mia"})

    assert users.get("fixed-id") == {"id": "fixed-id", "name": "Mia"}


def test_upsert_creates_new_collection(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    db.collection("logs").upsert("entry-1", {"event": "boot"})

    assert db.collections() == ["logs"]
    assert db.collection("logs").get("entry-1")["event"] == "boot"


def test_bulk_insert_rejects_non_list(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")

    with pytest.raises(ValidationError, match="expects a list"):
        users.bulk_insert({"name": "Ava"})


def test_bulk_update_rejects_non_list(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")

    with pytest.raises(ValidationError, match="expects a list"):
        users.bulk_update(("id", {"name": "Ava"}))


@pytest.mark.parametrize(
    "updates",
    [
        [{"name": "Ava"}],
        [("only-id",)],
        ["not-a-pair"],
        [("id-1", {"name": "Ava"}, "extra")],
        [("id-1", {"name": "Ava"}, {"name": "Mia"})],
        [{"document_id": "id-1", "updates": {"name": "Ava"}}],
    ],
    ids=[
        "dict-entry",
        "single-item-tuple",
        "string-entry",
        "three-item-tuple",
        "two-updates-one-entry",
        "dict-shaped-entry",
    ],
)
def test_bulk_update_rejects_malformed_entries(tmp_path, updates):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Original"})

    with pytest.raises(ValidationError, match="expects \\(document_id, updates\\) pairs"):
        users.bulk_update(updates)


def test_non_finite_values_rejected_on_insert_and_upsert(tmp_path):
    from math import nan

    users = Database(tmp_path / "app.jsondb").collection("users")

    with pytest.raises(ValidationError):
        users.insert({"score": nan})

    with pytest.raises(ValidationError):
        users.upsert("fixed-id", {"score": nan})


def test_bulk_update_is_all_or_nothing(tmp_path):
    """If any update in a bulk_update is invalid (missing doc or bad value),
    none of the updates apply."""
    users = Database(tmp_path / "app.jsondb").collection("users")
    ids = users.bulk_insert([{"name": "Ava"}, {"name": "Mia"}])

    with pytest.raises(NotFoundError):
        users.bulk_update(
            [
                (ids[0], {"active": True}),
                ("missing-id", {"active": False}),
            ]
        )

    # Neither change committed.
    assert "active" not in users.get(ids[0])
    assert "active" not in users.get(ids[1])

    with pytest.raises(ValidationError, match="cannot change document id"):
        users.bulk_update([(ids[0], {"id": "other-id", "active": True})])

    assert "active" not in users.get(ids[0])


def test_update_rejects_id_in_updates(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    document_id = users.insert({"name": "Ava"})

    with pytest.raises(ValidationError, match="cannot change document id"):
        users.update(document_id, {"id": "other-id"})


def test_update_is_shallow_merge(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    document_id = users.insert({"profile": {"city": "NYC", "zip": "10001"}})

    users.update(document_id, {"profile": {"city": "LA"}})

    assert users.get(document_id)["profile"] == {"city": "LA"}


def test_replace_accepts_matching_id(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    document_id = users.insert({"name": "Ava"})

    replaced = users.replace(document_id, {"id": document_id, "name": "Mia"})
    assert replaced == {"id": document_id, "name": "Mia"}


def test_upsert_rejects_conflicting_id(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")

    with pytest.raises(ValidationError, match="cannot change document id"):
        users.upsert("fixed-id", {"id": "other-id", "name": "Ava"})


@pytest.mark.parametrize(
    "document",
    [{"id": None, "name": "Ava"}, {"id": "", "name": "Ava"}],
    ids=["null-id", "empty-string-id"],
)
def test_upsert_rejects_invalid_id_field(tmp_path, document):
    users = Database(tmp_path / "app.jsondb").collection("users")

    with pytest.raises(ValidationError, match="cannot change document id"):
        users.upsert("fixed-id", document)


def test_bulk_insert_rejects_user_supplied_id(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")

    with pytest.raises(ValidationError, match="rejects user-supplied id"):
        users.bulk_insert([{"id": "custom", "name": "Ava"}])


def test_non_finite_values_rejected_on_update_and_replace(tmp_path):
    from math import nan

    users = Database(tmp_path / "app.jsondb").collection("users")
    document_id = users.insert({"score": 1.0})

    with pytest.raises(ValidationError):
        users.update(document_id, {"score": nan})

    with pytest.raises(ValidationError):
        users.replace(document_id, {"score": nan})


def test_bulk_operations_commit_once(tmp_path, monkeypatch):
    db = Database(tmp_path / "app.jsondb")
    commit_count = 0
    original_commit = db._engine._commit_unlocked

    def counting_commit(state):
        nonlocal commit_count
        commit_count += 1
        return original_commit(state)

    monkeypatch.setattr(db._engine, "_commit_unlocked", counting_commit)
    users = db.collection("users")

    ids = users.bulk_insert([{"name": "Ava"}, {"name": "Mia"}])
    users.bulk_update([(ids[0], {"active": True}), (ids[1], {"active": False})])

    assert commit_count == 2
    assert users.get(ids[0])["active"] is True
    assert users.get(ids[1])["active"] is False
