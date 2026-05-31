# ADR 0003: Whole-File Write Lock

## Decision

All writes use one exclusive whole-database file lock.

## Rationale

A single write lock keeps concurrent writers from loading stale state and
overwriting each other. Transactions hold this lock from load through commit.

## Trade-Off

Writes do not run in parallel. This is acceptable for an embedded learning
database.
