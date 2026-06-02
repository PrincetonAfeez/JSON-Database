"""Test transactions functionality."""

import pytest

from json_database import Database
from json_database.errors import NotFoundError, StorageError, TransactionError, ValidationError


def test_transaction_commits_all_changes(tmp_path):
    db = Database(tmp_path / "app.jsondb")

    with db.transaction() as tx:
        user_id = tx.collection("users").insert({"name": "Ava"})
        tx.collection("logs").insert({"event": "created_user", "user_id": user_id})

    assert db.collection("users").get(user_id)["name"] == "Ava"
    assert db.collection("logs").find({"user_id": user_id})


def test_transaction_rolls_back_on_exception(tmp_path):
    db = Database(tmp_path / "app.jsondb")

    with pytest.raises(RuntimeError):
        with db.transaction() as tx:
            user_id = tx.collection("users").insert({"name": "Ava"})
            raise RuntimeError("boom")

    with pytest.raises(NotFoundError):
        db.collection("users").get(user_id)


def test_nested_transactions_raise(tmp_path):
    db = Database(tmp_path / "app.jsondb")

    with db.transaction():
        with pytest.raises(TransactionError):
            with db.transaction():
                pass


def test_autocommit_write_during_transaction_raises(tmp_path):
    db = Database(tmp_path / "app.jsondb")

    with db.transaction():
        with pytest.raises(TransactionError):
            db.collection("users").insert({"name": "outside"})


def test_db_reads_during_transaction_see_in_memory_state(tmp_path):
    """Reads through the same `Database` instance during a transaction see the
    transaction's in-memory view, not the on-disk snapshot — otherwise a user
    could read stale data from `db` while writing through `tx`."""
    db = Database(tmp_path / "app.jsondb")
    db.collection("users").insert({"name": "original"})

    with db.transaction() as tx:
        new_id = tx.collection("users").insert({"name": "added"})
        assert len(db.collection("users").all()) == 2
        assert db.collection("users").get(new_id)["name"] == "added"


def test_db_collections_and_dump_during_transaction_see_in_memory_state(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    db.collection("users").insert({"name": "Ava"})

    with db.transaction() as tx:
        tx.collection("logs").insert({"event": "x"})
        assert db.collections() == ["logs", "users"]
        dumped = db.dump()
        assert "logs" in dumped["collections"]


def test_commit_failure_leaves_file_unchanged(tmp_path, monkeypatch):
    """If `atomic_write` itself raises during the transaction's final commit,
    the on-disk file must be untouched and the database must remain usable."""
    from json_database import storage as storage_module
    from json_database.errors import StorageError

    path = tmp_path / "app.jsondb"
    db = Database(path)
    original_id = db.collection("users").insert({"name": "original"})
    pre_bytes = path.read_bytes()

    def boom(_target, _data):
        raise StorageError("disk full")

    monkeypatch.setattr(storage_module, "atomic_write", boom)
    with pytest.raises(StorageError):
        with db.transaction() as tx:
            tx.collection("users").insert({"name": "should-rollback"})

    monkeypatch.undo()
    assert path.read_bytes() == pre_bytes
    reopened = Database(path)
    assert reopened.collection("users").get(original_id)["name"] == "original"
    assert reopened.check_integrity().ok


def test_db_reads_after_rollback_see_pre_transaction_state(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    db.collection("users").insert({"name": "original"})

    with pytest.raises(RuntimeError):
        with db.transaction() as tx:
            tx.collection("users").insert({"name": "added"})
            raise RuntimeError("boom")

    names = [doc["name"] for doc in db.collection("users").all()]
    assert names == ["original"]


def test_transaction_delete_and_replace_commit(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    document_id = db.collection("users").insert({"name": "Ava", "active": True})

    with db.transaction() as tx:
        tx.collection("users").delete(document_id)
        tx.collection("users").insert({"name": "Mia"})

    names = [doc["name"] for doc in db.collection("users").all()]
    assert names == ["Mia"]


def test_autocommit_update_during_transaction_raises(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    document_id = db.collection("users").insert({"name": "Ava"})

    with db.transaction():
        with pytest.raises(TransactionError):
            db.collection("users").update(document_id, {"name": "outside"})


def test_transaction_validation_failure_rolls_back(tmp_path):
    db = Database(tmp_path / "app.jsondb")

    with pytest.raises(ValidationError):
        with db.transaction() as tx:
            tx.collection("users").insert({"name": "Ava"})
            tx.collection("users").insert({"id": "forbidden"})

    assert db.collection("users").all() == []


def test_meta_find_and_where_during_transaction_see_in_memory_state(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    db.collection("users").insert({"name": "Ava", "active": True})

    with db.transaction() as tx:
        tx.collection("users").insert({"name": "Mia", "active": False})
        assert len(db.collection("users").find({"active": False})) == 1
        assert len(db.collection("users").where(lambda doc: doc["name"] == "Mia")) == 1
        assert "users" in db.collections()
        assert db.meta()["format"] == "json_database"


def test_check_integrity_during_transaction_reads_disk_not_memory(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    db.collection("users").insert({"name": "committed"})

    with db.transaction() as tx:
        tx.collection("users").insert({"name": "uncommitted"})
        report = db.check_integrity()
        assert report.ok is True
        assert len(db.collection("users").all()) == 2


def test_meta_checksum_stays_committed_until_transaction_commits(tmp_path):
    db = Database(tmp_path / "app.jsondb")
    db.collection("users").insert({"name": "Ava"})
    committed = db.meta()
    committed_checksum = committed["content_sha256"]
    committed_updated_at = committed["updated_at"]

    with db.transaction() as tx:
        tx.collection("users").insert({"name": "Mia"})
        meta = db.meta()
        assert meta["content_sha256"] == committed_checksum
        assert meta["updated_at"] == committed_updated_at

    assert db.meta()["content_sha256"] != committed_checksum
    assert db.meta()["updated_at"] != committed_updated_at


def test_database_rejects_non_positive_and_non_finite_timeout(tmp_path):
    with pytest.raises(ValidationError, match="positive finite"):
        Database(tmp_path / "app.jsondb", timeout=0)

    with pytest.raises(ValidationError, match="positive finite"):
        Database(tmp_path / "app.jsondb", timeout=float("nan"))

    with pytest.raises(ValidationError, match="positive finite"):
        Database(tmp_path / "app.jsondb", timeout=float("inf"))
