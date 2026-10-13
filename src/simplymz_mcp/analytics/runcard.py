"""Run-level summaries: downsampled TIC and anomaly detection (plan M1.T5)."""

from __future__ import annotations

from typing import Any

import numpy as np

from simplymz_mcp.io.mzml import RunData

GAP_FACTOR = 3.0  # RT gap if an MS1 interval exceeds 3x the median interval
DROPOUT_FRACTION = 0.05  # TIC dropout if TIC < 5% of the rolling background level
ROLLING_WINDOW = 101  # MS1 scans; dropouts up to ~20% of this are detectable
BACKGROUND_PERCENTILE = 20  # robust while peaks cover < 80% of the window
MAX_ANOMALIES = 10


def downsample_max(
    x: np.ndarray, y: np.ndarray, n_bins: int = 40
) -> tuple[list[float], list[float]]:
    """Binned maximum: split x into equal-width bins, keep the point with the largest y.

    Preserves peak apexes (unlike averaging); empty bins are skipped.
    """
    if x.size == 0:
        return [], []
    if x.size <= n_bins:
        return x.tolist(), y.tolist()
    edges = np.linspace(float(x[0]), float(x[-1]), n_bins + 1)
    idx = np.clip(np.searchsorted(edges, x, side="right") - 1, 0, n_bins - 1)
    xs, ys = [], []
    for b in range(n_bins):
        members = np.flatnonzero(idx == b)
        if members.size:
            j = members[int(np.argmax(y[members]))]
            xs.append(float(x[j]))
            ys.append(float(y[j]))
    return xs, ys


def rolling_percentile(y: np.ndarray, window: int, q: float) -> np.ndarray:
    """Centred rolling percentile with edge padding (same length as y)."""
    half = window // 2
    padded = np.pad(y, half, mode="edge")
    view = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.asarray(np.percentile(view, q, axis=1), dtype=np.float64)


def _ranges(mask: np.ndarray) -> list[tuple[int, int]]:
    """Consecutive True runs as (start, end) inclusive indices."""
    out = []
    i, n = 0, mask.size
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def detect_anomalies(
    rt: np.ndarray, tic: np.ndarray, n_peaks: np.ndarray, polarity: np.ndarray
) -> list[dict[str, Any]]:
    """Anomalies on MS1 scans (arrays already restricted to MS1, in acquisition order)."""
    found: list[dict[str, Any]] = []
    if rt.size >= 3:
        d = np.diff(rt)
        med = float(np.median(d))
        for k in np.flatnonzero(d > GAP_FACTOR * med).tolist():
            found.append(
                {
                    "type": "rt_gap",
                    "rt_start_min": round(float(rt[k]), 3),
                    "rt_end_min": round(float(rt[k + 1]), 3),
                    "n_scans": 0,
                }
            )
    empty = n_peaks == 0
    for a, b in _ranges(empty):
        found.append(
            {
                "type": "empty_scans",
                "rt_start_min": round(float(rt[a]), 3),
                "rt_end_min": round(float(rt[b]), 3),
                "n_scans": b - a + 1,
            }
        )
    if tic.size >= 11:
        window = min(ROLLING_WINDOW, tic.size - (1 - tic.size % 2))  # odd, <= run length
        base = rolling_percentile(tic, window, BACKGROUND_PERCENTILE)
        drop = (tic < DROPOUT_FRACTION * base) & ~empty & (base > 0)
        for a, b in _ranges(drop):
            found.append(
                {
                    "type": "tic_dropout",
                    "rt_start_min": round(float(rt[a]), 3),
                    "rt_end_min": round(float(rt[b]), 3),
                    "n_scans": b - a + 1,
                }
            )
    pols = set(polarity.tolist()) - {0}
    if len(pols) > 1:
        switches = int(np.count_nonzero(np.diff(polarity[polarity != 0]) != 0))
        found.append(
            {
                "type": "polarity_switching",
                "rt_start_min": round(float(rt[0]), 3),
                "rt_end_min": round(float(rt[-1]), 3),
                "n_scans": switches,
            }
        )
    found.sort(key=lambda a: a["rt_start_min"])
    return found


def _sig(v: float, digits: int = 3) -> float:
    return float(f"{v:.{digits}g}")


def run_card(run: RunData, rel_path: str, n_points: int = 40) -> dict[str, Any]:
    s = run.scans
    ms1 = s.ms_level == 1
    rt1, tic1 = s.rt_min[ms1], s.tic[ms1]
    xs, ys = downsample_max(rt1, tic1, n_points)
    anomalies = detect_anomalies(rt1, tic1, s.n_peaks[ms1], s.polarity[ms1])
    ms2 = s.ms_level >= 2
    prec = s.precursor_mz[ms2]
    prec = prec[~np.isnan(prec)]
    interval = float(np.median(np.diff(rt1))) if rt1.size > 1 else None
    j = int(np.argmax(tic1)) if tic1.size else None
    return {
        "file": rel_path,
        "sha256": run.sha256,
        "n_spectra": len(s),
        "ms_level_counts": run.meta["ms_level_counts"],
        "polarity": run.meta["polarity"],
        "spectrum_mode": run.meta["spectrum_mode"],
        "rt_range_min": run.meta["rt_range_min"],
        "ms1_median_interval_min": round(interval, 4) if interval else None,
        "tic": {
            "median": _sig(float(np.median(tic1))) if tic1.size else None,
            "max": _sig(float(tic1[j])) if j is not None else None,
            "rt_of_max_min": round(float(rt1[j]), 3) if j is not None else None,
        },
        "tic_trace": {"rt_min": [round(v, 3) for v in xs], "tic": [_sig(v) for v in ys]},
        "ms2": {
            "count": int(np.count_nonzero(ms2)),
            "precursor_mz_range": [round(float(prec.min()), 4), round(float(prec.max()), 4)]
            if prec.size
            else None,
        },
        "anomalies": anomalies[:MAX_ANOMALIES],
        "n_anomalies": len(anomalies),
        "file_warnings": run.meta.get("warnings", []),
    }
