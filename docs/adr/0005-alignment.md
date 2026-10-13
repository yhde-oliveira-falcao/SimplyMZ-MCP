# ADR 0005: Feature alignment
Status: Accepted · Date: 2026-10-04 · Accepted by Yuri Falcao (chat, 2026-10-04)

## Decision
Tolerance matching on m/z (ppm) and RT (min); greedy one-to-one assignment by combined
score; unmatched and conflicting features reported. RT warping deferred past v0.1.

## Why
Adequate for small batches (≤ ~50 injections) with modest drift; deterministic and easy
to test. Batches with drift beyond tolerance are flagged by QC (M2) rather than silently
corrected.
