# ADR 0001: Atomic Write With Temp File And Rename

## Decision

Commits write the new database bytes to a temp file in the same directory, flush
and fsync that temp file, then replace the database file with `os.replace`.

## Rationale

Replacing a file within the same filesystem avoids half-written destination
files. After a crash, readers should see either the old complete database or the
new complete database.

## Trade-Off

This protects file replacement, but every commit still rewrites the whole
database file.
