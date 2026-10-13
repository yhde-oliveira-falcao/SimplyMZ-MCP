# Contributing

1. `uv sync && uv run pre-commit install`.
2. Read `CLAUDE.md` (rules for humans and coding agents alike): stdout is the MCP
   transport, science lives in pure functions, every number in a report must come from
   the ledger, and tests are never loosened to get green.
3. Every change adds tests that fail without it. Expected scientific values come from
   independent oracles (`simplymz_mcp.synth.elements`, analytic formulas).
4. Before a PR: `uv run ruff check . && uv run ruff format --check . && uv run mypy &&
   uv run pytest -m "not network"`. Regenerate `docs/tools.md` with
   `uv run python scripts/gen_tools_doc.py` when tools change.
5. Design changes need an ADR in `docs/adr/` (status Proposed until accepted).
6. Never commit data you may not redistribute, or anything from a past employer.
