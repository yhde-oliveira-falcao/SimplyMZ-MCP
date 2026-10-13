# M4 Summary — Annotation ladder (flagship workflow 3)
Date: 2026-10-05 | Tag: not yet (CI waived) | Gate file: docs/progress/gates/M4.json

## Delivered
"What is this peak?" now gets candidate formulas ranked by mass error and isotope fit, a
library match with matched fragments and licence, and a confidence level (Schymanski 2-5)
computed by a versioned rule table from ledger evidence alone. Out-of-library compounds
get "insufficient_evidence" or a non-library level, never a false identity; decoys never
pass; Level 1 is never claimed. Every tool now rejects unknown arguments.

## Tasks
| Task | Status | Commit | Tests |
|---|---|---|---|
| M4.T1 Adducts | VERIFIED | 579a37a | (80 in test_annotation_formulas.py, T1-T3) |
| M4.T2 Formulas | VERIFIED | 579a37a | |
| M4.T3 Isotopes | VERIFIED | 579a37a | |
| M4.T4 Library | VERIFIED | 59eb099 | 3 unit + 3 component |
| M4.T5 match_spectrum | VERIFIED | 59eb099 | 5 unit |
| M4.T6 assign_confidence | VERIFIED | 3c91455, eadb9e9 | 5 unit + 2 component + 1 e2e |
| M4.T7 propose_formulas + prompt | VERIFIED | 3c91455, 19a76d7 | (component, e2e) |

## Acceptance criteria
| ID | Criterion | Evidence | Result |
|---|---|---|---|
| M4-AC1 | True formula in candidates for 100% of oracle compounds at 5 ppm | test_M4_AC1_true_formula_in_candidates_for_all_oracle_compounds (35 compounds; full list and tool top 20) | ✅ |
| M4-AC2 | With isotopes, true formula first for ≥ 90% below 400 Da | test_M4_AC2_isotopes_rank_truth_first_for_90pct_below_400_da (tool on fixture spectra + oracle set) | ✅ |
| M4-AC3 | In-library spectra → correct top-1 and Level 2 | test_M4_AC3_in_library_spectra_give_top1_and_level_2 (7/7) | ✅ |
| M4-AC4 | Out-of-library → insufficient_evidence / no library claim, 100% | test_M4_AC4_out_of_library_never_gets_a_library_claim (8 cases incl. leave-one-out) | ✅ |
| M4-AC5 | Decoys never exceed threshold | test_M4_AC5_decoys_never_exceed_threshold (cosine and modified cosine) | ✅ |
| M4-AC6 | Polarity mismatch names valid adducts | test_M4_AC6_polarity_mismatch_names_valid_adducts | ✅ |

## Gate output
Status: PASS_WITH_WAIVERS on commit aea9205 (clean worktree, gated on an isolated git worktree) · tests: 449 passed / 0 failed / 2 skipped (matchms optional) · core coverage 97.6% · ruff ✅ · mypy ✅ · contract 3/3 ✅ · M4 acceptance 6/6 ✅ · M0–M3 regression 38/38 ✅ · test count 451 ≥ 316 · gitleaks: no leaks. Waived: CI run URL (not tagged).

Note: commit aea9205 also contains M5.T1–T4 work done while the gate ran (all tested in the same run). Two earlier M4 gate attempts: one died when the session paused (background processes do not survive between turns; partial JSON showed steps 1–5 passing), one failed step 7 on a records bug (a note heading parsed as a task), fixed in aea9205.

## Deviations from plan, and ADRs added
- ADR 0009 (Proposed, needs Yuri): spectral similarity and MSP/MGF parsing in-house; matchms (777 MB, rdkit/numba, scipy<1.17 conflict) used only as validation oracle (exact agreement).
- Isotope prediction by convolution over pyteomics abundances instead of pyteomics isotopologues.
- Formula rules use the extended Seven Golden Rules ratio ranges (common ranges reject phosphoserine).
- MassBank downloader moved to M5.T2 (needs network verification of the release format).
- Three fixture compounds gained a second MS/MS fragment.
- Hardening: unknown tool arguments rejected for every tool.
- verify.py: any Proposed ADR is a pending human item at every milestone.

## Known limitations carried forward
- Validated on synthetic spectra and a synthetic CC0 library only.
- No F, I, Si or metals in formula enumeration; no RT prediction or in-silico fragmentation.

## Reviewer sign-off
- Opus review: pending
- Human (Yuri): ADR 0009 accepted with amendment (2026-10-05)
