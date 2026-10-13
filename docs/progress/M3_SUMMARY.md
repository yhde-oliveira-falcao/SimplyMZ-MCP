# M3 Summary — Features, async jobs, group comparison (flagship workflow 2)
Date: 2026-10-05 | Tag: not yet (CI waived, M3.T3 deferred) | Gate file: docs/progress/gates/M3.json

## Delivered
"What's different between treated and control?" now works end to end. Long work runs as
asynchronous jobs that return a handle at once and survive restarts. The built-in
masstrace-lite detector finds every planted compound in the fixtures with no unexplained
features, groups isotopes and adducts, aligns features across a batch, and compare_groups
ranks differences with blank subtraction, Welch tests and FDR, leading with a small-sample
caveat when replicates are few.

## Tasks
| Task | Status | Commit | Tests |
|---|---|---|---|
| M3.T1 Jobs | VERIFIED | 1a07d77 | 5 unit + 2 component |
| M3.T2 masstrace-lite | VERIFIED | 568549c | 9 unit + 20 component |
| M3.T3 pyOpenMS adapter | DEFERRED (ADR 0001: needs 3-OS spike) | — | — |
| M3.T4 detect_features / get_feature | VERIFIED | 9be0483 | 2 component + contract |
| M3.T5 Alignment | VERIFIED | 9be0483 | 4 unit |
| M3.T6 compare_groups | VERIFIED | 2f8a1fa | 7 unit + 1 component |
| M3.T7 /compare_groups prompt | VERIFIED | 47c43fd | 1 e2e (+ listing) |

## Acceptance criteria
| ID | Criterion | Evidence | Result |
|---|---|---|---|
| M3-AC1 | All 5 planted differential compounds in top 10 | test_M3_AC1_all_planted_differential_compounds_in_top_10 | ✅ |
| M3-AC2 | Blank contaminants absent from the ranked list | test_M3_AC2_blank_contaminants_absent_from_ranked_list | ✅ |
| M3-AC3 | Recall ≥ 95%, precision ≥ 90% on synthetic truth | test_M3_AC3_feature_detection_recall_and_precision (measured 100% / 100%) | ✅ |
| M3-AC4 | Long jobs return a handle in < 1 s, complete, survive restart | test_M3_AC4_long_jobs_return_fast_complete_and_survive_restart | ✅ |
| M3-AC5 | n = 3 per group → small-sample caveat | test_M3_AC5_small_sample_caveat_with_three_per_group | ✅ |

## Gate output
Status: PASS_WITH_WAIVERS on commit f07ca89 (clean worktree) · tests: 316 passed / 0 failed / 0 skipped · core coverage 97.9% · ruff ✅ · mypy ✅ (44 files) · contract 3/3 ✅ · M3 acceptance 5/5 ✅ · M0–M2 regression 33/33 ✅ · test count 316 ≥ 260 · gitleaks: no leaks. Waived: CI run URL; M3.T3 deferred per ADR 0001 (not tagged).

Provenance note: the M3 commits (1a07d77…f07ca89) were made in a working session whose transcript is not part of the reviewing conversation, and STATUS.md claimed the gate had passed before it was run. The gate was then run independently on f07ca89 (result above), the verify.py DEFERRED change was reviewed (requires a recorded decision, reported as a waiver, blocks tagging), and the M3.T3 deferral was checked against ADR 0001.

## Deviations from plan
- M3.T3 deferred under ADR 0001's own condition (spike on macOS/Windows pending); the gate
  now accepts DEFERRED only with a recorded "Deferred by:" decision, reports it as a waiver,
  and Final Verification still requires none to remain.
- detect_features is always asynchronous (even for one run), for a consistent contract.
- Job cancellation and timeouts are cooperative (Python threads cannot be killed).

## Known limitations carried forward
- masstrace-lite and the statistics are validated on synthetic data only; real data in M5.
- No RT warping in alignment.
- CI (3 OS) still waived.

## Reviewer sign-off
- Opus review: pending
- Human (Yuri): pending (M3.T3 deferral rests on ADR 0001)
