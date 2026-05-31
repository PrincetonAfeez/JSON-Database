# ADR 0002: Whole-File Rewrite

## Decision

The storage engine rewrites the entire JSON database file on each commit.

## Rationale

Whole-file rewrite is simple, inspectable, and easy to reason about for a
learning database.

## Trade-Off

Write cost grows with file size. A future append-only log or WAL could reduce
write amplification, but that is outside V1.
