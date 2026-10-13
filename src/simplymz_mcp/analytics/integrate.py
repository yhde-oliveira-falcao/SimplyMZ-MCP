"""Peak integration (plan M1.T7). All conventions are stated in the returned ``method``."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.signal import savgol_filter

from simplymz_mcp.analytics.chromatogram import noise_level

STOP_FRACTION = 0.001  # walk out until signal <= max(3*noise, 0.1% of apex)
VALLEY_FRACTION = 0.05  # a local minimum above 5% of apex means an overlapping neighbour


# Measured validation of this method (300 noise realisations per row; synthetic Gaussian
# peaks, linear sloped baseline, white noise; see tests/unit/test_chromatogram.py and
# docs/progress/M1.md, M1.T7). Disclosed with every result: accepted by the project owner on
# the condition that users are told.
VALIDATION = {
    "snr_definition": "height / RMS noise (not the USP peak-to-peak definition, which gives "
    "roughly 2-3x larger numbers for the same trace)",
    "conditions": "synthetic Gaussian peaks, ~12 points per FWHM, white noise",
    "snr50_rel_sd_pct": 1.5,
    "snr50_within_3pct": 0.957,
    "snr100_max_err_pct": 2.7,
    "coarse_snr50_rel_sd_pct": 3.1,
}


def area_precision(snr: float | None, points: int) -> dict[str, Any]:
    """Disclose how precise this method's area is expected to be for this trace."""
    v = VALIDATION
    if snr is None:
        tier = "unknown"
        note = (
            "Noise is not measurable in this trace (SNR undefined), so area precision "
            "cannot be estimated from the data; sampling and intensity noise still apply."
        )
    elif snr < 50:
        tier = "not_validated"
        note = (
            "SNR below 50: area precision of this method was not validated; expect "
            "deviations well beyond +/-3% from the true area."
        )
    elif snr < 100:
        tier = "approx_3pct"
        note = (
            f"At SNR 50-100 this method's single-trace area has about "
            f"{v['snr50_rel_sd_pct']}% relative SD: roughly 1 trace in 20 deviates by more "
            f"than +/-3% from the true area ({v['snr50_within_3pct']:.0%} within 3% in "
            f"validation)."
        )
    else:
        tier = "within_3pct"
        note = (
            f"At SNR >= 100 every validation trace was within +/-3% of the true area "
            f"(worst {v['snr100_max_err_pct']}%)."
        )
    if points < 7:
        note += (
            f" With fewer than 7 points across the peak precision is about half as good "
            f"(validation: ~{v['coarse_snr50_rel_sd_pct']}% SD at SNR 50)."
        )
    note += f" Validated on {v['conditions']}; SNR here is {v['snr_definition']}."
    return {"tier": tier, "note": note}


def _crossing(x0: float, y0: float, x1: float, y1: float, level: float) -> float:
    if y1 == y0:
        return x0
    return x0 + (level - y0) * (x1 - x0) / (y1 - y0)


BACKGROUND_WINDOW = 101  # points; must be much wider than a peak
BACKGROUND_PERCENTILE = 20


def local_background(y: np.ndarray) -> np.ndarray:
    """Rolling low percentile: a drift-following background used to find bounds."""
    from simplymz_mcp.analytics.runcard import rolling_percentile

    n = y.size
    window = min(BACKGROUND_WINDOW, n if n % 2 else n - 1)
    if window < 3:
        return np.full(n, float(np.min(y)) if n else 0.0)
    return rolling_percentile(y.astype(np.float64), window, BACKGROUND_PERCENTILE)


def smooth(y: np.ndarray) -> np.ndarray:
    """Savitzky-Golay (5 points, quadratic): used only to find bounds, never for areas."""
    if y.size < 5:
        return y.astype(np.float64)
    return np.asarray(savgol_filter(y, 5, 2), dtype=np.float64)


