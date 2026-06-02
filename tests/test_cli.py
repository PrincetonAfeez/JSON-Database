"""Test CLI functionality."""

import json
import subprocess
import sys

import pytest


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "json_database", *args],
        text=True,
        capture_output=True,
    )


def test_cli_crud_query_collections_and_check(tmp_path):
    path = tmp_path / "app.jsondb"

    result = run_cli("--db", str(path), "init")
    assert result.returncode == 0, result.stderr

    result = run_cli("--db", str(path), "insert", "users", '{"name": "Ava", "age": 31}')
    assert result.returncode == 0, result.stderr
    document_id = result.stdout.strip()

    result = run_cli("--db", str(path), "get", "users", document_id)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["name"] == "Ava"

    result = run_cli("--db", str(path), "update", "users", document_id, '{"active": true}')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["active"] is True

    result = run_cli("--db", str(path), "query", "users", '{"age": {"$gt": 18}}')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0]["id"] == document_id

    result = run_cli("--db", str(path), "collections")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "users"

    result = run_cli("--db", str(path), "check")
    assert result.returncode == 0, result.stderr

    result = run_cli("--db", str(path), "delete", "users", document_id)
    assert result.returncode == 0, result.stderr

    result = run_cli("--db", str(path), "get", "users", document_id)
    assert result.returncode == 1


def test_cli_exit_codes(tmp_path):
    path = tmp_path / "app.jsondb"
    run_cli("--db", str(path), "init")

    result = run_cli("--db", str(path), "get", "users", "missing")
    assert result.returncode == 1

    result = run_cli("--db", str(path), "insert", "users", "{bad-json")
    assert result.returncode == 2

    result = run_cli("--db", str(path), "insert", "users", '{"id": "custom"}')
    assert result.returncode == 2

    result = run_cli("--db", str(path), "get", "missing-collection", "x")
    assert result.returncode == 1

    result = run_cli("--db", str(path), "query", "users", '{"age": {"$near": 20}}')
    assert result.returncode == 2

    result = run_cli("--db", str(path), "--timeout", "0", "get", "users", "x")
    assert result.returncode == 2
    assert "positive finite" in result.stderr.lower()

    result = run_cli("--db", str(path), "--timeout", "nan", "get", "users", "x")
    assert result.returncode == 2


def test_cli_init_without_force_on_existing_db_returns_exit_5(tmp_path):
    path = tmp_path / "app.jsondb"
    run_cli("--db", str(path), "init")

    result = run_cli("--db", str(path), "init")
    assert result.returncode == 5


def test_cli_insert_without_init_creates_database_file(tmp_path):
    path = tmp_path / "missing.jsondb"

    result = run_cli("--db", str(path), "insert", "users", '{"name": "Ava"}')
    assert result.returncode == 0, result.stderr
    assert path.exists()


def test_cli_insert_on_corrupt_database_returns_exit_4(tmp_path):
    path = tmp_path / "app.jsondb"
    run_cli("--db", str(path), "init")
    document_id = run_cli(
        "--db", str(path), "insert", "users", '{"name": "Ava"}'
    ).stdout.strip()

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["collections"]["users"][document_id]["name"] = "tampered"
    path.write_text(json.dumps(raw), encoding="utf-8")

    result = run_cli("--db", str(path), "insert", "users", '{"name": "New"}')
    assert result.returncode == 4


def test_cli_init_force_overwrites_existing_database(tmp_path):
    path = tmp_path / "app.jsondb"
    run_cli("--db", str(path), "init")
    run_cli("--db", str(path), "insert", "users", '{"name": "Ava"}')

    result = run_cli("--db", str(path), "init", "--force")
    assert result.returncode == 0, result.stderr

    result = run_cli("--db", str(path), "collections")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_cli_storage_failure_exit_code(tmp_path, monkeypatch):
    from json_database import storage as storage_module
    from json_database.cli import main

    path = tmp_path / "app.jsondb"
    main(["--db", str(path), "init"])

    def boom(_target, _data):
        raise storage_module.StorageError("disk full")

    monkeypatch.setattr(storage_module, "atomic_write", boom)
    assert (
        main(["--db", str(path), "insert", "users", '{"name": "Ava"}']) == 5
    )


def test_cli_check_json_storage_status(tmp_path, monkeypatch):
    from pathlib import Path

    from json_database.cli import main

    storage_path = tmp_path / "storage.jsondb"
    main(["--db", str(storage_path), "init"])

    def deny(self):
        raise OSError("permission denied (simulated)")

    monkeypatch.setattr(Path, "read_bytes", deny)
    assert main(["--db", str(storage_path), "check", "--json"]) == 4


