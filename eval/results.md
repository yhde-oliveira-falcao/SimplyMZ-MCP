# Evaluation results

## Deterministic evaluations (gated)

| Check | Value | Threshold | Pass |
|---|---|---|---|
| qc_detection_at_2x | 1.0 | 1.0 | ✅ |
| qc_false_fail_at_half | 0.0 | 0.0 | ✅ |
| formula_presence | 1.0 | 1.0 | ✅ |
| formula_rank1_below_400 | 1.0 | 0.9 | ✅ |
| abstention_out_of_library | 1.0 | 1.0 | ✅ |
| decoy_false_positive | 0.0 | 0.0 | ✅ |

Synthetic data only (see docs/data.md). QC matrix: 6 faults x 0.5/2/4x the fail threshold; formulas: 35-compound oracle set; abstention: leave-one-out libraries and shifted-fragment decoys.

## LLM evaluation (reported, not gated)

Not run yet: needs ANTHROPIC_API_KEY (run `uv run python -m eval.llm_eval`).
