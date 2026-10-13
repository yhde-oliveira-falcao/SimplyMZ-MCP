"""Chromatogram extraction and peak detection (plan M1.T6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from scipy.signal import find_peaks, peak_widths

from simplymz_mcp.io.mzml import RunData

Kind = Literal["TIC", "BPC", "EIC"]
MAX_PEAKS = 10


@dataclass(frozen=True)
class ChromParams:
    kind: Kind
    mz: float | None = None
    mz_tol_ppm: float = 10.0
    rt_start_min: float | None = None
    rt_end_min: float | None = None
    ms_level: int = 1

    def window(self) -> tuple[float, float]:
        assert self.mz is not None
        tol = self.mz * self.mz_tol_ppm * 1e-6
        return self.mz - tol, self.mz + tol


def extract(run: RunData, p: ChromParams) -> tuple[np.ndarray, np.ndarray]:
    """Full-resolution (rt_min, intensity) for the selected scans. EIC sums all centroids
    with |m/z - target| <= target * ppm * 1e-6 (boundary inclusive)."""
    s = run.scans
    sel = s.ms_level == p.ms_level
    if p.rt_start_min is not None:
        sel &= s.rt_min >= p.rt_start_min
    if p.rt_end_min is not None:
        sel &= s.rt_min <= p.rt_end_min
    idx = np.flatnonzero(sel)
    rt = s.rt_min[idx].astype(np.float64)
    if p.kind == "TIC":
        return rt, s.tic[idx].astype(np.float64)
    if p.kind == "BPC":
        return rt, s.base_peak_intensity[idx].astype(np.float64)
    lo, hi = p.window()
    y = np.zeros(idx.size)
    for k, i in enumerate(idx):
        mz, it = run.peaks(int(i))
        a = np.searchsorted(mz, lo, side="left")
        b = np.searchsorted(mz, hi, side="right")
        y[k] = float(it[a:b].sum(dtype=np.float64))
    return rt, y


def noise_level(y: np.ndarray) -> float:
    """Robust noise from first differences: 1.4826 * MAD(diff) / sqrt(2).

    Insensitive to slow baseline drift and to the few large differences inside peaks."""
    if y.size < 3:
        return 0.0
    d = np.diff(y)
    mad = float(np.median(np.abs(d - np.median(d))))
    return float(1.4826 * mad / np.sqrt(2.0))


def detect_peaks(rt: np.ndarray, y: np.ndarray, max_peaks: int = MAX_PEAKS) -> dict[str, Any]:
    """Prominence-based peak picking. Parameters are returned so results are reproducible."""
    noise = noise_level(y)
    ymax = float(y.max()) if y.size else 0.0
    prominence = max(5.0 * noise, 0.01 * ymax, 1.0)
    params = {
        "method": "scipy.signal.find_peaks",
        "min_prominence": round(prominence, 3),
        "noise_estimate": round(noise, 3),
        "max_peaks": max_peaks,
    }
    if y.size < 3 or ymax <= 0:
        return {"params": params, "peaks": [], "n_found": 0}
    idx, props = find_peaks(y, prominence=prominence)
    widths = peak_widths(y, idx, rel_height=0.5)[0] if idx.size else np.empty(0)
    dt = float(np.median(np.diff(rt))) if rt.size > 1 else 0.0
    order = np.argsort(y[idx])[::-1]
    peaks = []
    for j in order[:max_peaks]:
        i = int(idx[j])
        peaks.append(
            {
                "rt_min": round(float(rt[i]), 4),
                "height_counts": float(f"{y[i]:.4g}"),
                "prominence_counts": float(f"{props['prominences'][j]:.4g}"),
                "fwhm_min_approx": round(float(widths[j]) * dt, 4),
            }
        )
    peaks.sort(key=lambda p: p["rt_min"])
    return {"params": params, "peaks": peaks, "n_found": int(idx.size)}
