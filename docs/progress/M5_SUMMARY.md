# M5 Summary — Report, public data, evaluation, release
Date: 2026-10-05 | Tag: not yet | Gate file: docs/progress/gates/M5.json

## Delivered
Reports are now verifiable: export_report fills numbers from the ledger, rejects any
untraceable number, and carries every referenced result's limits (precision and engine
notes included). A pinned real public LC-MS file runs through the whole pipeline in
scheduled CI, and a recall benchmark against OpenMS's own output keeps real-data feature
detection honest. Deterministic evaluations pass all thresholds; the LLM comparison is
ready to run. The package builds, installs cleanly and answers over stdio; a release
workflow publishes to TestPyPI and smoke-tests on three OSes.

## Tasks
| Task | Status | Commit | Tests |
|---|---|---|---|
| M5.T1 export_report | VERIFIED | 2076057 | 14 unit (property) + 1 component |
| M5.T2 Public data | VERIFIED | 97710bd | 6 unit (1 network) + 1 component + 1 |
| M5.T3 Real-data integration | VERIFIED | ebf8c01 | 2 network + 2 regression |
| M5.T4 Evaluation harness | VERIFIED | 516fcd0 | 3 + AC3 |
| M5.T5 Docs | VERIFIED | dcf4172 | 1 e2e |
| M5.T6 Packaging | VERIFIED | 3f01a44 | AC4 |
| M5.T7 Demo | DEFERRED (human task per plan) | 3f01a44 (script) | - |

## Acceptance criteria
| ID | Criterion | Evidence | Result |
|---|---|---|---|
| M5-AC1 | Untraceable numbers rejected; every number traces to the ledger | test_M5_AC1_untraceable_numbers_rejected_valid_report_traces | ✅ |
| M5-AC2 | Pipeline end to end on a real public mzML | test_M5_AC2_pipeline_runs_end_to_end_on_real_public_mzml (network) | ✅ |
| M5-AC3 | Deterministic evals meet thresholds; LLM table exists | test_M5_AC3_deterministic_evals_meet_thresholds (6/6); LLM table: human item | ⏳ deterministic ✅, LLM table pending |
| M5-AC4 | Clean install from TestPyPI on 3 OSes | test_M5_AC4_package_builds_and_installs_cleanly (local wheel); TestPyPI run: human item | ⏳ local ✅, TestPyPI pending |
| M5-AC5 | README complete | test_M5_AC5_readme_has_install_config_workflows_benchmarks_limitations | ✅ |

## Gate output
Status: LOCAL_PASS_PENDING_HUMAN on commit 3f70c52 (clean worktree, isolated git worktree) · tests: 456 passed / 0 failed / 2 skipped (matchms optional) · core coverage 97.6% · ruff ✅ · mypy ✅ · contract 3/3 ✅ · M5 acceptance 5/5 ✅ (incl. real-data network test and clean wheel install that parses mzML) · M0–M4 regression 44/44 ✅ · test count 458 ≥ 451 · gitleaks: no leaks. Pending human: LLM evaluation table; TestPyPI release run. Waived: CI; M5.T7 (demo, human task). Not tagged.

An earlier M5 gate run on 45cb1b5 was stopped deliberately: that commit still had the psims packaging bug, so its AC4 pass would have certified a package that cannot read mzML.

## Deviations from plan
- Release-blocking bug fixed (337618e): a clean install could not parse mzML (psims missing from core dependencies); also removed hidden network calls. Smoke tests now load a file.
- Feature detector defaults changed after real data (max_gap 4, min_points 4); M3 acceptance re-verified.
- integrate_peak crash on noisy real traces fixed (found by M5.T3).
- MassBank licences come from MassBank.json because the MSP export has none.
- Demo recording deferred to the human, as the plan defines it.

## Known limitations carried forward
- Real-data feature recall is 5/10 of OpenMS's most intense features on one file; more real data needed before tuning the intensity threshold.
- LLM comparison not yet run; TestPyPI not yet published; CI waived.

## Reviewer sign-off
- Opus review: pending
- Human (Yuri): run LLM eval, enable TestPyPI, record demo
