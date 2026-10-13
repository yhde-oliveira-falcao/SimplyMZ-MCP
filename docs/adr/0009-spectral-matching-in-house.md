# ADR 0009: Spectral similarity implemented in-house; matchms as validation oracle
Status: Accepted · Date: 2026-10-05 · Accepted with amendment by Yuri Falcao (chat, 2026-10-05)

## Context
The plan names matchms for spectral similarity (M4.T4/T5). Measured on 2026-10-05:
matchms 0.33.1 (Apache-2.0) needs a 777 MB environment (core SimplyMZ: 101 MB), depends
on rdkit, numba, matplotlib, pandas and pins scipy < 1.17, which conflicts with the
scipy 1.17 already in the lock file. That defeats the "light `uvx simplymz-mcp`" goal and
the plan's own risk mitigation ("core uses numpy/scipy/pyteomics/matchms/pyarrow only"
assumed matchms was light).

## Decision
Implement CosineGreedy and ModifiedCosine (the published greedy cosine algorithms, as
documented by matchms) and MSP/MGF parsing in `simplymz_mcp.annotation`, with no new core
dependency. matchms is used as an independent oracle: a recorded one-off comparison in a
throwaway environment, and an opt-in test when matchms is importable.

## Consequences
+ Install stays light; no scipy conflict.
− We own ~200 lines of similarity code; correctness is guarded by the matchms comparison
  and unit tests on hand-computed cases.
Reversible: `match_spectrum` calls one function; swapping in matchms later is local.

## Validation (2026-10-05)
`simplymz_mcp.annotation.similarity.cosine` was compared with matchms 0.33.1 CosineGreedy
and ModifiedCosineGreedy on 300 random spectrum pairs × 3 parameter sets (tolerance 0.01 /
0.02 Da, mz_power 0 / 1, intensity_power 1 / 0.5, precursor shifts 0 and 14.0157 Da):
1,800 scores, maximum absolute difference 2.2e-16. `tests/unit/test_similarity.py`
repeats the comparison whenever matchms is importable.

## Amendment (accepted 2026-10-05)
Yuri: keep the lighter built-in engine as the default, but keep matchms as an optional
library the agent can tell users about, and as an option for the final report.

* `match_spectrum(engine="builtin" | "matchms")`; default builtin. With engine="matchms" and
  matchms missing, the tool returns an instructive error with the install command.
* matchms is **not** declared as a package extra: in a single lock file uv resolves
  extras together, and matchms' `scipy<1.17` would downgrade scipy for every user
  (verified: lock fell to scipy 1.16.3). Opt-in install instead:
  `uvx --with "matchms>=0.33,<0.34" simplymz-mcp` (verified: resolves in 9 s with scipy
  1.16.3 confined to that environment).
* Every match_spectrum result states the engine used and discloses the option. Honest
  wording: for CosineGreedy and ModifiedCosineGreedy the two engines give identical scores
  (max difference 2.2e-16), so matchms does not add precision for these methods; it adds an
  independent cross-check now and access to more similarity measures later.
* `server_info` reports `matchms` under `extras` when importable.
* Backlog (docs/backlog.md): matchms-based extended similarity measures, and an option in
  `export_report` (M5) to re-score reported library matches with matchms.