def auto_bounds(y: np.ndarray, apex: int, noise: float, base: float = 0.0) -> tuple[int, int, bool]:
    """Find bounds on the smoothed trace: walk out from the apex to the threshold (or a
    valley: the smoothed signal rises again by more than 2x noise), then extend each side
    by the same distance so the bounds sit on baseline rather than on the peak's tails.
    Extension stops early if the signal climbs above the threshold (a neighbouring peak)."""
    ys = smooth(y)
    lo, hi = max(apex - 2, 0), min(apex + 3, ys.size)
    apex = lo + int(np.argmax(ys[lo:hi]))  # walk from the smoothed apex
    h = float(ys[apex]) - base
    stop = base + max(3.0 * noise, STOP_FRACTION * h)
    rise = 2.0 * noise
    overlap = False

    def walk(step: int) -> int:
        nonlocal overlap
        i, low = apex, apex
        while 0 <= i + step < ys.size and ys[i] > stop:
            i += step
            if ys[i] < ys[low]:
                low = i
            elif (
                ys[i] > ys[low] + rise
                and ys[i] > stop
                and ys[apex] - ys[low] > 2.0 * rise  # a real descent happened first
            ):  # climbing a neighbour
                overlap = overlap or ys[low] > base + VALLEY_FRACTION * h
                return low
        return i

    left, right = walk(-1), walk(+1)
    if not overlap:
        ext_l = max(left - (apex - left), 0)
        while left > ext_l and ys[left - 1] <= stop:
            left -= 1
        ext_r = min(right + (right - apex), y.size - 1)
        while right < ext_r and ys[right + 1] <= stop:
            right += 1
    return left, right, overlap


