"""masstrace-lite: the built-in feature detector (ADR 0001, plan M3.T2).

1. Mass traces: MS1 centroids above ``min_intensity`` joined across consecutive scans when
   within ``ppm`` of the trace's running intensity-weighted m/z (gap of ``max_gap`` scans
   allowed). Brighter centroids claim traces first.
2. Peaks on each trace (a trace may hold several elution peaks), integrated with the same
   integrator as integrate_peak.
3. Grouping: 13C isotopes (delta 1.003355/z, co-eluting, less intense) and common adducts
   (fixed mass differences, co-eluting).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.signal import find_peaks

from simplymz_mcp.analytics.integrate import integrate
from simplymz_mcp.io.mzml import RunData

ISOTOPE_DELTA = 1.003355
ISOTOPE_TOL_DA = 0.015  # absorbs fine-structure shifts (e.g. 34S vs 13C2)
# (name, mass difference to the [M+H]+ / [M-H]- partner, polarity)
ADDUCT_DELTAS = [
    ("[M+Na]+ vs [M+H]+", 21.981945, 1),
    ("[M+NH4]+ vs [M+H]+", 17.026549, 1),
    ("[M+K]+ vs [M+H]+", 37.955882, 1),
    ("[M+Cl]- vs [M-H]-", 35.976678, -1),
    ("[M+FA-H]- vs [M-H]-", 46.005480, -1),
]


@dataclass
class DetectorParams:
    ppm: float = 10.0
    min_intensity: float | None = None  # None -> 3 x median MS1 centroid intensity
    max_gap: int = 4  # real centroids drop out intermittently (M5.T3, OpenMS comparison)
    min_points: int = 4
    min_rel_prominence: float = 0.1

    def as_dict(self) -> dict[str, Any]:
        return {
            k: getattr(self, k)
            for k in ("ppm", "min_intensity", "max_gap", "min_points", "min_rel_prominence")
        }


@dataclass
class _Trace:
    start: int  # MS1 ordinal of first point
    scans: list[int] = field(default_factory=list)
    mzs: list[float] = field(default_factory=list)
    ints: list[float] = field(default_factory=list)
    wsum: float = 0.0
    mzw: float = 0.0

    @property
    def mz(self) -> float:
        return self.mzw / self.wsum

    def add(self, k: int, mz: float, it: float) -> None:
        self.scans.append(k)
        self.mzs.append(mz)
        self.ints.append(it)
        self.wsum += it
        self.mzw += mz * it


def build_traces(
    run: RunData, p: DetectorParams, min_intensity: float, check: Any = None
) -> tuple[list[_Trace], np.ndarray]:
    ms1 = np.flatnonzero(run.scans.ms_level == 1)
    rt = run.scans.rt_min[ms1]
    active: list[_Trace] = []
    done: list[_Trace] = []
    for k, i in enumerate(ms1):
        if check is not None and k % 50 == 0:
            check(k / max(len(ms1), 1))
        still: list[_Trace] = []
        for t in active:
            (still if t.scans[-1] >= k - 1 - p.max_gap else done).append(t)
        active = still
        mz, it = run.peaks(int(i))
        keep = it >= min_intensity
        mz, it = mz[keep], it[keep]
        if mz.size == 0:
            continue
        active.sort(key=lambda t: t.mz)
        act_mz = np.array([t.mz for t in active]) if active else np.empty(0)
        taken = np.zeros(len(active), dtype=bool)
        for j in np.argsort(it)[::-1]:
            m = float(mz[j])
            tol = m * p.ppm * 1e-6
            best = -1
            if act_mz.size:
                a = int(np.searchsorted(act_mz, m - tol))
                b = int(np.searchsorted(act_mz, m + tol, side="right"))
                cands = [c for c in range(a, b) if not taken[c] and active[c].scans[-1] < k]
                if cands:
                    best = min(cands, key=lambda c: abs(act_mz[c] - m))
            if best >= 0:
                active[best].add(k, m, float(it[j]))
                taken[best] = True
            else:
                t = _Trace(start=k)
                t.add(k, m, float(it[j]))
                active.append(t)
                # keep arrays aligned: new traces are matched from the next scan on
                act_mz = np.append(act_mz, np.inf)
                taken = np.append(taken, True)
    done.extend(active)
    return [t for t in done if len(t.scans) >= p.min_points], rt


def _peaks_on_trace(t: _Trace, rt_all: np.ndarray, p: DetectorParams) -> list[dict[str, Any]]:
    k0, k1 = t.scans[0], t.scans[-1]
    pad = 3
    lo, hi = max(k0 - pad, 0), min(k1 + pad, rt_all.size - 1)
    rt = rt_all[lo : hi + 1]
    y = np.zeros(rt.size)
    mzs = np.full(rt.size, np.nan)
    for k, m, it in zip(t.scans, t.mzs, t.ints, strict=True):
        y[k - lo] = it
        mzs[k - lo] = m
    # Missing scans inside the trace (allowed gaps) are interpolated, not zeroed: a zero
    # would create a false valley and split one peak in two.
    inside = np.arange(k0 - lo, k1 - lo + 1)
    have = ~np.isnan(mzs[inside])
    if not have.all():
        y[inside[~have]] = np.interp(inside[~have], inside[have], y[inside[have]])
    ymax = float(np.max(y))
    idx, _ = find_peaks(np.concatenate([[0.0], y, [0.0]]), prominence=p.min_rel_prominence * ymax)
    out: list[dict[str, Any]] = []
    seen: set[tuple[float, float]] = set()
    for i in idx - 1:
        try:
            r = integrate(rt, y, apex_rt=float(rt[i]))
        except ValueError:
            continue
        a = int(np.searchsorted(rt, r["rt_start_min"]))
        b = int(np.searchsorted(rt, r["rt_end_min"], side="right"))
        w = y[a:b]
        seg = mzs[a:b]
        ok = ~np.isnan(seg)
        bounds = (r["rt_start_min"], r["rt_end_min"])
        if not ok.any() or r["height_counts"] <= 0 or bounds in seen:
            continue
        seen.add(bounds)
        out.append(
            {
                "mz": round(float(np.sum(seg[ok] * w[ok]) / np.sum(w[ok])), 6),
                "rt_min": r["rt_apex_min"],
                "rt_start_min": r["rt_start_min"],
                "rt_end_min": r["rt_end_min"],
                "height": r["height_counts"],
                "area": r["area_counts_min"],
                "fwhm_min": r["fwhm_min"],
                "snr": r["snr"],
                "n_points": int(ok.sum()),
            }
        )
    return out


def group_isotopes_and_adducts(feats: list[dict[str, Any]], polarity: int, rt_tol: float) -> None:
    """Annotate in place: isotope_of/isotope_index/charge and adduct_group."""
    order = sorted(range(len(feats)), key=lambda i: -feats[i]["height"])
    for i in order:
        f = feats[i]
        f.setdefault("isotope_of", None)
        f.setdefault("isotope_index", 0)
        f.setdefault("charge", 1)
        f.setdefault("adduct_group", None)
    owners: set[str] = set()
    for i in order:
        f = feats[i]
        if f["isotope_of"] is not None:
            continue
        for z in (1, 2):
            found = False
            for n in (1, 2, 3):
                target = f["mz"] + n * ISOTOPE_DELTA / z
                # Isotopes are below 1.5x the monoisotopic peak (Cl/Br M+2 can be ~100%),
                # and a feature that already owns isotopes is a monoisotope itself.
                cands = [
                    j
                    for j in order
                    if j != i
                    and feats[j]["isotope_of"] is None
                    and feats[j]["id"] not in owners
                    and abs(feats[j]["mz"] - target) <= ISOTOPE_TOL_DA / z
                    and abs(feats[j]["rt_min"] - f["rt_min"]) <= rt_tol
                    and feats[j]["height"] < 1.5 * f["height"]
                ]
                if not cands:
                    if n == 1:
                        break
                    continue  # e.g. Cl: M+1 weak but present, M+2 strong; allow skipping
                j = min(cands, key=lambda j: abs(feats[j]["mz"] - target))
                feats[j].update(isotope_of=f["id"], isotope_index=n, charge=z)
                owners.add(f["id"])
                found = True
            if found:
                f["charge"] = z
                break
    mono = [f for f in feats if f["isotope_of"] is None]
    group = 0
    for a in mono:
        for name, delta, pol in ADDUCT_DELTAS:
            if pol != polarity:
                continue
            for b in mono:
                if b is a or abs(b["rt_min"] - a["rt_min"]) > rt_tol:
                    continue
                if abs((b["mz"] - a["mz"]) - delta) <= 0.005:
                    gid = a["adduct_group"] or b["adduct_group"]
                    if gid is None:
                        group += 1
                        gid = f"A{group}"
                    a["adduct_group"] = b["adduct_group"] = gid
                    b.setdefault("adduct_relation", name)


def detect_features(
    run: RunData, params: DetectorParams | None = None, check: Any = None
) -> dict[str, Any]:
    p = params or DetectorParams()
    ms1 = run.scans.ms_level == 1
    all_int = (
        np.concatenate([run.peaks(int(i))[1] for i in np.flatnonzero(ms1)])
        if ms1.any()
        else np.empty(0)
    )
    noise = float(np.median(all_int)) if all_int.size else 0.0
    min_int = p.min_intensity if p.min_intensity is not None else 3.0 * noise
    traces, rt = build_traces(run, p, min_int, check)
    feats: list[dict[str, Any]] = []
    for t in traces:
        feats.extend(_peaks_on_trace(t, rt, p))
    feats.sort(key=lambda f: (f["rt_min"], f["mz"]))
    for n, f in enumerate(feats, start=1):
        f["id"] = f"F{n:05d}"
    interval = float(np.median(np.diff(rt))) if rt.size > 1 else 0.05
    pol = int(np.sign(np.median(run.scans.polarity[ms1]))) if ms1.any() else 1
    group_isotopes_and_adducts(feats, pol or 1, rt_tol=max(interval * 0.6, 0.02))
    params_out = {**p.as_dict(), "min_intensity": round(min_int, 3), "engine": "masstrace-lite"}
    return {"features": feats, "params": params_out, "n_traces": len(traces)}
