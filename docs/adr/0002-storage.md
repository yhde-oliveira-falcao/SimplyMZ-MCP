# ADR 0002: Storage
Status: Accepted · Date: 2026-10-04 · Accepted by Yuri Falcao (chat, 2026-10-04)

## Decision
SQLite (stdlib) for handles, runs, batches, jobs and the ledger. Parquet (pyarrow, added in
M1) for scan tables, feature tables and cached chromatograms, keyed by file SHA-256.
DuckDB deferred.

## Why
Fewest dependencies; SQLite gives transactions and triggers (needed for an append-only
ledger); Parquet is fast and inspectable with any tool.

## Consequences
pyarrow adds ~40–60 MB to the core install. Cache directory is configurable and excluded
from git (`.simplymz/`).