def flank_baseline(
    rt: np.ndarray,
    y: np.ndarray,
    detrended: np.ndarray,
    a: int,
    b: int,
    stop: float,
    width: int,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Baseline anchors from points just outside [a, b] that are below ``stop``.

    Returns ((t_left, y_left), (t_right, y_right)) as medians of each flank, or None when
    neither flank has points (the caller then uses the bound points)."""
    lf = np.arange(max(a - width, 0), a)
    rf = np.arange(b + 1, min(b + 1 + width, y.size))
    lf = lf[detrended[lf] <= stop]  # exclude points belonging to other peaks
    rf = rf[detrended[rf] <= stop]
    if lf.size == 0 and rf.size == 0:
        return None
    if lf.size == 0:
        lf = rf
    if rf.size == 0:
        rf = lf
    return (
        (float(np.median(rt[lf])), float(np.median(y[lf]))),
        (float(np.median(rt[rf])), float(np.median(y[rf]))),
    )


def _width_at(
    rt: np.ndarray, net: np.ndarray, a: int, apex: int, b: int, level: float
) -> tuple[float | None, float | None]:
    """Left/right times where the net signal crosses ``level`` (linear interpolation)."""
    left = right = None
    for i in range(apex, a, -1):
        if net[i - 1] <= level < net[i]:
            left = _crossing(rt[i - 1], net[i - 1], rt[i], net[i], level)
            break
    for i in range(apex, b):
        if net[i + 1] <= level < net[i]:
            right = _crossing(rt[i], net[i], rt[i + 1], net[i + 1], level)
            break
    return left, right


def integrate(
    rt: np.ndarray,
    y: np.ndarray,
    rt_start: float | None = None,
    rt_end: float | None = None,
    apex_rt: float | None = None,
) -> dict[str, Any]:
    """Integrate one peak. Bounds are given or found automatically around the apex.

    Area: trapezoid of (signal - linear baseline between the bound points), clipped at 0,
    in counts x min. Height: apex minus baseline. FWHM by interpolation. Asymmetry factor
    at 10% height = trailing / leading half-width. SNR = height / first-difference noise of
    the trace outside the bounds.
    """
    if rt.size < 3:
        raise ValueError("need at least 3 points")
    warnings: list[str] = []
    if rt_start is not None and rt_end is not None:
        a = int(np.searchsorted(rt, rt_start, side="left"))
        b = int(np.searchsorted(rt, rt_end, side="right")) - 1
        if b - a < 2:
            raise ValueError("integration window contains fewer than 3 points")
        apex = a + int(np.argmax(y[a : b + 1]))
        overlap = False
        mode = "user"
    else:
        if apex_rt is not None:
            centre = int(np.argmin(np.abs(rt - apex_rt)))
            lo, hi = max(centre - 3, 0), min(centre + 4, rt.size)
            apex = lo + int(np.argmax(y[lo:hi]))
        else:
            apex = int(np.argmax(y))
        detrended = y - local_background(y)
        noise_all = noise_level(detrended)
        base_level = float(np.median(detrended))  # residual level left by the detrending
        a, b, overlap = auto_bounds(detrended, apex, noise_all, base_level)
        # The walk starts from the smoothed apex; on noisy traces that can sit a few scans
        # from the raw maximum. Bounds must contain the raw apex and span >= 3 points.
        a, b = min(a, apex), max(b, apex)
        while b - a < 2 and (a > 0 or b < rt.size - 1):
            a, b = max(a - 1, 0), min(b + 1, rt.size - 1)
        mode = "auto"
    if overlap:
        warnings.append(
            "Overlapping peak: integration stopped at a valley above 5% of the "
            "apex; the area ends at the valley and is "
            "approximate."
        )
    if a == 0 or b == rt.size - 1:
        warnings.append(
            "Integration reaches the edge of the trace (start/end of acquisition "
            "or RT window); part of the peak may be missing from the area."
        )
    if apex in (a, b):
        warnings.append("Apex lies on an integration bound; the peak may be cut off.")
    t, s = rt[a : b + 1], y[a : b + 1]
    anchors = None
    if mode == "auto" and not overlap:
        h_guess = float(detrended[apex]) - base_level
        stop = base_level + max(3.0 * noise_all, STOP_FRACTION * h_guess)
        anchors = flank_baseline(rt, y, detrended, a, b, stop, width=max(5, b - a + 1))
    if anchors is None:
        (t0, y0), (t1, y1) = (float(t[0]), float(s[0])), (float(t[-1]), float(s[-1]))
        baseline_mode = "bound points"
    else:
        (t0, y0), (t1, y1) = anchors
        baseline_mode = "median of flanking points below threshold"
    slope = (y1 - y0) / (t1 - t0) if t1 != t0 else 0.0
    baseline = y0 + slope * (t - t0)
    net = s - baseline  # signed: clipping negative noise would bias areas upward
    area = float(np.trapezoid(net, t))
    k = apex - a
    height = float(net[k])
    half_l, half_r = _width_at(t, net, 0, k, len(t) - 1, 0.5 * height)
    ten_l, ten_r = _width_at(t, net, 0, k, len(t) - 1, 0.1 * height)
    fwhm = half_r - half_l if half_l is not None and half_r is not None else None
    t_apex = float(t[k])
    if 0 < k < len(t) - 1:  # parabolic vertex through the top three points
        y0, y1, y2 = float(net[k - 1]), float(net[k]), float(net[k + 1])
        denom = y0 - 2 * y1 + y2
        if denom < 0:
            t_apex += 0.5 * (y0 - y2) / denom * float(t[k + 1] - t[k])
    asym = None
    if ten_l is not None and ten_r is not None and t_apex - ten_l > 0:
        asym = (ten_r - t_apex) / (t_apex - ten_l)
    outside = np.concatenate([y[:a], y[b + 1 :]])
    noise = noise_level(outside) if outside.size >= 3 else 0.0
    snr = height / noise if noise > 0 else None
    if snr is None:
        warnings.append("No measurable noise outside the peak; SNR is undefined.")
    if fwhm is None:
        warnings.append("Half-height crossing not found inside the bounds; FWHM undefined.")
    points = int(np.count_nonzero(net >= 0.05 * height)) if height > 0 else 0  # peak body
    if points < 7:
        warnings.append(f"Only {points} points across the peak; area and shape are imprecise.")
    return {
        "rt_apex_min": round(float(rt[apex]), 4),
        "rt_start_min": round(float(t[0]), 4),
        "rt_end_min": round(float(t[-1]), 4),
        "area_counts_min": float(f"{area:.6g}"),
        "height_counts": float(f"{height:.6g}"),
        "fwhm_min": round(fwhm, 5) if fwhm is not None else None,
        "asymmetry_10pct": round(asym, 3) if asym is not None else None,
        "snr": round(snr, 1) if snr is not None else None,
        "noise_counts": float(f"{noise:.4g}"),
        "points_across_peak": points,
        "area_precision": area_precision(round(snr, 1) if snr is not None else None, points),
        "bounds_mode": mode,
        "overlap": overlap,
        "warnings": warnings,
        "method": {
            "area": f"trapezoid of signal minus linear baseline ({baseline_mode}), signed",
            "noise": "1.4826*MAD(first differences)/sqrt(2), outside bounds",
            "asymmetry": "trailing/leading half-width at 10% height",
            "auto_bounds": f"walk out to max(3*noise, {STOP_FRACTION:.1%} apex) or valley, "
            "then extend by the same distance while below threshold",
        },
    }
