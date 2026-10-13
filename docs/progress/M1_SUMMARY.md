# M1 Summary — Ingestion and run-level tools
Date: 2026-10-04 | Tag: not yet (CI waived) | Gate file: docs/progress/gates/M1.json

## Delivered
SimplyMZ can now load an mzML or mzML.gz file safely, describe it in a compact run card
that flags acquisition problems, extract TIC/BPC/EIC chromatograms with detected peaks, and
integrate a peak with stated methods and warnings. Every result is recorded in an
append-only evidence ledger, and handles (runs and chromatograms) survive a server restart
through a SHA-256-keyed Parquet cache.

## Tasks
| Task | Status | Commit | Tests |
|---|---|---|---|
| M1.T1 Path security | VERIFIED | fa0b8d8 | 21 |
| M1.T2 mzML reader | VERIFIED | d95ab95, f4b5825 | 29 |
| M1.T3 State | VERIFIED | 44c6960 | 6 |
| M1.T4 Ledger | VERIFIED | b7f377f | 8 + 1 e2e |
| M1.T5 Run tools + resource | VERIFIED | eeef5ea | 12 |
| M1.T6 get_chromatogram | VERIFIED | 0beac14 | (shared) |
| M1.T7 integrate_peak | VERIFIED | 0beac14, b3b853c | 15 unit + 3 component |
| M1.T8 tools.md | VERIFIED | b1666cb | 1 |

## Acceptance criteria
| ID | Criterion | Evidence | Result |
|---|---|---|---|
| M1-AC1 | All fixtures load; malformed/vendor fail instructively | test_M1_AC1_all_fixtures_load_and_bad_files_fail_instructively | ✅ |
| M1-AC2 | Run card ≤ 1,500 tokens; dropout flagged, clean runs zero anomalies | test_M1_AC2_run_card_budget_and_dropout_flagging | ✅ |
| M1-AC3 | EIC apex within ±1 scan for every planted compound | test_M1_AC3_eic_apex_within_one_scan_for_every_planted_compound (≥200 compound×run checks; dropout run excluded by design) | ✅ |
| M1-AC4 | Areas within ±3% of analytic truth (SNR ≥ 50) | test_M1_AC4_areas_within_3pct_of_analytic_truth (peaks fully inside acquisition); unit statistics in M1.md | ✅ (statistical at SNR 50, disclosed per ADR 0008) |
| M1-AC5 | Handles survive a restart | test_M1_AC5_handles_survive_server_restart (two stdio processes) | ✅ |
| M1-AC6 | One immutable ledger entry per call | test_M1_AC6_one_immutable_ledger_entry_per_tool_call | ✅ |
| M1-AC7 | Traversal and symlink escape blocked | test_M1_AC7_path_traversal_and_symlink_escape_blocked | ✅ |

## Gate output
Status: PASS_WITH_WAIVERS on commit de5333e · tests: 195 passed / 0 failed / 0 skipped (after ADR 0008 disclosure) · core coverage 97.2% (core, io, state, ledger, analytics) · ruff ✅ · mypy ✅ · contract 3/3 ✅ · M1 acceptance 7/7 ✅ · M0 regression 5/5 ✅ · test count 195 ≥ 85 · gitleaks: no leaks. Waived: CI run URL (not tagged).

## Deviations from plan
- Integration at SNR 50 tested statistically (≥95% within 3%, bias < 0.5%); 100% within 3% at SNR ≥ 100. Accepted by Yuri with mandatory disclosure to users (ADR 0008, implemented and tested).
- M1-AC4 oracle restricted to peaks fully acquired (±4σ inside the run): DEHP at 9.8 min is cut by the 10-min run end; integrate_peak now warns about trace-edge truncation.
- Errors are not written to the ledger (no evidence to cite); "every tool call" read as every successful or insufficient-evidence call.
- Synthetic fixtures sample ~3 points per FWHM, so integrate_peak warns "imprecise" on them; real LC-MS usually has more points.

## Known limitations carried forward
- CI (3 OS) still unverified; waiver recorded.
- Profile-mode data are flagged but not centroided by SimplyMZ.

## Reviewer sign-off
- Opus review: pending
- Human (Yuri): SNR-50 deviation accepted with disclosure (2026-10-05)
