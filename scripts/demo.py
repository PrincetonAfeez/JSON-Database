#!/usr/bin/env python3
"""Durability and integrity demo for portfolio / evaluation.

Run from the repository root:

    python scripts/demo.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_jsondb(db: Path, *args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "json_database", "--db", str(db), *args],
        text=True,
        capture_output=True,
    )
    if result.returncode != expect:
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(
            f"expected exit {expect}, got {result.returncode} for: json_database {' '.join(args)}"
        )
    return result


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    db = root / "demo.jsondb"
    lock = root / "demo.jsondb.lock"

    print("=== JSON Database durability demo ===")
    print(f"Database path: {db}\n")

    for path in (db, lock):
        if path.exists():
            path.unlink()

    run_jsondb(db, "init")
    print("[OK] Initialized database")

    inserted = run_jsondb(db, "insert", "users", '{"name": "Ava", "age": 20}')
    document_id = inserted.stdout.strip()
    print(f"[OK] Inserted user {document_id}")

    run_jsondb(db, "check")
    print("[OK] Integrity check passed")

    raw = json.loads(db.read_text(encoding="utf-8"))
    raw["collections"]["users"][document_id]["name"] = "TAMPERED"
    db.write_text(json.dumps(raw), encoding="utf-8")
    print("[!] Tampered with file outside json_database")

    run_jsondb(db, "check", expect=4)
    print("[OK] check correctly failed with exit 4")

    run_jsondb(db, "insert", "users", '{"name": "New"}', expect=4)
    print("[OK] insert on corrupt file correctly failed with exit 4")

    print("\n=== Demo complete ===")


if __name__ == "__main__":
    main()
