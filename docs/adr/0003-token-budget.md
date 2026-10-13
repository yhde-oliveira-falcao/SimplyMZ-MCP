# ADR 0003: Token budget enforcement
Status: Accepted · Date: 2026-10-04 · Accepted by Yuri Falcao (chat, 2026-10-04)

## Decision
Every tool has a hard budget in the registry (default 1,500 tokens). Estimate =
`ceil(len(indented JSON) / 3.5)`. Indented JSON is used because MCP SDK 2.x sends
structured results as indented text content, so this is what the client actually reads.
Over budget → the registry halves the longest list in `data` until it fits and sets
`truncated: true`; if it still does not fit → `BUDGET_EXCEEDED` error with a hint.
Contract tests fail if any example output exceeds its budget without truncation.

## Status of implementation
Implemented in `core/budget.py` and `core/registry.py` (M0.T4). Paging handles arrive with
the first tool that needs them (M1).
