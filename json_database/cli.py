"""argparse command-line interface for json_database.

Exit codes:
    0 success
    1 not found (collection or document)
    2 invalid user input, invalid JSON argument, invalid query, transaction state error,
      or invalid lock timeout (including non-finite values)
    3 lock timeout
    4 integrity failure, missing database file, or invalid database format
    5 storage failure or other unexpected internal error
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from typing import Any

from . import __version__
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
from .serializer import JsonSerializer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jsondb", description="Small JSON-backed document database")
    parser.add_argument("--version", action="version", version=f"jsondb {__version__}")
    parser.add_argument("--db", required=True, help="Path to the database file")
    parser.add_argument("--timeout", type=float, default=5.0, help="Lock timeout in seconds")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")

    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create an empty database")
    init.add_argument("--force", action="store_true", help="Overwrite an existing database")

    insert = subparsers.add_parser("insert", help="Insert a document")
    insert.add_argument("collection")
    insert.add_argument("document")

    get = subparsers.add_parser("get", help="Get a document by ID")
    get.add_argument("collection")
    get.add_argument("document_id")

    update = subparsers.add_parser("update", help="Shallow-merge document fields")
    update.add_argument("collection")
    update.add_argument("document_id")
    update.add_argument("updates")

    replace = subparsers.add_parser("replace", help="Replace a document")
    replace.add_argument("collection")
    replace.add_argument("document_id")
    replace.add_argument("document")

    delete = subparsers.add_parser("delete", help="Delete a document")
    delete.add_argument("collection")
    delete.add_argument("document_id")

    query = subparsers.add_parser("query", help="Query documents")
    query.add_argument("collection")
    query.add_argument("criteria")

    dump = subparsers.add_parser("dump", help="Print the database or one collection")
    dump.add_argument("collection", nargs="?")

    check = subparsers.add_parser("check", help="Check database integrity")
    check.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the integrity report as JSON on stdout",
    )

    subparsers.add_parser("collections", help="List collections")

    return parser


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout_to_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    output_serializer = JsonSerializer(pretty=args.pretty)

    try:
        db = Database(args.db, timeout=args.timeout)
        if args.command == "init":
            db.init(force=args.force)
            print(f"initialized: {args.db}")
            return 0
        if args.command == "insert":
            document = _parse_json_argument(args.document, "document")
            document_id = db.collection(args.collection).insert(document)
            print(document_id)
            return 0
        if args.command == "get":
            _print_json(output_serializer, db.collection(args.collection).get(args.document_id))
            return 0
        if args.command == "update":
            updates = _parse_json_argument(args.updates, "updates")
            _print_json(output_serializer, db.collection(args.collection).update(args.document_id, updates))
            return 0
        if args.command == "replace":
            document = _parse_json_argument(args.document, "document")
            _print_json(output_serializer, db.collection(args.collection).replace(args.document_id, document))
            return 0
        if args.command == "delete":
            db.collection(args.collection).delete(args.document_id)
            print(f"deleted: {args.collection}/{args.document_id}")
            return 0
        if args.command == "query":
            criteria = _parse_json_argument(args.criteria, "criteria")
            _print_json(output_serializer, db.collection(args.collection).find(criteria))
            return 0
        if args.command == "dump":
            if args.collection:
                payload: Any = db.collection(args.collection).all()
            else:
                payload = db.dump()
            _print_json(output_serializer, payload)
            return 0
        if args.command == "check":
            report = db.check_integrity()
            if args.as_json:
                payload = dataclasses.asdict(report)
                payload["path"] = str(payload["path"])
                sys.stdout.write(json.dumps(payload, indent=2) + "\n")
                sys.stdout.flush()
                return 0 if report.ok else 4
            if report.ok:
                print("OK: integrity check passed")
                return 0
            print(f"ERROR: {report.message}", file=sys.stderr)
            if report.expected is not None:
                print(f"expected: {report.expected}", file=sys.stderr)
            if report.actual is not None:
                print(f"actual:   {report.actual}", file=sys.stderr)
            return 4
        if args.command == "collections":
            for collection in db.collections():
                print(collection)
            return 0
        parser.error(f"unknown command: {args.command}")
    except NotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (ValidationError, SerializationError, QueryError, TransactionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except LockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except (IntegrityError, DatabaseFormatError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    except StorageError as exc:
        print(f"storage error: {exc}", file=sys.stderr)
        return 5
    except JsonDBError as exc:
        # Defensive catch for any future JsonDBError subclass not matched
        # above. All concrete subclasses raised by today's API are caught
        # explicitly; this branch only triggers if a new subclass is added
        # to errors.py without a matching except above.
        print(f"error: {exc}", file=sys.stderr)
        return 5


def _reconfigure_stdout_to_utf8() -> None:
    """Force stdout/stderr to UTF-8 so non-ASCII content doesn't crash on
    legacy Windows code pages. Available on Python 3.7+; harmless elsewhere."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _parse_json_argument(value: str, label: str) -> Any:
    try:
        return JsonSerializer(pretty=False).loads(value)
    except SerializationError as exc:
        raise SerializationError(f"invalid JSON {label}: {exc}") from exc


def _print_json(serializer: JsonSerializer, value: Any) -> None:
    data = serializer.dumps(value)
    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        stream.write(data)
        stream.flush()
        return
    # Text path: only reached when `sys.stdout` has no `.buffer` attribute,
    # e.g. captured under pytest's `capsys`. `_reconfigure_stdout_to_utf8`
    # at CLI start makes a `UnicodeEncodeError` here essentially impossible
    # for real consoles; if one does fire (a non-reconfigurable wrapper),
    # we let it propagate cleanly so the user sees the real cause.
    sys.stdout.write(data.decode("utf-8"))
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
