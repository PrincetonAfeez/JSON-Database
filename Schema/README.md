# JSON Database Schemas

This folder documents the simple schema contracts for the JSON Database project.

## Files

- `database.schema.json` — persisted `.jsondb` file envelope with `meta` and `collections`.
- `document.schema.json` — stored document object shape, including the generated `id` field.
- `query.schema.json` — query criteria object used by `find()` and the CLI `query` command.
- `collection-name.schema.json` — standalone collection-name validation contract.

## Notes

These schemas are documentation and validation aids. They do not replace the runtime validation in the Python package.

Known limits of standard JSON Schema for this project:

- It cannot recompute or verify `meta.content_sha256`; it can only check that the checksum has the expected string shape.
- It cannot require each stored document's `id` value to equal that document's key without validator-specific extensions.
- It describes the persisted JSON representation, including `__jsondb_type__` envelopes for custom serialized values.
