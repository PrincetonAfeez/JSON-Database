# Acceptance Criteria Traceability

Maps scope §18 acceptance criteria to tests and documentation. Run `python -m pytest` to verify (137 tests, 1 skipped as of v0.1.1).

| # | Criterion | Evidence |
| --- | --------- | -------- |
| 1 | A new database file can be initialized | `test_init_creates_checksum_inside_database_file`, `test_cli_crud_query_collections_and_check` |
| 2 | A missing database path can be created on first write | `test_missing_database_is_created_on_first_write`, `test_cli_insert_without_init_creates_database_file` |
| 3 | Documents can be inserted into collections | `test_crud_and_uuid_ids`, CLI CRUD test |
| 4 | Inserted documents receive UUID primary keys | `test_crud_and_uuid_ids` |
| 5 | Stored documents include an `id` field | `test_crud_and_uuid_ids` |
| 6 | Documents can be retrieved by ID | `test_crud_and_uuid_ids`, CLI get |
| 7 | Missing documents raise `NotFoundError` | `test_crud_and_uuid_ids`, `test_replace_on_missing_document_raises` |
| 8 | Documents can be updated with shallow merge | `test_update_is_shallow_merge`, `test_update_returns_a_copy` |
| 9 | Documents can be deleted | `test_crud_and_uuid_ids`, CLI delete |
| 10 | Collections can be listed in V1 | `test_replace_upsert_and_collections`, CLI collections |
| 11 | Equality queries work in MVP | `test_equality_and_operator_queries` |
| 12 | Operator queries work in V1 | `test_equality_and_operator_queries`, `test_explicit_comparison_and_exists_operators` |
| 13 | Bulk insert and bulk update commit once in V1 | `test_bulk_operations_commit_once` |
| 14 | Transactions hold the write lock for the whole transaction | Design: `transaction.py` + ADR 0003; `test_nested_transactions_raise` |
| 15 | Transactions commit all changes together | `test_transaction_commits_all_changes` |
| 16 | Transactions roll back completely on exception | `test_transaction_rolls_back_on_exception`, `test_transaction_validation_failure_rolls_back` |
| 17 | Nested transactions raise `TransactionError` | `test_nested_transactions_raise` |
| 18 | The database file is written atomically | `test_atomic_write_*`, ADR 0001 |
| 19 | Crash before `os.replace` leaves old file intact | `test_crash_before_replace_leaves_original_intact` |
| 20 | SHA-256 checksum is stored in the database file | `test_init_creates_checksum_inside_database_file`, `test_make_empty_state_shape` |
| 21 | Corrupting the database file causes a clear error | `test_corrupting_content_raises_integrity_error`, `test_integrity_report_distinguishes_missing_from_corrupt` |
| 22 | File locking prevents concurrent write corruption | `test_two_concurrent_writers_serialize_cleanly`, `test_four_concurrent_writers_all_commit`, `test_concurrency.py` |
| 23 | Lock timeout produces `LockError` and CLI exit code 3 | `test_lock_timeout_in_current_process`, `test_cli_lock_timeout_exit_code` |
| 24 | JSON serialization round-trips required custom types | `test_custom_values_persist_in_documents`, `test_serializer.py` |
| 25 | CLI init/insert/get/update/delete/dump/check work | `test_cli_crud_query_collections_and_check` |
| 26 | CLI errors are user-friendly | `test_cli_exit_codes`, integrity/validation exit-code tests |
| 27 | `StorageEngine` owns atomic writes, locking, serialization, integrity | Layering: `storage.py`; CONTRIBUTING.md |
| 28 | Document/query layer does not call `os.replace`, `msvcrt`, or `fcntl` directly | Grep audit: only `atomic.py`, `lock.py`, `storage.py` touch OS primitives |
| 29 | Core library does not import CLI or web code | Package layout; `json_database/` has no web/CLI imports in library modules except `cli.py` |
| 30 | Tests cover CRUD, transactions, atomicity, integrity, locking, serialization, queries, CLI | Full suite under `tests/` (see module list in README) |

## Layering verification

Run from the repository root:

```powershell
# Document and query layers must not touch OS file primitives directly
rg "os\.replace|msvcrt|fcntl" json_database --glob "!lock.py" --glob "!atomic.py" --glob "!storage.py"
```

Expected: no matches outside `lock.py`, `atomic.py`, and `storage.py`.

## Related documents

- [Architecture decisions (ADR index)](adr/README.md)
- [scripts/demo.py](../scripts/demo.py) — durability / integrity demo (`python scripts/demo.py`)
- [What I learned](WHAT_I_LEARNED.md)
