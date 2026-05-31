# What I Learned

A one-page reflection on building a small JSON document database in pure Python.

## Serialization is the floor

Every ORM and document store eventually reduces to bytes on disk. Implementing
`JsonSerializer` with explicit type tags for `datetime`, `Decimal`, `set`, and
`bytes` made the cost of “JSON-like but not JSON” visible. Rejecting non-finite
floats and `frozenset` at the write boundary keeps the on-disk format strict and
the checksum reproducible.

## Atomic write is non-negotiable

A crash mid-write must never leave a torn file. Temp file → flush → fsync →
`os.replace` (ADR 0001) is the smallest pattern that works. The test that simulates
failure before replace proves the old file survives — that single test is worth
more than pages of prose.

## Locks define your concurrency story

A threading lock would not survive multiple processes. OS file locks (`fcntl` /
`msvcrt`, ADR 0006) serialize writers across processes. Holding the lock for the
entire transaction (ADR 0003) prevents lost updates between load and commit. The
deliberate choice to **not** unlink the lock file (ADR 0009) trades a leftover
empty file for freedom from inode races.

## Integrity is two different questions

“Is this file structurally valid?” and “Was it edited outside the library?” are
related but not identical. A structured `IntegrityReport` with separate
`format`, `corrupt`, and `missing` statuses (ADR 0007) keeps audit results honest.
Autocommit reads raise exceptions; `check_integrity()` returns a report — two
contracts, both documented.

## Layering is the lesson

The CLI never calls `os.replace`. Collections never open files. `StorageEngine`
is the seam where durability lives. That arrow — CLI → Database → Collection →
StorageEngine → filesystem — is the architecture I would reuse in any embedded
store, even if the format changed.

## Process

This project reached v0.1.1 through three review passes: an initial build,
a 25-item audit (CLI contracts, integrity semantics, tests), and a 16-item
edge-case pass (finite timeouts, load validation, documentation). Iterative
review mattered as much as the first implementation.

## Limits I accept on purpose

Whole-file rewrite, no indexes, no network server, no encryption, no WAL. Those
are not oversights — they keep the artifact reviewable in one sitting and keep
the learning goal clear: **durability primitives**, not production scale.
