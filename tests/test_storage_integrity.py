"""Test storage integrity functionality."""

import json

import pytest

from json_database import Database
from json_database.errors import DatabaseFormatError, IntegrityError, StorageError


def test_init_creates_checksum_inside_database_file(tmp_path):
    path = tmp_path / "app.jsondb"
    db = Database(path)

    db.init()

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw["meta"]["content_sha256"], str)
    assert db.check_integrity().ok


def test_init_fails_if_file_exists_without_force(tmp_path):
    path = tmp_path / "app.jsondb"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(StorageError):
        Database(path).init()


def test_corrupting_content_raises_integrity_error(tmp_path):
    path = tmp_path / "app.jsondb"
    users = Database(path).collection("users")
    document_id = users.insert({"name": "Ava"})

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["collections"]["users"][document_id]["name"] = "Mia"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(IntegrityError):
        Database(path).dump()

    assert not Database(path).check_integrity().ok


def test_invalid_json_raises_database_format_error(tmp_path):
    path = tmp_path / "app.jsondb"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(DatabaseFormatError):
        Database(path).dump()


def test_empty_file_is_not_silently_accepted(tmp_path):
    path = tmp_path / "app.jsondb"
    path.write_text("", encoding="utf-8")

    with pytest.raises(DatabaseFormatError):
        Database(path).dump()


def test_integrity_report_distinguishes_missing_from_corrupt(tmp_path):
    missing = Database(tmp_path / "nope.jsondb").check_integrity()
    assert missing.status == "missing"
    assert missing.ok is False

    path = tmp_path / "app.jsondb"
    db = Database(path)
    document_id = db.collection("users").insert({"name": "Ava"})

    ok = db.check_integrity()
    assert ok.status == "ok"
    assert ok.ok is True
    # No comparison values are populated on success — keeps the report honest.
    assert ok.expected is None and ok.actual is None

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["collections"]["users"][document_id]["name"] = "Mia"
    path.write_text(json.dumps(raw), encoding="utf-8")

    corrupt = Database(path).check_integrity()
    assert corrupt.status == "corrupt"
    assert corrupt.ok is False
    assert corrupt.expected and corrupt.actual and corrupt.expected != corrupt.actual


def test_integrity_report_format_status_for_unparseable_file(tmp_path):
    path = tmp_path / "app.jsondb"
    path.write_text("{not-json", encoding="utf-8")

    report = Database(path).check_integrity()
    assert report.status == "format"
    assert report.ok is False


def test_make_empty_state_shape():
    """A direct unit test of the empty-state factory, separate from the
    `Database.init()` path."""
    from json_database.storage import FORMAT, VERSION, make_empty_state

    state = make_empty_state()

    assert state["meta"]["format"] == FORMAT
    assert state["meta"]["version"] == VERSION
    assert state["collections"] == {}
    sha = state["meta"]["content_sha256"]
    assert isinstance(sha, str) and len(sha) == 64
    # Empty-state creation is a single call; both timestamps must agree.
    assert state["meta"]["created_at"] == state["meta"]["updated_at"]


def test_integrity_report_storage_status_when_read_denied(tmp_path, monkeypatch):
    """An `OSError` on `read_bytes` (e.g., permission denied) is reported as
    `status='storage'`, not `'format'` or `'corrupt'`."""
    from pathlib import Path

    path = tmp_path / "app.jsondb"
    Database(path).init()

    def deny(self):
        raise OSError("permission denied (simulated)")

    monkeypatch.setattr(Path, "read_bytes", deny)
    report = Database(path).check_integrity()
    assert report.status == "storage"
    assert report.ok is False
    assert "could not read" in report.message.lower()


def test_integrity_report_format_status_for_missing_checksum(tmp_path):
    path = tmp_path / "app.jsondb"
    Database(path).init()

    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["meta"]["content_sha256"]
    path.write_text(json.dumps(raw), encoding="utf-8")

    report = Database(path).check_integrity()
    assert report.status == "format"
    assert report.ok is False


def test_integrity_report_format_status_for_wrong_version(tmp_path):
    path = tmp_path / "app.jsondb"
    Database(path).init()

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["meta"]["version"] = 99
    path.write_text(json.dumps(raw), encoding="utf-8")

    report = Database(path).check_integrity()
    assert report.status == "format"
    assert report.ok is False


def test_integrity_report_format_status_for_document_id_mismatch(tmp_path):
    path = tmp_path / "app.jsondb"
    document_id = Database(path).collection("users").insert({"name": "Ava"})

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["collections"]["users"][document_id]["id"] = "wrong-id"
    path.write_text(json.dumps(raw), encoding="utf-8")

    report = Database(path).check_integrity()
    assert report.status == "format"
    assert report.ok is False


def test_load_rejects_reserved_type_key_as_document_field(tmp_path):
    path = tmp_path / "app.jsondb"
    document_id = Database(path).collection("users").insert({"name": "Ava"})

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["collections"]["users"][document_id]["__jsondb_type__"] = "attack"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DatabaseFormatError, match="__jsondb_type__"):
        Database(path).dump()


def test_load_rejects_nested_reserved_type_key_with_extra_fields(tmp_path):
    path = tmp_path / "app.jsondb"
    document_id = Database(path).collection("users").insert({"name": "Ava"})

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["collections"]["users"][document_id]["note"] = {
        "__jsondb_type__": "datetime",
        "value": "2020-01-01T00:00:00+00:00",
        "extra": "tampered",
    }
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DatabaseFormatError, match="__jsondb_type__"):
        Database(path).dump()


def test_load_rejects_invalid_collection_name_on_disk(tmp_path):
    path = tmp_path / "app.jsondb"
    Database(path).init()

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["collections"]["__secret"] = {}
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DatabaseFormatError, match="invalid collection name"):
        Database(path).dump()


def test_integrity_report_format_status_for_empty_file(tmp_path):
    path = tmp_path / "app.jsondb"
    path.write_text("", encoding="utf-8")

    report = Database(path).check_integrity()
    assert report.status == "format"
    assert report.ok is False


def test_load_rejects_empty_document_id_key_on_disk(tmp_path):
    path = tmp_path / "app.jsondb"
    Database(path).init()

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["collections"]["users"] = {"": {"id": ""}}
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DatabaseFormatError, match="document id cannot be empty"):
        Database(path).dump()

    report = Database(path).check_integrity()
    assert report.status == "format"
    assert report.ok is False
