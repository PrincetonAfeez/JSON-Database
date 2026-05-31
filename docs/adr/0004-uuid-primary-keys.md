# ADR 0004: UUID Primary Keys

## Decision

Inserted documents receive UUID string IDs.

## Rationale

UUIDs avoid a shared incrementing counter and make ID generation safe without a
separate coordination mechanism.

## Trade-Off

UUIDs are less human-readable than integer IDs.
