# ADR 0005: Single-File Checksum

## Decision

The SHA-256 checksum is stored in `meta.content_sha256` inside the main database
file.

## Rationale

A separate sidecar checksum file can get out of sync if a crash happens after
the database file is replaced but before the sidecar is updated. Keeping the
checksum in the same JSON envelope lets one atomic write commit both together.

## Trade-Off

The checksum is computed over a canonical representation with
`meta.content_sha256` temporarily set to null. It detects accidental corruption
but does not prevent malicious modification.
