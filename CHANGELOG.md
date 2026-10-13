# Changelog

## 0.1.0 (unreleased)
- Licensed under GPL-3.0-or-later (ADR 0010).
- Names: PyPI/CLI/MCP server name
  `simplymz-mcp`, Python package `simplymz_mcp`, resources `simplymz://…`, env vars
  `SIMPLYMZ_ROOT` / `SIMPLYMZ_CACHE`, state folder `<root>/.simplymz`, reports in
  `<root>/simplymz_reports/`, error class `SimplyMZError`.
- MCP server with 19 tools, 4 prompts and run/batch resources over stdio.
- Run level: safe mzML loading, run cards with anomaly detection, chromatograms, peak
  integration with disclosed precision.
- Batch QC with ten metrics, configurable thresholds and a fault-injection validation suite.
- Feature detection (masstrace-lite, async jobs), alignment, group comparison with FDR.
- Annotation ladder: adducts, formula enumeration, isotope fit, MSP/MGF libraries with
  licences, greedy/modified cosine (matchms optional), rule-based confidence levels.
- Append-only evidence ledger, verifiable Markdown/HTML reports with a number guard.
- Pinned public demo dataset, MassBank downloader with per-record licences.
