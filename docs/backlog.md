# Backlog (ideas outside the current milestones; plan §Risks "scope creep")

- **matchms option in reports** (Yuri, 2026-10-05): when matchms is installed, let
  `export_report` re-score every reported library match with engine="matchms" and print
  both scores side by side. ADR 0009 amendment.
- **Extended similarity via matchms**: expose additional matchms measures (e.g. neutral-loss
  cosine) through `match_spectrum(engine="matchms", method=...)` after v0.1.
- **Faster test suite**: fixture-heavy tests re-parse the same mzML files with fresh
  caches; a session-wide shared Parquet cache could remove most of the ~12 min gate run
  (M4 gate --durations: slowest test 95 s setup).
