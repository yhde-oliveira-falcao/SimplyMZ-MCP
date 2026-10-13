# ADR 0001: Feature detection engine
Status: Accepted · Date: 2026-10-04 · Accepted by Yuri Falcao (chat, 2026-10-04)

## Context
`uvx simplymz-mcp` should install fast with no heavy native dependencies, and feature
detection must be testable against known ground truth.

## Decision
Define a `FeatureDetector` interface. Default engine: built-in **masstrace-lite**
(numpy/scipy: mass traces within ppm across consecutive scans, smoothing, peak picking,
13C isotope and adduct grouping). pyOpenMS `FeatureFinderMetabo` becomes the optional
extra `simplymz-mcp[openms]`, implemented in M3.T3 only after the 3-OS spike is green.
asari is not adopted as an extra for v0.1.

## Evidence (docs/spike/M0_engines.md)
Core venv 101 MB; pyOpenMS 297 MB; asari 468 MB with 13 direct deps. Both BSD-3-Clause and
install on Linux. macOS/Windows pending the spike workflow.

## Consequences
+ Light default install, fully testable on synthetic truth.
− masstrace-lite will be weaker than mature engines on real data; thresholds are labelled
  "synthetic-only" and M5 real-data tests measure the gap.
