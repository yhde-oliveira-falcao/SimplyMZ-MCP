# ADR 0006: Evidence ledger and report number guard
Status: Accepted · Date: 2026-10-04 · Accepted by Yuri Falcao (chat, 2026-10-04)

## Decision
SQLite table, append-only enforced by triggers that abort UPDATE and DELETE. A row holds:
op, params, input hashes, parent handles, versions (simplymz-mcp + key deps), UTC timestamp,
result digest. JSONL export. The report builder fills numbers only from `{ev:…}` slots; a
number guard rejects client narrative containing numeric tokens absent from the referenced
ledger entries.

## Consequences
Reports are machine-verifiable. Some legitimate narrative numbers (e.g. "3 replicates")
must be referenced from the ledger too; the guard's error lists offending tokens.
