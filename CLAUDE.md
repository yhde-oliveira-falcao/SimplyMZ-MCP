# CLAUDE.md — rules for coding agents in this repo

**Start of every session:** read `docs/progress/STATUS.md`, then the current milestone in
`IMPLEMENTATION_PLAN.md`. Work tasks in order. Never start milestone N+1 while gate N is red.

## Hard constraints
- The LLM plans and explains; tools compute; the ledger remembers.
- No tool ever returns raw peak arrays to the client.
- Every number in a report comes from a ledger entry.
- `status: "insufficient_evidence"` is a correct result, not a failure.
- Build only from open-source libraries and public or synthetic data. **No code, data or
  formats from past employers (Sciex, Scispot or any other).**

## Verification rules
- Every task adds tests that would fail without the task's code.
- Run the task's tests, then the full fast suite (`uv run pytest -m "not network" -q`),
  before marking a task VERIFIED in `docs/progress/M<n>.md` (template in plan §2.2).
- Never delete, skip, xfail or loosen a test (tolerances included) to get green. If a test is
  genuinely wrong, fix it in a separate commit and log why under "Deviations".
- Test count must not decrease between gates (`scripts/verify.py` enforces it).
- Same failure after **3 fix attempts** → mark the task `BLOCKED` in STATUS.md with the error,
  what was tried, and a proposal. Stop and wait for the human.
- Never mark anything verified by reasoning alone: paste the actual command and output.
- Expected scientific values come from independent oracles (`simplymz_mcp.synth.elements`,
  analytic formulas), never from the library function under test.

## Engineering rules
- stdout is the MCP transport: log to **stderr only**; `print()` is banned (ruff T20).
- Pure functions for all science; MCP tools are thin wrappers registered via `core.registry`.
- Units in every field name (`mz_tol_ppm`, `rt_min`, `area_counts`).
- No network except `fetch_public_dataset` and tests marked `network`.
- Never commit secrets, `.env` files or credentials (gitleaks runs in pre-commit and CI).
- Fixtures in `tests/fixtures/` are generated: change `simplymz_mcp.synth`, then run
  `uv run python scripts/generate_fixtures.py` and commit both. Never hand-edit them.

## Commands
- Setup: `uv sync` · Hooks: `uv run pre-commit install`
- Fast suite: `uv run pytest -m "not network" -q`
- Gate: `uv run python scripts/verify.py M<n>` (writes `docs/progress/gates/M<n>.json`)
- Gate procedure: verify → write `M<n>_SUMMARY.md` from the JSON → verify again → commit →
  `git tag m<n>-verified` (only on a full PASS, never on PENDING) → update STATUS.md.
