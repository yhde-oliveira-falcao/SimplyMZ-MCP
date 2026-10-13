# M0 Summary — Foundations
Date: 2026-10-04 | Tag: not yet (CI waived until the repo is on GitHub) | Gate file: docs/progress/gates/M0.json

## Delivered
An installable, empty-but-real MCP server: `uvx --from . simplymz-mcp` starts a stdio server
whose only tool, `server_info`, returns a valid envelope, and nothing but JSON-RPC reaches
stdout. Every later tool will go through the core registry (envelope, instructive errors,
token budgets). A deterministic synthetic-data generator produces 20 mzML runs with ground
truth (clean pos/neg, QC batch with planted differences, six fault variants, DDA MS2 run
with one out-of-library compound) plus a synthetic MS/MS library. The milestone gate,
progress records and agent rules are in place.

## Tasks
| Task | Status | Commit | Tests |
|---|---|---|---|
| M0.T1 Scaffold | VERIFIED | 64160a0 | tooling (pre-commit, uv sync) |
| M0.T2 CI | VERIFIED (run pending) | ee89845 | actionlint; AC1 structural test |
| M0.T3 Server skeleton | VERIFIED | 7bdff3d | 3 e2e |
| M0.T4 Core | VERIFIED | 7ce3ef2 | 29 unit |
| M0.T5 Synthetic data | VERIFIED | cb7bd34, 324e29b | 46 unit |
| M0.T6 Spike + ADRs | VERIFIED (Linux only) | 4eaffd3 | n/a |
| M0.T7 Progress system | VERIFIED | 40b7aff | 2 contract, 5 acceptance |

## Acceptance criteria
| ID | Criterion | Evidence | Result |
|---|---|---|---|
| M0-AC1 | CI green on all 6 matrix jobs | test_M0_AC1_ci_workflow_defines_six_matrix_jobs (structure); CI run URL in STATUS.md | ⏳ structure ✅, run pending |
| M0-AC2 | `uvx --from . simplymz-mcp --help`; server_info valid over stdio | test_M0_AC2_uvx_help_and_server_info_over_stdio | ✅ |
| M0-AC3 | Only JSON-RPC on stdout for a full session | test_M0_AC3_only_json_rpc_on_stdout_for_full_session (+ e2e mutation check) | ✅ |
| M0-AC4 | Deterministic fixtures that parse, truth for each | test_M0_AC4_fixtures_deterministic_parse_and_have_truth; test_synth.py | ✅ |
| M0-AC5 | verify.py M0 passes; summary written | test_M0_AC5_gate_has_all_nine_steps_and_summary_covers_criteria; gate JSON | ⚠️ strict gate passes with CI waiver |

## Gate output
Status: LOCAL_PASS_PENDING_HUMAN on commit 4c196cc (clean worktree) · tests: 85 passed / 0 failed / 0 skipped · core coverage 99.4% · ruff ✅ · mypy ✅ · contract ✅ · acceptance 5/5 ✅ · test count 85 (first gate) · gitleaks: no leaks.
Pending human items (8): CI run URL; ADRs 0001–0007 Accepted. Strict `verify.py M0` exits 1 until these are done, so `m0-verified` is NOT tagged.

## Deviations from plan, and ADRs added
- MCP SDK 2.3: FastMCP is now `MCPServer`; SDK diverts stdout during serving (see M0.md T3).
- Token budget estimated on indented JSON (ADR 0003).
- gitleaks 8.30 uses `gitleaks git` (plan said `gitleaks detect`).
- pyteomics `isotopologues()` drops ²H/¹⁷O by default; isotope oracle is the exact analytic M+1 formula.
- Fixtures gzip-compressed (except one) to stay at 1.5 MB; cross-platform check by content digest.
- verify.py step 7 adds human/external checks (CI run URL, ADRs Accepted).
- ADRs 0001–0007 added and Accepted.
- verify.py supports a recorded CI waiver: status `pass_with_waivers`, never tagged.

## Known limitations carried forward
- macOS/Windows behaviour (CI, engine spike) unverified until the repo is on GitHub.
- `PROJECT_BRIEF.md` is not in the repo yet; Yuri to add it from his copy.
- Fixture generation needs psims (dev/`fixtures` extra). psims ships vendored controlled-vocabulary files; generation without network access has not been tested.

## Reviewer sign-off
- Opus review: pending
- Human (Yuri): ADRs 0001–0007 Accepted (chat, 2026-10-04); CI run explicitly deferred (waiver in STATUS.md)
