"""Independent element table for the synthetic-data oracle.

Source: NIST, "Atomic Weights and Isotopic Compositions for All Elements"
(https://physics.nist.gov/cgi-bin/Compositions/stand_alone.pl), relative atomic
masses (u) and representative isotopic compositions (mole fraction).
Kept separate from pyteomics on purpose: ground truth must not come from the same
library the code under test uses. ``tests/unit/test_synth.py`` cross-checks the two.
"""

from __future__ import annotations

import re
from collections import Counter

ELECTRON_MASS = 0.000548579909

# element -> list of (isotope mass, abundance); abundances sum to ~1.
ISOTOPES: dict[str, list[tuple[float, float]]] = {
    "H": [(1.00782503223, 0.999885), (2.01410177812, 0.000115)],
    "C": [(12.0, 0.9893), (13.00335483507, 0.0107)],
    "N": [(14.00307400443, 0.99636), (15.00010889888, 0.00364)],
    "O": [(15.99491461957, 0.99757), (16.99913175650, 0.00038), (17.99915961286, 0.00205)],
    "P": [(30.97376199842, 1.0)],
    "S": [
        (31.9720711744, 0.9499),
        (32.9714589098, 0.0075),
        (33.967867004, 0.0425),
        (35.96708071, 0.0001),
    ],
    "Cl": [(34.968852682, 0.7576), (36.965902602, 0.2424)],
    "Na": [(22.9897692820, 1.0)],
    # K-40 (0.000117) omitted; renormalised below.
    "K": [(38.9637064864, 0.932581), (40.9618252579, 0.067302)],
}

_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)")


def parse_formula(formula: str) -> Counter[str]:
    if not formula or _TOKEN.sub("", formula):
        raise ValueError(f"cannot parse formula {formula!r}")
    counts: Counter[str] = Counter()
    for el, n in _TOKEN.findall(formula):
        if el not in ISOTOPES:
            raise ValueError(f"element {el!r} not in synthetic element table")
        counts[el] += int(n) if n else 1
    return counts


def monoisotopic_mass(formula: str | Counter[str]) -> float:
    counts = parse_formula(formula) if isinstance(formula, str) else formula
    return sum(ISOTOPES[el][0][0] * n for el, n in counts.items())


def isotope_pattern(
    formula: str | Counter[str], n_peaks: int = 4, prune: float = 1e-9
) -> list[tuple[float, float]]:
    """Return [(mass, abundance relative to the monoisotopic peak)] for M+0..M+n_peaks-1.

    Peaks are grouped by nominal mass offset (fine structure collapsed to an
    abundance-weighted mean mass), which is what a ~20k-resolution instrument reports.
    """
    counts = parse_formula(formula) if isinstance(formula, str) else formula
    mono = monoisotopic_mass(counts)
    # distribution over nominal offsets: offset -> (prob, prob-weighted mass)
    dist: dict[int, tuple[float, float]] = {0: (1.0, 0.0)}
    for el, n in counts.items():
        isos = ISOTOPES[el]
        total = sum(a for _, a in isos)
        base = isos[0][0]
        steps = [(round(m - base), m - base, a / total) for m, a in isos]
        for _ in range(n):
            new: dict[int, tuple[float, float]] = {}
            for off, (p, pm) in dist.items():
                for d_nom, d_mass, a in steps:
                    k = off + d_nom
                    if k >= n_peaks:
                        continue
                    q = p * a
                    if q < prune:
                        continue
                    op, opm = new.get(k, (0.0, 0.0))
                    new[k] = (op + q, opm + pm * a + q * d_mass)
            dist = new
    p0 = dist[0][0]
    return [(mono + dist[k][1] / dist[k][0], dist[k][0] / p0) for k in range(n_peaks) if k in dist]
