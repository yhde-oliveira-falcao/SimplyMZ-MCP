"""Isotope pattern prediction and fit (plan M4.T3).

Prediction: polynomial convolution over nominal mass offsets using pyteomics' isotope
abundances, tracking the abundance-weighted mass of each offset (fine structure
collapsed, as a ~20-60k resolution instrument reports it).
Fit: observed M+1 and M+2 intensities relative to M+0 vs prediction; tolerance
sigma = 10% of the predicted ratio + 0.01 absolute. A candidate whose M+1 or M+2 is more
than 3 sigma away is rejected as an impossible pattern.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np
from pyteomics import mass as pmass

ISOTOPE_SPACING = 1.0033548  # 13C - 12C
REL_SIGMA = 0.10
ABS_SIGMA = 0.01
REJECT_SIGMA = 3.0


def _element_dist(el: str) -> list[tuple[int, float, float]]:
    table = pmass.nist_mass[el]
    mono_mass = table[0][0]
    isos = [(k, m, a) for k, (m, a) in table.items() if k != 0 and a > 0]
    base = min(isos, key=lambda t: abs(t[1] - mono_mass))[0]
    return [(k - base, m - mono_mass, a) for k, m, a in isos]


def predict(counts: dict[str, int], n_peaks: int = 3) -> list[tuple[float, float]]:
    """[(mass offset from monoisotopic, abundance relative to M+0)] for M+0..M+n-1."""
    prob = np.zeros(n_peaks)
    wmass = np.zeros(n_peaks)
    prob[0] = 1.0
    for el, n in counts.items():
        dist = _element_dist(el)
        for _ in range(n):
            new_p = np.zeros(n_peaks)
            new_w = np.zeros(n_peaks)
            for off, dm, a in dist:
                if off >= n_peaks:
                    continue
                new_p[off:] += prob[: n_peaks - off] * a
                new_w[off:] += (wmass[: n_peaks - off] + prob[: n_peaks - off] * dm) * a
            prob, wmass = new_p, new_w
    return [
        (float(wmass[k] / prob[k]) if prob[k] else k * ISOTOPE_SPACING, float(prob[k] / prob[0]))
        for k in range(n_peaks)
    ]


def observe(
    mz: np.ndarray,
    intensity: np.ndarray,
    mono_mz: float,
    charge: int = 1,
    ppm: float = 10.0,
    n_peaks: int = 3,
) -> list[float] | None:
    """Observed intensities of M+0..M+n-1 relative to M+0 (None if M+0 is absent).

    Each isotope peak is searched at mono + k*1.00335/z within max(ppm, 3 mDa)."""
    rel = []
    base = None
    for k in range(n_peaks):
        target = mono_mz + k * ISOTOPE_SPACING / abs(charge)
        tol = max(target * ppm * 1e-6, 0.003 + (0.006 if k == 2 else 0.0))
        a, b = np.searchsorted(mz, target - tol), np.searchsorted(mz, target + tol, side="right")
        val = float(intensity[a:b].sum()) if b > a else 0.0
        if k == 0:
            if val <= 0:
                return None
            base = val
        rel.append(val / base if base else 0.0)
    return rel


def fit(counts: dict[str, int], observed: list[float]) -> dict[str, Any]:
    pred = [a for _, a in predict(counts, len(observed))]
    z = []
    for k in range(1, len(observed)):
        sigma = REL_SIGMA * pred[k] + ABS_SIGMA
        z.append((observed[k] - pred[k]) / sigma)
    worst = max((abs(v) for v in z), default=0.0)
    return {
        "predicted_rel": [round(p, 4) for p in pred],
        "observed_rel": [round(o, 4) for o in observed],
        "z_scores": [round(v, 2) for v in z],
        "score": round(math.exp(-0.5 * sum(v * v for v in z)), 4),
        "rejected": worst > REJECT_SIGMA,
    }


def counts_of(formula_counts: tuple[tuple[str, int], ...] | Counter[str]) -> dict[str, int]:
    return dict(formula_counts)
