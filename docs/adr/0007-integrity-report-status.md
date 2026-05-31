# ADR 0007: Structured Integrity Report Status

## Decision

`Database.check_integrity()` returns an `IntegrityReport` with a `status` field
whose value is one of `"ok"`, `"missing"`, `"corrupt"`, `"format"`, or
`"storage"`. Callers branch on `status` rather than parsing the human-readable
`message`.

## Rationale

The integrity check fails for several distinct reasons: the file is absent,
the JSON is unparseable, the structural shape is wrong, the checksum does not
match the content, or the OS refused to read the file. A single boolean flag
loses this distinction and forces callers to grep error strings to recover it.
Returning a structured status lets the CLI emit machine-readable output and
lets library callers (tests, scripts) handle each case differently without
string matching.

## Trade-Off

Adding a `Literal`-typed `status` field expands the surface of the public
dataclass — any new failure mode must extend the enum and document the
addition. Acceptable for a learning project that wants its API to be honest
about what it knows.
