"""Rank formula candidates by mass error and isotope fit (plan M4.T2/T3)."""

from __future__ import annotations

import math
from typing import Any

from simplymz_mcp.annotation.formulas import Candidate
from simplymz_mcp.annotation.isotopes import fit

PPM_SIGMA = 2.0  # typical high-resolution mass error used to weight candidates


def rank(cands: list[Candidate], observed: list[float] | None) -> list[dict[str, Any]]:
    """Score = exp(-0.5 (ppm / 2)^2) x isotope score (when isotope data exist).

    Candidates with an impossible isotope pattern are kept but marked rejected and ranked
    after all others, so the caller can show why they were excluded."""
    out = []
    for c in cands:
        mass_score = math.exp(-0.5 * (c.ppm / PPM_SIGMA) ** 2)
        row: dict[str, Any] = {
            "formula": c.formula,
            "neutral_mass": round(c.mass, 6),
            "ppm": round(c.ppm, 2),
            "rdbe": c.rdbe,
        }
        if observed is not None:
            f = fit(dict(c.counts), observed)
            row["isotope"] = f
            row["rejected"] = f["rejected"]
            row["score"] = round(mass_score * f["score"], 4)
        else:
            row["rejected"] = False
            row["score"] = round(mass_score, 4)
        out.append(row)
    out.sort(key=lambda r: (r["rejected"], -r["score"], abs(r["ppm"]), r["formula"]))
    return out
