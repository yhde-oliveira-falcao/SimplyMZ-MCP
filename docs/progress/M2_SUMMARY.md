# M2 Summary — Batch QC (flagship workflow 1)
Date: 2026-10-05 | Tag: not yet (CI waived) | Gate file: docs/progress/gates/M2.json

## Delivered
"Did last night's batch pass?" now has a deterministic answer. A CSV sample sheet becomes a
batch; qc_batch reports ten metrics with pass/warn/fail against configurable thresholds,
names the offending runs, and states its limits. A fault-injection suite proves each
metric fires at twice its threshold, stays quiet at half, and leaves unrelated metrics
alone. Two prompts guide an AI client through QC and chromatogram explanation with
explicit honesty rules.

## Tasks
| Task | Status | Commit | Tests |
|---|---|---|---|
| M2.T1 load_batch | VERIFIED | 61ada34 | 11 unit + 2 component |
| M2.T2 QC metrics | VERIFIED | 3662384 | 13 unit (shared with T3) |
| M2.T3 Thresholds | VERIFIED | 3662384 | (in test_qc.py) |
| M2.T4 qc_batch + resource | VERIFIED | 926934b | 2 component + contract |
| M2.T5 Fault suite | VERIFIED | 0266abf | 13 |
| M2.T6 Prompts | VERIFIED | 546ac7d | 3 e2e |

## Acceptance criteria
| ID | Criterion | Evidence | Result |
|---|---|---|---|
| M2-AC1 | Clean batch: every metric pass | test_M2_AC1_clean_batch_every_metric_passes (ms2_count_cv n/a: no MS2 in QC fixtures) | ✅ |
| M2-AC2 | Fault ≥ 2× threshold → that metric fails, only plausible metrics change | test_M2_AC2_fault_at_2x_or_more_fails_only_plausible_metrics (6 faults × 2×, 4×; allowed side effects in FAULT_CASES) | ✅ |
| M2-AC3 | Fault at 0.5× → not fail | test_M2_AC3_fault_at_half_threshold_does_not_fail (6 faults) | ✅ |
| M2-AC4 | Identical inputs → identical output digest | test_M2_AC4_identical_inputs_give_identical_output (two fresh caches) | ✅ |
| M2-AC5 | qc_batch ≤ budget on largest batch | test_M2_AC5_qc_output_within_budget_on_largest_batch (clean + 24 faulty envelopes) | ✅ |

## Gate output
Status: PASS_WITH_WAIVERS on commit f75b72c · tests: 260 passed / 0 failed / 0 skipped · core coverage 97.4% · ruff ✅ · mypy ✅ · contract 3/3 ✅ · M2 acceptance 21/21 ✅ · M0+M1 regression 12/12 ✅ · test count 260 ≥ 195 · gitleaks: no leaks. Waived: CI run URL (not tagged).

## Deviations from plan
- Added metric blank_contamination_pct so the generator's contaminant fault is detectable.
- Async QC for large batches deferred to M3.T1 (jobs); > 60 runs refused with instructions.
- Mass accuracy is relative to the QC median unless targets are given (stated in limits).

## Known limitations carried forward
- Thresholds were validated on synthetic data only; real-data behaviour is checked in M5.
- Reference features need ≥ 1 QC injection; without QCs and targets QC returns insufficient_evidence.
- CI (3 OS) still waived.

## Reviewer sign-off
- Opus review: pending
- Human (Yuri): pending
