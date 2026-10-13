# ADR 0008: Integration precision is disclosed in every result
Status: Accepted · Date: 2026-10-05 · Accepted by Yuri Falcao (chat, 2026-10-05)

## Context
The plan asked for areas within ±3% of truth at SNR ≥ 50. Measured over 300 noise
realisations (synthetic Gaussian peaks, ~12 points per FWHM, RMS noise), the method is
unbiased (+0.05%) with 1.5% relative SD at SNR 50, so ~4% of single traces exceed ±3%.
At SNR ≥ 100 every trace was within ±3% (worst 2.7%). This is a property of noise, not of
the algorithm.

## Decision
Accept the statistical criterion (≥ 95% within ±3% and |bias| < 0.5% at SNR 50; 100% within
±3% at SNR ≥ 100), on the owner's condition that **the MCP tells users**:
- `integrate_peak` returns `data.area_precision` = {tier, note}, puts the note first in
  `limits`, and adds a short precision phrase to the verdict;
- tiers: SNR ≥ 100 within 3% · 50–100 ~1.5% SD (1 in 20 exceeds 3%) · < 50 not validated ·
  undefined SNR not estimable; fewer than 7 points across the peak halves precision;
- every note states the SNR definition (height / RMS noise, not USP peak-to-peak) and the
  validation conditions;
- the tool description carries the same disclosure, so the client knows before calling.

## Consequences
Numbers are traceable to `VALIDATION` in `analytics/integrate.py`; if the method changes,
re-measure and update those constants and this ADR together. Reports (M5) must keep the
precision note next to any reported area.