def test_cli_check_json_missing_format_and_storage(tmp_path):
    missing_path = tmp_path / "never-existed.jsondb"
    result = run_cli("--db", str(missing_path), "check", "--json")
    assert result.returncode == 4
    payload = json.loads(result.stdout)
    assert payload["status"] == "missing"
    assert payload["expected"] is None and payload["actual"] is None

    format_path = tmp_path / "bad-format.jsondb"
    format_path.write_text("{not-json", encoding="utf-8")
    result = run_cli("--db", str(format_path), "check", "--json")
    assert result.returncode == 4
    payload = json.loads(result.stdout)
    assert payload["status"] == "format"


def test_cli_replace_dump_and_pretty(tmp_path):
    path = tmp_path / "app.jsondb"
    run_cli("--db", str(path), "init")
    document_id = run_cli(
        "--db", str(path), "insert", "users", '{"name": "Ava"}'
    ).stdout.strip()

    result = run_cli(
        "--db", str(path), "replace", "users", document_id, '{"name": "Mia"}'
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["name"] == "Mia"

    result = run_cli("--db", str(path), "dump", "users")
    assert result.returncode == 0, result.stderr
    docs = json.loads(result.stdout)
    assert [d["name"] for d in docs] == ["Mia"]

    result = run_cli("--db", str(path), "--pretty", "dump", "users")
    assert result.returncode == 0, result.stderr
    assert "\n" in result.stdout  # indent=2 splits objects across lines


def test_cli_query_empty_result_is_success(tmp_path):
    path = tmp_path / "app.jsondb"
    run_cli("--db", str(path), "init")

    result = run_cli("--db", str(path), "query", "users", '{"missing": true}')
    # Empty collection or no match should be exit 0 with [] output.
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_cli_integrity_failure_exit_code(tmp_path):
    path = tmp_path / "app.jsondb"
    run_cli("--db", str(path), "init")
    document_id = run_cli(
        "--db", str(path), "insert", "users", '{"name": "Ava"}'
    ).stdout.strip()

    # Tamper with the file outside the library.
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["collections"]["users"][document_id]["name"] = "tampered"
    path.write_text(json.dumps(raw), encoding="utf-8")

    result = run_cli("--db", str(path), "check")
    assert result.returncode == 4
    assert "checksum" in result.stderr.lower() or "integrity" in result.stderr.lower()


def test_cli_lock_timeout_exit_code(tmp_path):
    from json_database.lock import FileLock

    path = tmp_path / "app.jsondb"
    run_cli("--db", str(path), "init")
    lock_path = path.with_name(path.name + ".lock")

    with FileLock(lock_path, timeout=1):
        result = run_cli(
            "--db",
            str(path),
            "--timeout",
            "0.1",
            "insert",
            "users",
            '{"name": "Ava"}',
        )

    assert result.returncode == 3
    assert "waited" in result.stderr.lower()


def test_cli_missing_database_check_reports_missing(tmp_path):
    path = tmp_path / "never-existed.jsondb"

    result = run_cli("--db", str(path), "check")
    assert result.returncode == 4
    assert "does not exist" in result.stderr.lower()


def test_cli_version_flag():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "json_database", "--version"],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0
    assert "jsondb" in result.stdout.lower()
    assert "0.1.1" in result.stdout


def test_jsondb_console_script_runs_version():
    import os
    import shutil
    import sys
    import sysconfig
    from pathlib import Path

    jsondb = shutil.which("jsondb")
    if jsondb is None:
        scripts = Path(sysconfig.get_path("scripts"))
        candidate = scripts / ("jsondb.exe" if os.name == "nt" else "jsondb")
        if candidate.exists():
            jsondb = str(candidate)
    if jsondb is None:
        pytest.skip("jsondb console script not installed on PATH")

    result = subprocess.run([jsondb, "--version"], text=True, capture_output=True)
    assert result.returncode == 0
    assert "0.1.1" in result.stdout


def test_cli_check_json_output_ok(tmp_path):
    path = tmp_path / "app.jsondb"
    run_cli("--db", str(path), "init")

    result = run_cli("--db", str(path), "check", "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["path"].endswith("app.jsondb")


def test_print_json_text_fallback(monkeypatch):
    """When `sys.stdout` has no `.buffer` attribute (e.g., a captured-text
    stream), `_print_json` falls through to the text-write path."""
    import io
    import sys

    from json_database.cli import _print_json
    from json_database.serializer import JsonSerializer

    fake = io.StringIO()  # StringIO has no `.buffer`
    monkeypatch.setattr(sys, "stdout", fake)
    _print_json(JsonSerializer(pretty=False), {"x": 1})

    output = fake.getvalue()
    assert json.loads(output) == {"x": 1}


def test_cli_check_json_output_corrupt(tmp_path):
    path = tmp_path / "app.jsondb"
    run_cli("--db", str(path), "init")
    doc_id = run_cli(
        "--db", str(path), "insert", "users", '{"name": "Ava"}'
    ).stdout.strip()

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["collections"]["users"][doc_id]["name"] = "tampered"
    path.write_text(json.dumps(raw), encoding="utf-8")

    result = run_cli("--db", str(path), "check", "--json")
    assert result.returncode == 4
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "corrupt"
    assert payload["expected"] != payload["actual"]
