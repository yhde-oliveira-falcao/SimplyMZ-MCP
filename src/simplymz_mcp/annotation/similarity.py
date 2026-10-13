"""Greedy cosine and modified cosine spectral similarity (plan M4.T5, ADR 0009).

Follows the algorithm documented by matchms (CosineGreedy / ModifiedCosine): peak pairs
within ``tolerance`` Da are scored by the product of their transformed intensities
(mz**mz_power * intensity**intensity_power); pairs are taken greedily in descending order
of that product, each peak used at most once; the score is the sum of selected products
divided by the norms of both transformed spectra. ModifiedCosine also pairs peaks shifted
by the precursor mass difference. Checked against matchms 0.33.1 (see tests).
"""

from __future__ import annotations

import numpy as np


def _candidate_pairs(
    mz_a: np.ndarray, mz_b: np.ndarray, tol: float, shift: float
) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for i, m in enumerate(mz_a):
        lo = np.searchsorted(mz_b, m - shift - tol, side="left")
        hi = np.searchsorted(mz_b, m - shift + tol, side="right")
        pairs.extend((i, int(j)) for j in range(lo, hi))
    return pairs


def cosine(
    mz_a: np.ndarray,
    int_a: np.ndarray,
    mz_b: np.ndarray,
    int_b: np.ndarray,
    tolerance: float = 0.01,
    mz_power: float = 0.0,
    intensity_power: float = 1.0,
    precursor_a: float | None = None,
    precursor_b: float | None = None,
    modified: bool = False,
) -> tuple[float, list[tuple[int, int]]]:
    """Return (score, matched index pairs). Inputs must be sorted by m/z."""
    if mz_a.size == 0 or mz_b.size == 0:
        return 0.0, []
    wa = (mz_a**mz_power) * (int_a**intensity_power)
    wb = (mz_b**mz_power) * (int_b**intensity_power)
    pairs = _candidate_pairs(mz_a, mz_b, tolerance, 0.0)
    if modified:
        if precursor_a is None or precursor_b is None:
            raise ValueError("modified cosine needs both precursor m/z values")
        shift = precursor_a - precursor_b
        if abs(shift) > tolerance:
            pairs += _candidate_pairs(mz_a, mz_b, tolerance, shift)
    if not pairs:
        return 0.0, []
    scores = np.array([wa[i] * wb[j] for i, j in pairs])
    order = np.argsort(-scores, kind="stable")
    used_a: set[int] = set()
    used_b: set[int] = set()
    total, matched = 0.0, []
    for k in order:
        i, j = pairs[int(k)]
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        total += float(scores[k])
        matched.append((i, j))
    norm = float(np.sqrt(np.sum(wa**2)) * np.sqrt(np.sum(wb**2)))
    return (total / norm if norm > 0 else 0.0), sorted(matched)


MATCHMS_INSTALL = 'uvx --with "matchms>=0.33,<0.34" simplymz-mcp'


def matchms_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("matchms") is not None


def cosine_matchms(
    mz_a: np.ndarray,
    int_a: np.ndarray,
    mz_b: np.ndarray,
    int_b: np.ndarray,
    tolerance: float = 0.01,
    precursor_a: float | None = None,
    precursor_b: float | None = None,
    modified: bool = False,
) -> tuple[float, int]:
    """Same measure computed by matchms (optional dependency): (score, n_matched)."""
    from matchms import Spectrum
    from matchms.similarity import CosineGreedy, ModifiedCosineGreedy

    sa = Spectrum(
        mz=np.asarray(mz_a, float),
        intensities=np.asarray(int_a, float),
        metadata={"precursor_mz": precursor_a or 0.0},
    )
    sb = Spectrum(
        mz=np.asarray(mz_b, float),
        intensities=np.asarray(int_b, float),
        metadata={"precursor_mz": precursor_b or 0.0},
    )
    sim = (
        ModifiedCosineGreedy(tolerance=tolerance) if modified else CosineGreedy(tolerance=tolerance)
    )
    res = sim.pair(sa, sb)
    return float(res["score"]), int(res["matches"])
