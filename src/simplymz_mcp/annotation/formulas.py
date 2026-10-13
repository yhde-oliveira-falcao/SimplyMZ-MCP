"""Molecular formula enumeration (plan M4.T2).

Enumerates neutral formulas whose monoisotopic mass is within ``ppm`` of a target, then
applies a documented subset of Kind & Fiehn's "Seven Golden Rules" (BMC Bioinformatics
2007, 8:105): element count limits by mass range (rule 1), integer non-negative ring and
double-bond equivalents for a neutral even-electron molecule (rules 2/3, via RDBE), and
the *extended* element-ratio ranges of rule 4 (H/C 0.1-6, N/C <= 4, O/C <= 3, P/C <= 2,
S/C <= 3, Cl/C <= 2, Br/C <= 2). The "common" ranges (O/C <= 1.2, P/C <= 0.3, ...) reject
real metabolites such as phosphoserine (O/C 2.0, P/C 0.33), so they are not used as hard
filters. Isotope ratio checks (rule 5) are done separately in isotopes.py.
Formulas are written in Hill order: C, H, then other elements alphabetically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pyteomics import mass as pmass

MONO = {el: float(pmass.nist_mass[el][0][0]) for el in ("C", "H", "N", "O", "P", "S", "Cl", "Br")}
# Rule 1 limits (Kind & Fiehn 2007, table for < 500 Da and < 1000 Da).
LIMITS_500 = {"C": 39, "H": 72, "N": 20, "O": 20, "P": 9, "S": 10, "Cl": 8, "Br": 5}
LIMITS_1000 = {"C": 78, "H": 126, "N": 25, "O": 27, "P": 9, "S": 14, "Cl": 11, "Br": 8}
RATIOS = {"N": 4.0, "O": 3.0, "P": 2.0, "S": 3.0, "Cl": 2.0, "Br": 2.0}  # extended ranges
H_PER_C = (0.1, 6.0)
ORDER = ("C", "H", "N", "O", "P", "S", "Cl", "Br")
HILL = ("C", "H", "Br", "Cl", "N", "O", "P", "S")


@dataclass(frozen=True)
class Candidate:
    formula: str
    counts: tuple[tuple[str, int], ...]
    mass: float
    ppm: float
    rdbe: float


def hill(counts: dict[str, int]) -> str:
    parts = []
    for el in HILL:
        n = counts.get(el, 0)
        if n:
            parts.append(el if n == 1 else f"{el}{n}")
    return "".join(parts)


def rdbe(c: dict[str, int]) -> float:
    halogen = c.get("Cl", 0) + c.get("Br", 0)
    return c.get("C", 0) - (c.get("H", 0) + halogen) / 2 + (c.get("N", 0) + c.get("P", 0)) / 2 + 1


def passes_rules(c: dict[str, int]) -> bool:
    carbons = c.get("C", 0)
    if carbons == 0:
        return False
    r = rdbe(c)
    if r < 0 or abs(r - round(r)) > 1e-9:  # neutral even-electron molecule
        return False
    if not H_PER_C[0] <= c.get("H", 0) / carbons <= H_PER_C[1]:
        return False
    return all(c.get(el, 0) / carbons <= lim for el, lim in RATIOS.items())


def enumerate_formulas(
    neutral_mass: float, ppm: float = 5.0, elements: str = "CHNOPS", max_candidates: int = 200
) -> list[Candidate]:
    """All rule-passing neutral formulas within ``ppm``, sorted by |ppm| (then formula)."""
    allowed = [el for el in ORDER if el in _parse_elements(elements)]
    if "C" not in allowed or "H" not in allowed:
        raise ValueError("elements must include C and H")
    limits = LIMITS_500 if neutral_mass < 500 else LIMITS_1000
    tol = neutral_mass * ppm * 1e-6
    hetero = [el for el in allowed if el not in ("C", "H")]
    out: list[Candidate] = []

    def recurse(i: int, counts: dict[str, int], m: float) -> None:
        if i == len(hetero):
            for n_c in range(1, limits["C"] + 1):
                rest = neutral_mass - m - n_c * MONO["C"]
                if rest < -tol:
                    break
                h_lo = max(0, math.ceil((rest - tol) / MONO["H"]))
                h_hi = min(limits["H"], math.floor((rest + tol) / MONO["H"]))
                for n_h in range(h_lo, h_hi + 1):
                    c = {**counts, "C": n_c, "H": n_h}
                    total = m + n_c * MONO["C"] + n_h * MONO["H"]
                    err = (total - neutral_mass) / neutral_mass * 1e6
                    if abs(err) <= ppm and passes_rules(c):
                        c = {k: v for k, v in c.items() if v}
                        out.append(
                            Candidate(hill(c), tuple(sorted(c.items())), total, err, rdbe(c))
                        )
            return
        el = hetero[i]
        for n in range(limits[el] + 1):
            mm = m + n * MONO[el]
            if mm > neutral_mass + tol:
                break
            recurse(i + 1, {**counts, el: n} if n else counts, mm)

    recurse(0, {}, 0.0)
    out.sort(key=lambda c: (abs(c.ppm), c.formula))
    return out[:max_candidates]


def _parse_elements(spec: str) -> set[str]:
    found, i = set(), 0
    while i < len(spec):
        two = spec[i : i + 2]
        if two in ("Cl", "Br"):
            found.add(two)
            i += 2
        else:
            found.add(spec[i])
            i += 1
    unknown = found - set(ORDER)
    if unknown:
        raise ValueError(f"unsupported elements {sorted(unknown)}; allowed: {ORDER}")
    return found
